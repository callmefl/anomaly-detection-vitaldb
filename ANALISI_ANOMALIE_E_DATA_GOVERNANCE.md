# Analisi delle anomalie e della Data Governance

**Progetto:** Anomaly Detection su VitalDB  
**Data della revisione:** 9 ottobre 2026  
**Ambito:** revisione statica di sorgenti, configurazioni e artefatti locali. Nessun file esistente è stato modificato.

## Sintesi

Il repository implementa un flusso locale a livelli: file Parquet Bronze e Silver, MongoDB Time Series Gold, registry, API FastAPI e dashboard. È un prototipo locale ispirato a una Medallion Architecture e ad alcuni principi lakehouse; non dispone però di un transaction log né di una pubblicazione atomica dei dati end-to-end.

Le evidenze quantitative disponibili sono quelle nei report locali, generati il 2 ottobre 2026: 50 casi, 644.637 righe Bronze e 311.173 righe Silver, con il 26% di celle vitali ancora nulle in Silver. I report non sono una verifica dello stato MongoDB attuale. Docker Desktop non era raggiungibile durante la revisione; non è stato possibile avviare la pipeline o verificare le collection live.

## 1. Anomalie presenti e causa

Le voci sono divise tra **difetti verificabili dal codice o dagli artefatti** e **rischi di runtime da riprodurre**.

### 1.1 Difetti verificabili

| Priorità | Anomalia | Perché è un problema / causa |
|---|---|---|
| Alta | La validazione JSON Schema è configurata su `vital_signals`. | MongoDB non supporta le regole di schema validation nelle Time Series. `mongo/vital_signals_schema.js` usa `collMod` e dichiara che `moderate` valida i nuovi inserimenti, ma questa configurazione non è un vincolo di qualità valido per la collection. Lo script può inoltre segnalare un errore durante l’inizializzazione. La validazione sul registry, che è una collection normale, è un caso distinto. |
| Alta | L’interpolazione e il forward-fill non rispettano necessariamente il tempo reale. | `src/silver/clean.py` rimuove prima le righe con tutte le metriche nulle, quindi applica `interpolate(..., limit=5)` e `ffill(limit=300)`. I limiti contano righe superstiti, non secondi; dopo i drop, righe adiacenti possono distare più di un secondo. Inoltre l’interpolazione lineare usa la posizione delle righe, non `Time`. Il commento “5 secondi” / “300 secondi” non è garantito dai calcoli. |
| Alta | La completezza Gold è dichiarata pari a zero nulli senza misurare i mancanti originali. | `build_records()` omette i campi metrici nulli e scarta le righe senza metriche. `src/analysis/benchmark_etl.py` imposta `null_pct_gold` a `0.0` in modo fisso. L’assenza di null nei documenti scritti non equivale alla completezza della serie: i mancanti sono stati omessi, non recuperati. |
| Alta | Il caricamento Gold non è atomico e il retry può duplicare le misure. | `src/gold/load_mongo.py` inserisce prima i documenti Time Series e poi il registry. Un errore a metà di `insert_many` può lasciare dati parziali; un errore nella scrittura del registry lascia dati senza catalogo. Al retry, il controllo del registry non trova il caso e può reinserire i documenti già scritti. MongoDB non consente scritture Time Series dentro una transazione. |
| Alta | Le anomalie già persistite possono diventare obsolete. | `save_anomalies_to_mongo()` cancella le anomalie precedenti solo per i casi presenti nei nuovi documenti anomali. Se il nuovo run non trova anomalie per un caso, lascia nel database quelle del run precedente. Se la cancellazione riesce e l’inserimento fallisce, il risultato precedente è perso. |
| Media | I flag qualità non guidano la detection e `nibp_age_s` si perde in Gold. | Gold serializza i flag `quality_flags`, ma `load_from_gold()` proietta solo timestamp, metadata e metriche. La detection non vede i flag Silver; inoltre `build_records()` non salva `nibp_age_s`. Regole e modelli possono così usare valori imputati o già segnalati senza poterli distinguere. |
| Media | La valutazione ML e l’esecuzione dalla dashboard non sono confrontabili direttamente. | La valutazione addestra i modelli sui casi complessivi; l’endpoint `/cases/{case_id}/detect` li riaddestra sul singolo caso. Cambiano popolazione, distribuzione e soglie effettive. L’autoencoder calcola inoltre scaling e soglia percentile sugli stessi dati usati per il fit, quindi i risultati non sono una misura di generalizzazione su dati indipendenti. |
| Media | README e risultati numerici sono incoerenti. | Il README riporta 3,88 MB Bronze, 2,24 MB Silver, 0,27 MB Gold, oltre 150× di speedup e F1 0,92. I report locali del 2 ottobre riportano invece 3,88 / 2,72 / 0,58 MB, 3,7×, F1 anomalia 0,073 per Isolation Forest e 0,091 per autoencoder. Il 92,56% nei dati locali è l’accuratezza del classificatore banale “sempre normale”, non quella di Isolation Forest. |
| Media | La percentuale residua di nulli in Silver è alta e oltre metà delle righe viene eliminata. | `quality_report.json` registra 644.637 righe originali, 311.173 mantenute, 333.464 eliminate e il 26% di celle vitali nulle residue. Il drop è intenzionale per righe totalmente vuote, ma elimina oltre metà dei timestamp Bronze e il report non documenta la copertura temporale persa per caso o per sensore. |
| Media | Il download dei dati di laboratorio promesso nella descrizione non è implementato. | `src/bronze/download.py` scarica tracce e dati clinici `/cases`, ma non chiama `vitaldb.load_lab_data()` e non salva un dataset di laboratorio. Il perimetro effettivo è più ristretto di quello descritto in `SKILL.md` e nella dashboard. |
| Media | L’API può dichiarare il database sano quando Mongo non risponde. | `api/main.py::health()` cattura l’eccezione, azzera i conteggi e restituisce comunque `status: ok`. La UI può quindi mostrare MongoDB come disponibile durante un errore di connessione. |
| Bassa | Il requisito PyTorch nel Dockerfile può essere interpretato dalla shell come redirezione. | In `Dockerfile`, `torch>=2.0` non è quotato. Il carattere `>` può essere trattato come operatore di redirezione invece che parte del requisito; il comando non esprime in modo affidabile il vincolo di versione voluto. `requirements.txt` contiene una seconda installazione di Torch, ma il primo comando resta ambiguo e sporca il build. |
| Bassa | Il README dichiara 12 test complessivi, ma nel codice se ne contano 24. | Il totale statico delle funzioni `test_` è 24 distribuite nei file `tests/`. La suite API dipende inoltre da un Mongo raggiungibile e il test di detection può scrivere nel database: non è completamente isolata come test unitario. |

### 1.2 Rischi runtime non riprodotti

- L’inizializzazione di `vital_signals_schema.js` può fallire perché le regole di schema validation non sono supportate sulle Time Series. Non è stato possibile osservare i log del container in questa sessione.
- Non è stato verificato se i report locali corrispondano alle collection Gold attualmente presenti; gli artefatti hanno data di generazione 2 ottobre 2026.
- Non sono stati eseguiti test né pipeline. I test API possono interagire con Mongo e il test di detection scrive risultati: la revisione è rimasta statica e in sola lettura.

## 2. Fix e suggerimenti per le anomalie

Gli interventi seguenti conservano il flusso Bronze → Silver → Gold e non richiedono di introdurre un altro motore dati.

| Anomalia | Correzione pratica | Motivo |
|---|---|---|
| Validazione Time Series | Rimuovere il validator dalla Time Series. Validare i record in Python prima dell’inserimento; mantenere JSON Schema sul registry e, se utile, usare una collection normale di staging per validare i payload. | Il controllo avviene in un punto supportato e può rifiutare dati malformati prima che arrivino in Gold. |
| Pulizia non basata sui secondi | Preservare l’asse `Time`; definire i gap usando differenze temporali reali. Interpolare solo gap interni entro 5 secondi e fare LOCF NIBP solo se l’età della misura è ≤300 secondi. | Fa coincidere la regola dichiarata con quella applicata anche in presenza di righe rimosse o campionamento irregolare. |
| Gold con nulli “zero” | Calcolare la completezza per metrica e caso prima e dopo ogni trasformazione; definire esplicitamente se il denominatore include tutte le celle attese o solo i valori emessi. Eliminare il valore fisso `0.0`. | Evita di presentare l’omissione dei null come recupero dei dati. |
| Retry Gold duplicabile | Creare un identificativo di run/generazione. Scrivere le misure marcandole con tale identificativo e pubblicare la generazione nel registry solo dopo controlli di conteggio e qualità. Le query leggono solo la generazione attiva. In alternativa, registrare stati `STARTED`, `COMMITTED`, `FAILED` e avere un recupero esplicito dei run incompleti. | Il registry diventa un puntatore di pubblicazione logica: le misure parziali non risultano attive. Non sostituisce l’atomicità fisica, ma rende il retry controllabile. |
| Anomalie stale | Persistire il risultato per `case_id + run_id` o usare una collection risultati versionata; pubblicare il nuovo run solo a completamento. Gestire anche il run con zero anomalie. | Un risultato vuoto deve poter sostituire in modo coerente il risultato precedente. |
| Flag ignorati / età NIBP persa | Aggiungere `nibp_age_s`, flag e indicatori di imputazione ai documenti Gold o a un record qualità collegato; includerli nella proiezione della detection. Definire se i valori imputati entrano nelle regole cliniche e nei modelli. | Rende osservabile la qualità durante l’analisi e impedisce di confondere misurazione e imputazione. |
| Metriche ML non confrontabili | Usare la stessa strategia train/threshold per report e API. Separare per caso o per tempo i dati di addestramento e test; riportare PR-AUC, precision, recall, F1, base rate e soglia con metodo e versione. | Misura la generalizzazione e rende confrontabili i numeri tra valutazione e uso nella dashboard. |
| Numeri README/UI stale | Rigenerare README e dashboard dai report correnti oppure mostrare data di generazione e “dato non disponibile” senza fallback numerici presentati come live. Correggere la descrizione dell’accuratezza 92,56%. | Evita che risultati vecchi o baseline siano attribuiti ai modelli correnti. |
| Perdita temporale e null Silver | Registrare righe scartate e copertura per caso/sensore, oltre alla percentuale di celle nulle. Aggiungere una soglia di qualità che impedisca la promozione a Gold quando il caso non la soddisfa. | La pipeline può completarsi tecnicamente ma pubblicare serie con copertura insufficiente; un gate rende il problema visibile. |
| Lab assenti | Allineare la documentazione all’ambito effettivo oppure implementare il download lab con file Bronze, manifest e provenienza. | Evita che interfaccia e relazione dichiarino dati non presenti. |
| Health check | Restituire stato non sano o HTTP 503 se Mongo non risponde; includere un controllo ping e distinguere `api` da `database`. | La UI e l’orchestrazione ricevono uno stato rappresentativo. |
| Dockerfile | Scrivere il requisito come `"torch>=2.0"` e mantenere un’unica strategia d’installazione CPU; bloccare le dipendenze per build riproducibili. | Evita la redirezione involontaria e riduce differenze tra build. |
| Suite e documentazione | Aggiornare il numero dei test e isolare i test API con un database di test/mocking; documentare chiaramente quali test sono unitari e quali richiedono Mongo. | Riduce dipendenze ambientali e impedisce effetti collaterali sui dati usati dalla dashboard. |

## 3. Data Governance e Data Quality: situazione e migliorie motivate

### Situazione attuale

La governance esiste in forma artigianale e distribuita:

- **Catalogo:** `registry` conserva `case_id`, `record_count`, `schema_version` e una provenance minima (`step`, timestamp).
- **Metadata delle misure:** `metadata` è il `metaField` con `case_id`, sensore, reparto, età e sesso. Essendo ripetuto per tutte le misure dello stesso caso, supporta filtri per caso e raggruppamento dei bucket.
- **Metadata delle tracce:** `track_metadata` descrive nome della traccia, unità e range atteso, ma è popolata da uno script Mongo separato e non è collegata in modo automatico alla trasformazione o alla validazione di ogni record.
- **Qualità Silver:** il report JSON conteggia righe, scarti, nulli e flag outlier per caso; le copie precedenti sono archiviate in `quality_history`.
- **Enforcement:** il registry ha validator JSON Schema; la Time Series no. Mongo documenta che le regole di schema validation non sono supportate sulle Time Series.
- **Atomicità:** l’ordine “misure prima, registry dopo” riduce i casi fantasma, ma non fornisce commit/rollback tra i due passaggi. Mongo documenta che non è possibile scrivere in una Time Series dentro una transazione.

Questa soluzione è sufficiente per dimostrare metadata, catalogo, partizionamento e controlli di qualità in un prototipo. Va descritta come **architettura locale ispirata al lakehouse con catalogo e pubblicazione applicativa**, non come lakehouse nativo con transazioni e transaction log.

### Gap di governance che incidono sulla qualità

1. **Provenienza insufficiente per ricostruire un risultato.** Il registry non registra run ID, checksum o versione del Bronze, sorgente/API e data di estrazione, commit del codice, parametri di cleaning, intervallo di campionamento, versione delle regole qualità o versione del modello. `schema_version: 1.0` da sola non identifica la trasformazione.
2. **Qualità non collegata alla promozione.** Il report viene prodotto, ma non risulta un criterio che blocchi Gold quando nulli, scarti, outlier o copertura superano una soglia.
3. **Imputazione non tracciata abbastanza.** I valori interpolati o propagati non sono marcati per metrica; `nibp_age_s` viene calcolato ma non arriva a Gold. Chi usa il dato non può sempre distinguere misura reale e valore imputato.
4. **Semantica temporale debole.** Gold costruisce timestamp usando `2020-01-01 + Time`. È un espediente per ordinare la serie, non la data reale dell’intervento. Il timestamp dovrebbe essere documentato come offset sintetico o rappresentato con un campo esplicito `elapsed_seconds`/`relative_time`, evitando che venga interpretato come data clinica reale.
5. **Range documentati e regole non pienamente allineati.** `track_metadata` contiene range attesi, mentre il cleaning implementa range nel codice. Senza un’unica fonte versionata, le due definizioni possono divergere; ad esempio i limiti DBP differiscono tra schema metadata e cleaning.
6. **Report non omogenei tra layer.** Bronze/Silver hanno conteggi locali; Gold usa misure omesse e un null rate hardcoded a zero. Non è possibile confrontare la completezza tra i tre layer con la metrica corrente.
7. **Governance locale e non coordinata.** I Parquet e i report restano file locali, mentre il registry è in Mongo. Non c’è un manifest unico che colleghi file, trasformazione, report e generazione pubblicata. La riproducibilità dipende dagli artefatti presenti sulla macchina.

### Migliorie incrementali consigliate

| Area | Miglioria | Motivazione e risultato atteso |
|---|---|---|
| Catalogo/provenienza | Estendere il registry con `run_id`, stato, date di inizio/fine, versione del codice, versione schema/trasformazione, parametri ETL, fonte e checksum input, conteggi per fase, record scartati e ID del quality report. | Ogni caso diventa riconducibile a uno specifico input e a una specifica trasformazione; un retry non viene confuso con un caricamento già pubblicato. |
| Pubblicazione Gold | Usare generazioni immutabili e un puntatore `active_run_id` nel registry; controllare i conteggi Bronze→Silver→Gold e promuovere solo run completi. | Simula un commit logico in una collection normale, senza dichiarare una transazione sulle Time Series. I lettori vedono una generazione completa. |
| Contratto metadata | Definire un unico catalogo versionato delle tracce con nome sorgente, nome Gold, unità, tipo, frequenza attesa, range, semantica temporale e regole missing/outlier. Caricarlo sia nel cleaning sia nella preparazione Gold. | Evita definizioni duplicate e range divergenti; il contratto spiega che cosa significa ciascun valore. |
| Validazione dati | Validare in Python lo schema dei payload Gold e aggiungere controlli di dominio: timestamp monotoni, case ID valido, range numerici, campi richiesti, unità attese e coerenza tra SBP/DBP/MBP. | Compensa il limite di schema validation sulle Time Series e intercetta dati errati prima della scrittura. Mantenere il validator Mongo sul registry. |
| Missingness/imputazione | Per ogni metrica conservare almeno stato osservato/imputato/mancante, tecnica di imputazione e, per NIBP, età in secondi. Non riempire gap oltre la durata ammessa e non cancellare l’informazione che la misura era assente. | Permette di controllare l’impatto dell’imputazione sulle statistiche, sulle regole cliniche e sui modelli. |
| Metriche DQ | Produrre metriche comparabili per metrica e caso: percentuale missing, imputata, scartata, outlier, duplicati, copertura temporale e durata massima dei gap. Calcolare lo stesso insieme su Bronze, Silver e Gold con denominatore esplicito. | Localizza se il degrado nasce dalla sorgente, dal cleaning o dal caricamento e rimuove il falso `0%` Gold. |
| Gate qualità | Definire soglie esplicite, inizialmente in modalità report-only, poi bloccare la promozione Gold se la copertura è insufficiente o i controlli strutturali falliscono. | Introduce governance operativa gradualmente senza cambiare l’ordine dei layer. Ogni eccezione può essere registrata nel registry. |
| Data lineage dashboard | Mostrare data del report, run ID, versione schema/cleaning e conteggi per layer; etichettare dati stimati e report non aggiornati. | La dashboard diventa una vista verificabile del catalogo, anziché presentare valori statici come se fossero correnti. |
| Privacy e minimizzazione | Valutare se età, sesso e reparto servano davvero replicati nel `metaField`; mantenere solo attributi necessari e documentare le regole di accesso/esportazione. | Riduce la duplicazione di dati clinici e rende più chiara la governance degli attributi personali, anche in un prototipo locale. |

### Come presentare correttamente il risultato

La formulazione più precisa è: **“Abbiamo implementato localmente una pipeline Bronze/Silver su Parquet e un layer Gold MongoDB Time Series, con metadata applicativi, registry, report di qualità e una strategia di pubblicazione compensativa. La soluzione emula alcuni aspetti di catalogazione e governance del lakehouse, ma non fornisce transazioni atomiche sulle misure Time Series né un transaction log nativo.”**

La qualità risente dell’esecuzione in modo misurabile: il report locale mostra una riduzione delle celle nulle dal 67,6% Bronze al 26,0% Silver, ma anche la rimozione di 333.464 righe su 644.637. Il valore Gold `0.0%` non è un miglioramento dimostrato: deriva da una metrica codificata fissa e dall’omissione dei campi mancanti. Per valutare davvero il beneficio del cleaning servono completezza per sensore, copertura temporale e quantità/età dei valori imputati.

## Riferimenti

- [MongoDB Manual — Time Series Collection Limitations](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-limitations/): schema validation non supportata e scritture Time Series non consentite nelle transazioni.
- [MongoDB Manual — Time Series Indexes](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-index/): comportamento e considerazioni sugli indici Time Series.
- Codice di riferimento: `src/silver/clean.py`, `src/gold/load_mongo.py`, `src/detection/detector.py`, `src/analysis/benchmark_etl.py`, `src/analysis/evaluate_models.py`, `api/main.py`, `mongo/vital_signals_schema.js`, `README.md`.
