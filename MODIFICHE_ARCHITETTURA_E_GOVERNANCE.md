# SINTESI DELLE 10 MODIFICHE ARCHITETTURALI E DI DATA GOVERNANCE
**Progetto:** VitalDB Multimodal Real-Time Anomaly Detection & Lakehouse Architecture  
**Documento per:** Allineamento Relazione Tecnica e Presentazione Slide (PPT)  
**Versione Pipeline:** 1.0.0  
**Stato Test Suite:** 35/35 Test Superati (100% Pass Rate)

---

## INTRODUZIONE E OBIETTIVI DEL REFACTORING

Il presente documento formalizza i 10 interventi di ingegnerizzazione architetturale, irrobustimento metodologico e data governance implementati sulla pipeline end-to-end del progetto VitalDB.

L'architettura segue il paradigma **Medallion Lakehouse** (Bronze $\to$ Silver $\to$ Gold), integrando:
1. **Bronze Layer:** Landing grezzo ad alta fedeltà di tracciati biometrici Solar8000, parametri clinici e referti di laboratorio.
2. **Silver Layer:** Bonifica temporale rigorosa (secondi reali a 1 Hz), interpolazione dei soli buchi fisiologici brevi ($\le 5\text{s}$), staleness tracking NIBP (LOCF con scadenza a 300 s), tracciamento delle feature imputate e partizionamento fisico per reparto chirurgico (`department=<REPARTO>`).
3. **Gold Layer:** Storage analitico columnar su MongoDB 8.0 in Time Series Collections con bucketing a 1 secondo, compensazione a 2 fasi con stato di caricamento logico (`loading` $\to$ `committed`), validazione applicativa preventiva e catalogo metadata centralizzato.
4. **Detection Layer:** Algoritmo multilivello combinato (Shock Index, Ipotensione Severa, Isolation Forest spaziale, LSTM Autoencoder ricorrente PyTorch), consapevole della qualità dei dati e protetto da cancellazioni distruttive.
5. **Governance & Analytics:** Metriche di benchmark reali misurate su disco e su indici, calcolo accurato dei valori nulli e conformità tra catalogo e codice.

---

## MATRICE RIASSUNTIVA DEI 10 PUNTI

| # | Ambito Architetturale | Intervento Principale | File Coinvolti | Beneficio Principale |
|---|---|---|---|---|
| **1** | **Configurazione & Schemi** | `TRACK_SPECS` unica fonte di verità e `PIPELINE_VERSION` | `src/config.py`, `mongo/registry_schema.js` | Elimina divergenze sui range clinici; abilita data lineage |
| **2** | **Silver Layer & Cleansing** | `interpolate_short_gaps` ($\le 5\text{s}$), `*_imputed`, range centralizzati e DQ report per sensore | `src/silver/clean.py` | Preserva i secondi reali; non maschera interruzioni lunghe di segnale |
| **3** | **Gold Layer & Ingestion** | Caricamento idempotente a 2 fasi (`loading` $\to$ `committed`), `validate_records` e metadati arricchiti | `src/gold/load_mongo.py` | Idempotenza senza transazioni su Time Series; scarto dati corrotti |
| **4** | **Serving & API** | Filtro `status: "committed"` nelle interrogazioni del registry | `src/analysis/queries.py` | Esclude casi parziali da dashboard e query analitiche |
| **5** | **Detection & Persistenza** | Mascheramento outlier a NaN, imputazione isolata per paziente, persistenza insert-before-delete | `src/detection/detector.py` | Evita falsi allarmi da artefatti e garantisce tolleranza ai guasti |
| **6** | **Valutazione Modelli** | Singolo fit Isolation Forest, baseline dinamica da prevalenza reale e dichiarazione pseudo-ground truth | `src/analysis/evaluate_models.py` | Rigore scientifico: metriche coerenti e baseline non hardcoded |
| **7** | **Benchmark & Storage** | Separazione `storageSize` vs `totalIndexSize`, confronto Silver vs Gold e null rate reale con `$exists` | `src/analysis/benchmark_etl.py` | Metriche di compressione e qualità credibili e confrontabili |
| **8** | **Bronze Layer & Ingestion** | Manifest `download_manifest.json`, skip dei file presenti, gestione esplicita errori e lab data | `src/bronze/download.py` | Pipeline Bronze deterministica, tracciabile e resiliente a download parziali |
| **9** | **Isolamento & Test Suite** | Monkeypatch isolato per `/detect`, test unitari su download, ETL gap, validazione e idempotenza | `tests/test_api.py`, `tests/test_bronze.py`, `tests/test_detection.py`, `tests/test_etl.py`, `tests/test_gold.py` | Test suite non distruttiva sui dati clinici; copertura completa dei corner case |
| **10**| **Manutenzione & Reset** | Pulizia selettiva dei manifest storici in fase di reset dell'ambiente | `scripts/reset_pipeline.py` | Ripristino trasparente dell'ambiente di calcolo senza residui inconsistenti |

---

## ANALISI DETTAGLIATA DEI 10 PUNTI

---

### PUNTO 1: FONTE UNICA DEI RANGE CLINICI E PROVENANCE DELLA PIPELINE
* **Layer:** Trasversale (Configurazione, Governance & Catalog)
* **File Modificati:** `src/config.py`, `mongo/registry_schema.js`

#### Contesto e Problema Iniziale (As-Is)
In precedenza, i limiti fisiologici dei parametri vitali erano cablati in punti diversi del codice: in `src/silver/clean.py` per il calcolo degli outlier e nello script `mongo/registry_schema.js` per il catalogo `track_metadata`. Questa duplicazione aveva già provocato una divergenza critica: la pressione diastolica (`Solar8000/NIBP_DBP`) ammetteva un valore massimo di 180 mmHg nel cleaning ma di 200 mmHg nel JSON Schema di MongoDB. Inoltre, mancava un identificativo di versione globale per tracciare la provenance del dato.

#### Soluzione Implementata (To-Be)
1. Centralizzato in `src/config.py` il dizionario `TRACK_SPECS` per i 5 tracciati biometrici primari (HR, SpO₂, SBP, DBP, MBP), specificando per ciascuno: nome leggibile, unità di misura, valore minimo e valore massimo fisiologico.
2. Definita la costante `PIPELINE_VERSION = "1.0.0"`.
3. Riallineato `mongo/registry_schema.js` impostando il limite massimo di `NIBP_DBP` a 180 mmHg.
4. Aggiornata la funzione `seed_track_metadata` in `src/gold/load_mongo.py` per sincronizzare la collezione MongoDB `track_metadata` direttamente da `TRACK_SPECS`.

#### Impatto Architetturale
- **Single Source of Truth:** Impossibile generare contraddizioni tra i criteri di scarto del layer Silver e le specifiche dichiarate nel catalogo del Gold.
- **Data Lineage:** Ogni elaborazione e record caricato su MongoDB è ora tracciato con la versione esatta dell'algoritmo che lo ha generato.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Governance dei Dati: Single Source of Truth
- *Concetto Chiave:* Eliminata la duplicazione manuale dei range biometrici mediante `TRACK_SPECS`; allineato il tetto clinico DBP a 180 mmHg su tutto lo stack.

---

### PUNTO 2: SILVER CONSAPEVOLE DEL TEMPO REALE E REPORT DQ MULTI-SENSORE
* **Layer:** Silver (Data Cleansing & Partitioning)
* **File Modificati:** `src/silver/clean.py`, `tests/test_etl.py`

#### Contesto e Problema Iniziale (As-Is)
La funzione di cleaning eseguiva un `dropna(how='all')` all'inizio del processo. Poiché i tracciati sono campionati a 1 Hz, la rimozione preliminare di righe vuote rompeva la continuità dell'asse temporale: i filtri successivi contavano "righe" e non "secondi effettivi". Inoltre, `interpolate(method='linear', limit=5)` riempiva arbitrariamente i primi 5 secondi anche all'interno di buchi prolungati (es. 2 minuti di cavo scollegato), mascherando interruzioni strumentali critiche. Il report di qualità, infine, contava solo metriche globali senza distinguere il comportamento dei singoli sensori.

#### Soluzione Implementata (To-Be)
1. **Nessun `dropna` iniziale:** Il DataFrame grezzo mantiene la griglia temporale a 1 secondo durante tutte le fasi di imputazione e calcolo della staleness.
2. **Funzione `interpolate_short_gaps(series, max_gap=5)`:** Algoritmo vettorizzato che identifica la dimensione di ciascun blocco contiguo di `NaN`. Solo i buchi interni di durata $\le 5\,\text{s}$ vengono interpolati linearmente. I buchi $> 5\,\text{s}$ e i `NaN` periferici (leading/trailing) rimangono rigorosamente inalterati.
3. **Tracciamento Imputazione:** Create le colonne booleane `HR_imputed` e `SPO2_imputed` per marcare puntualmente i valori ricostruiti matematicamente rispetto a quelli nativamente misurati dai sensori.
4. **Scarto Finale:** La rimozione dei record totalmente privi di parametri vitali avviene solo come ultimo step.
5. **Sensor Quality Metrics:** Il report JSON per caso e per sensore calcola: campioni osservati, campioni imputati, campioni mancanti, outlier rilevati e percentuale di copertura temporale effettiva.

#### Impatto Architetturale
- **Integrità Clinica:** Si evita la fabbricazione artificiale di segnali vitali durante disconnessioni prolungate dei monitor di sala operatoria.
- **Auditing & Trasparenza:** A valle è sempre possibile distinguere un dato biometrico reale da uno interpolato.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Silver Layer: Interpolazione Consapevole del Tempo
- *Concetto Chiave:* Algoritmo `interpolate_short_gaps` ($\le 5\text{s}$) su griglia temporale intatta. Distinzione netta tra dato osservato (`observed`) e dato stimato (`imputed`).

---

### PUNTO 3: IDEMPOTENZA GOLD, TRANSIZIONE A DUE FASI E VALIDAZIONE APPLICATIVA
* **Layer:** Gold (MongoDB 8.0 Time Series & Metadata Ingestion)
* **File Modificati:** `src/gold/load_mongo.py`, `tests/test_gold.py`

#### Contesto e Problema Iniziale (As-Is)
MongoDB Time Series Collections non supportano le transazioni multi-documento ACID tradizionali (errore di sistema 263) e consentono operazioni di `delete_many` unicamente filtrando per `metaField` (`metadata.case_id`). Di conseguenza, un rieseguimento dell'ETL o un retry a metà operazione duplicava i record temporali o lasciava il database in uno stato inconsistente. Inoltre, non esisteva validazione preliminare prima dell'inserimento massivo.

#### Soluzione Implementata (To-Be)
1. **Compensazione a Due Fasi (Two-Phase Load):**
   - Transizione di stato nel metastore `registry`: `status: "loading"`.
   - Bonifica preventiva compensativa: `db['vital_signals'].delete_many({"metadata.case_id": case_id})`.
   - Validazione applicativa: invocazione di `validate_records()` su tipi di dato, consistenza dei timestamp `datetime` e range finiti.
   - Inserimento massivo in batch (`insert_many`).
   - Finalizzazione dello stato: `status: "committed"` con registrazione di `run_id`, `pipeline_version` e parametri di cleaning adottati.
2. **Arricchimento Documento BSON:** I record su `vital_signals` memorizzano nel sotto-documento `quality_flags` lo stato `nibp_age_s` e i flag booleani `*_imputed`.
3. **Idempotenza nei Retry:** `process_silver_to_gold` salta esclusivamente i casi che presentano `status == "committed"`. Eventuali casi rimasti in `loading` (a causa di crash precedenti) vengono automaticamente bonificati e ricaricati in modo pulito.

#### Impatto Architetturale
- **Affidabilità Enterprise:** Massima garanzia di consistenza ottenibile su collezioni MongoDB Time Series in assenza di transazioni distribuite.
- **Data Quality Gateway:** I record malformati vengono intercettati ed espulsi a livello applicativo prima di corrompere lo storage columnar di MongoDB.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Gold Layer: Ingestion Idempotente a Due Fasi
- *Concetto Chiave:* Protocollo di compensazione logica (`loading` $\to$ `delete` $\to$ `insert` $\to$ `committed`) per superare il vincolo no-ACID delle Time Series Collections di MongoDB.

---

### PUNTO 4: SERVING LAYER CON FILTRO SUI SOLI CASI COMMITTED
* **Layer:** Serving, Analysis & REST API
* **File Modificati:** `src/analysis/queries.py`

#### Contesto e Problema Iniziale (As-Is)
La funzione `list_loaded_cases()` restituiva tutti i record presenti nella collezione `registry`. Qualora un caso fosse a metà del caricamento (stato `loading`) o fosse fallito per un'interruzione di rete, compariva ugualmente nelle dashboard e nelle API di query, esponendo serie temporali tronche o inconsistenti.

#### Soluzione Implementata (To-Be)
1. Aggiunto il filtro esplicito `{"status": "committed"}` alla query MongoDB in `list_loaded_cases()`.
2. Garantito che le API FastAPI e i selettori interattivi dell'interfaccia web visualizzino unicamente dataset che abbiano superato con successo l'intero ciclo di ingestione e validazione.

#### Impatto Architetturale
- **Isolamento della Pubblicazione:** Applicazione del principio di separazione tra fase di caricamento (staging) e fase di rilascio analitico (commit).

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Serving Layer: Pubblicazione Selettiva
- *Concetto Chiave:* Le API e la dashboard interrogano solo record con `status: "committed"`, eliminando il rischio di dirty reads durante l'esecuzione dell'ETL.

---

### PUNTO 5: DETECTION RESILIENTE, ISOLAMENTO DEI CASI E PERSISTENZA SICURA
* **Layer:** Anomaly Detection & ML Modeling
* **File Modificati:** `src/detection/detector.py`, `tests/test_detection.py`

#### Contesto e Problema Iniziale (As-Is)
Nella versione originaria:
1. Gli outlier sensoriali (es. elettrodo staccato con HR = 300 bpm o 0 bpm) rimanevano nei dati numerici elaborati dallo Shock Index e dall'Isolation Forest, innescando falsi allarmi clinici.
2. L'imputazione preliminare di Isolation Forest eseguiva un `ffill().bfill()` globale su tutto il DataFrame concatenato, trasferendo i valori dell'ultimo record del paziente $N$ al primo record del paziente $N+1$ (data leakage cross-paziente).
3. `save_anomalies_to_mongo` cancellava le anomalie prima dell'inserimento: in caso di eccezione durante l'insert, il caso rimaneva permanentemente svuotato di qualsiasi anomalia storica.

#### Soluzione Implementata (To-Be)
1. **Mascheramento Outlier Fisiologici:** `load_from_gold` proietta `quality_flags` e imposta preventivamente a `np.nan` i parametri contrassegnati da flag outlier. L'artefatto di misura non viene più scambiato per emergenza clinica.
2. **Imputazione Raggruppata per Paziente:** In `detect_isolation_forest` e `AnomalyDetector`, l'imputazione `ffill().bfill()` opera tramite `groupby('case_id')`, preservando l'isolamento statistico tra pazienti differenti.
3. **Pattern Insert-Before-Delete:** In `save_anomalies_to_mongo`, i nuovi documenti vengono marcati con il timestamp dell'esecuzione (`detected_at = now`) e inseriti (`insert_many`). Solo ad operazione completata con successo, il database esegue `delete_many({"case_id": {"$in": analyzed_cases}, "detected_at": {"$ne": now}})`. Se il processo crasha durante la scrittura, i vecchi dati rimangono intatti. Se il paziente è tornato clinicamente stabile (0 anomalie), le vecchie anomalie stale vengono comunque rimosse.

#### Impatto Architetturale
- **Precisione Diagnostica:** Separazione formale tra rumore strumentale (DQ) e instabilità emodinamica reale (anomalia clinica).
- **Zero Data Loss:** Tolleranza ai guasti durante la sincronizzazione dei risultati di machine learning su MongoDB.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Anomaly Detection: Robustezza e Zero Data Loss
- *Concetto Chiave:* Mascheramento degli artefatti pre-ML; imputazione strictly per-paziente; persistenza transazionale sicura con inserimento precedente alla cancellazione dei vecchi allarmi.

---

### PUNTO 6: VALUTAZIONE SCIENTIFICA: MODELLO UNIFICATO E BASELINE DINAMICA
* **Layer:** Model Evaluation & Validation
* **File Modificati:** `src/analysis/evaluate_models.py`

#### Contesto e Problema Iniziale (As-Is)
Nel modulo di valutazione dei modelli ML:
1. Venivano addestrati due distinti modelli Isolation Forest indipendenti: uno per calcolare la matrice di confusione (Precision/Recall/F1) e un secondo modello diverso per calcolare la curva Precision-Recall e la PR-AUC, rendendo le metriche numericamente disallineate tra loro.
2. La baseline stampata a video riportava un valore hardcoded fisso del "4.9%", che non rifletteva la prevalenza reale dei casi caricati nel database.
3. Mancava una formalizzazione del limite metodologico dovuto alla circolarità della pseudo-ground truth (basata sulla disgiunzione logica delle regole cliniche).

#### Soluzione Implementata (To-Be)
1. **Single Model Fit:** Addestramento di una singola istanza di Isolation Forest per ciascun run, dalla quale si estraggono in modo rigorosamente coerente sia le predizioni binarie (`predict`) sia gli anomaly score continui (`decision_function`).
2. **Baseline Dinamica:** Stampa della vera baseline teorica calcolata in tempo reale dalla prevalenza effettiva del dataset (`base_rate = y_true.mean() * 100`).
3. **Dichiarazione Esplicita di Provenance:** Aggiunto nel file JSON dei risultati il campo `notes` che dichiara formalmente la natura e il perimetro della pseudo-ground truth.

#### Impatto Architetturale
- **Rigore Scientifico:** Piena riproducibilità sperimentale e coerenza tra le metriche di soglia (Precision/Recall) e le metriche di ranking (PR-AUC).

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Valutazione Modelli: Coerenza Metodologica
- *Concetto Chiave:* Unificazione del fit Isolation Forest (singolo modello sia per decision score che per classificazione); baseline calcolata dinamicamente sulla reale prevalenza dei campioni patologici.

---

### PUNTO 7: BENCHMARK ACCURATO: STORAGE BREAKDOWN E NULL RATE REALE
* **Layer:** Analytics, Governance & Performance Benchmarking
* **File Modificati:** `src/analysis/benchmark_etl.py`

#### Contesto e Problema Iniziale (As-Is)
Nel benchmark comparativo dell'ETL:
1. La metrica `null_pct_gold` era forzata a `0.0` fisso (valore fittizio non misurato).
2. La dimensione del layer Gold considerava `totalSize` aggregato, sommando indistintamente lo spazio effettivo dei dati su disco con la dimensione degli indici B-Tree.
3. Mancava il confronto esplicito di riduzione dimensionale tra il layer Silver (Parquet compresso) e il layer Gold (MongoDB Time Series columnar).

#### Soluzione Implementata (To-Be)
1. **Misurazione Null con `$exists`:** Il null rate del Gold viene calcolato interrogando puntualmente MongoDB con conteggi `$exists` per ciascuna metrica vitale rispetto al volume atteso di record.
2. **Separazione Storage vs Indici:** Il benchmark estrae da `db.command("collStats", "vital_signals")` separatamente `storageSize` (peso compresso delle serie temporali) e `totalIndexSize` (peso degli indici).
3. **Confronto a Due Livelli:** Calcolate sia la riduzione Bronze $\to$ Gold, sia la riduzione Silver $\to$ Gold.

#### Impatto Architetturale
- **Trasparenza Prestazionale:** I dati mostrati in relazione e a video riflettono la reale efficienza dell'architettura columnar e del bucketing di MongoDB 8.0.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Benchmark ETL: Analisi di Compressione Rigorosa
- *Concetto Chiave:* Separazione trasparente tra volume dati compresso (`storageSize`) e indici; calcolo non fittizio della qualità dei dati nel Gold tramite operatori `$exists`.

---

### PUNTO 8: BRONZE ROBUSTO, MANIFEST DI TRACCIABILITÀ E GESTIONE LAB DATA
* **Layer:** Bronze (Raw Landing & Data Extraction)
* **File Modificati:** `src/bronze/download.py`, `tests/test_bronze.py`

#### Contesto e Problema Iniziale (As-Is)
Lo script di download del layer Bronze presentava tre criticità:
1. In caso di fallimento nel download del file fondamentale `clinical_data.parquet`, lo script proseguiva silenziosamente senza sollevare errori, facendo confluire tutti i pazienti sotto il reparto di ripiego `UNKNOWN`.
2. Se il download di un tracciato veniva interrotto a metà, la pipeline stampava comunque un messaggio fuorviante di "COMPLETATA CON SUCCESSO".
3. Mancava la gestione dei dati di laboratorio (`download_lab_data`) e non esisteva un registro per saltare i casi già scaricati, costringendo a riscaricare tutti i dati ad ogni esecuzione.

#### Soluzione Implementata (To-Be)
1. **Download Manifest:** Generazione di `download_manifest.json` che traccia data, versione e stato di ciascun caso scaricato (`downloaded`, `failed`).
2. **Skipping Intelligente:** I casi già presenti sul filesystem e validati nel manifest vengono saltati automaticamente.
3. **Fail-Fast Rigoroso:** Se il download dei dati clinici fallisce, lo script interrompe l'esecuzione sollevando un'eccezione esplicita ed esce con `sys.exit(1)`.
4. **Modulo Lab Data:** Implementata la funzione `download_lab_data()` per scaricare e filtrare i referti ematochimici e di laboratorio sui soli identificativi dei pazienti estratti.

#### Impatto Architetturale
- **Efficienza di Rete:** Riduzione dei tempi di download ed eliminazione di chiamate ridondanti alle API di VitalDB.
- **Determinismo:** Certezza dello stato del Bronze layer prima di innescare le elaborazioni downstream nel Silver.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Bronze Layer: Ingestion Deterministica con Manifest
- *Concetto Chiave:* Introduzione di `download_manifest.json`, politica fail-fast sui dati clinici essenziali e download modulare dei dati di laboratorio.

---

### PUNTO 9: TEST SUITE ISOLATA, UNITARIA E NON DISTRUTTIVA
* **Layer:** Testing, CI/CD & Verification
* **File Modificati:** `tests/test_api.py`, `tests/test_bronze.py`, `tests/test_detection.py`, `tests/test_etl.py`, `tests/test_gold.py`

#### Contesto e Problema Iniziale (As-Is)
Il test di integrazione dell'endpoint `/detect` eseguiva l'algoritmo sul Caso #1 e scriveva i risultati direttamente su MongoDB, sovrascrivendo le anomalie dimostrative utilizzate per le schermate della presentazione. Inoltre, mancavano test unitari specifici per le funzionalità più critiche introdotte (interpolazione selettiva, compensazione a 2 fasi, resilienza download).

#### Soluzione Implementata (To-Be)
1. **Monkeypatching su `/detect`:** Nel test di FastAPI, la funzione `save_anomalies_to_mongo` viene intercettata con un no-op, proteggendo il database da sovrascritture durante la suite automatica di test.
2. **Nuove Suite di Test Dedicate:**
   - `test_bronze.py`: verifica dello skip dei file già scaricati, del blocco in caso di dati clinici mancanti e del fallback sui dati di laboratorio.
   - `test_etl.py`: verifica di `interpolate_short_gaps` su gap corti ($\le 5\text{s}$), gap lunghi ($> 5\text{s}$) e valori periferici; verifica delle colonne `*_imputed` e dei range `TRACK_SPECS`.
   - `test_detection.py`: verifica della sequenza insert-before-delete, dell'eliminazione delle anomalie stale con `detected_at != now` e del mascheramento degli outlier in `load_from_gold`.
   - `test_gold.py`: test su `validate_records` (scarto record corrotti o con timestamp mancanti) e sulla transizione idempotente `loading` $\to$ `committed`.

#### Impatto Architetturale
- **Safety First:** I test possono essere eseguiti in qualsiasi momento in locale o in CI/CD senza sporcare o cancellare i dati operativi.
- **Copertura Completa:** Test suite passata da 25 a 35 test unitari (100% superati).

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* Affidabilità del Codice: Test Suite Isolata
- *Concetto Chiave:* Suite automatizzata con 35 unit test; isolamento completo tramite monkeypatch per impedire alterazioni dei dati analitici durante l'esecuzione dei test.

---

### PUNTO 10: MANUTENZIONE, RESET COORDINATO E PULIZIA ARTEFATTI
* **Layer:** Operations, DevOps & Environment Management
* **File Modificati:** `scripts/reset_pipeline.py`

#### Contesto e Problema Iniziale (As-Is)
Lo script di reset dell'ambiente ripuliva le collezioni MongoDB e i file Parquet nei layer Silver e Gold, ma lasciava intatti i file di stato ausiliari nel Bronze (come `download_manifest.json`), generando disallineamenti quando si tentava di eseguire una ripartenza da zero.

#### Soluzione Implementata (To-Be)
1. Integrata in `scripts/reset_pipeline.py` la cancellazione esplicita del file `download_manifest.json` e della cartella di storico `quality_history`.
2. Allineata la sequenza di reset affinché ripristini l'ambiente in uno stato perfettamente vergine e riproducibile.

#### Impatto Architetturale
- **Manutenibilità:** Capacità di re-inizializzare la pipeline senza residui di cache o metadati disallineati.

#### Punti Chiave per Relazione e Slide PPT
- *Slide Title:* DevOps & Manutenibilità: Reset Trasparente
- *Concetto Chiave:* Automazione del ripristino dell'infrastruttura con pulizia coordinata di metastore, manifest e serie temporali.

---

## SCHEMA ARCHITETTURALE DI SINTESI (FLUSSO END-TO-END)

```
[ VitalDB Cloud API ]
         │
         ▼ (Punto 8: Fail-fast, Download Manifest, Lab Data)
┌────────────────────────────────────────────────────────┐
│                      BRONZE LAYER                      │
│  - case_<ID>.parquet (Raw landing 1 Hz)                │
│  - clinical_data.parquet (Metadati clinici)            │
│  - download_manifest.json (Tracciabilità download)     │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Punto 1: TRACK_SPECS unici)
                           ▼ (Punto 2: Griglia continua, interpolate_short_gaps <=5s, *_imputed)
┌────────────────────────────────────────────────────────┐
│                      SILVER LAYER                      │
│  - Partizionamento fisico: department=<REPARTO>/       │
│  - LOCF NIBP con staleness age (<= 300s)               │
│  - Report DQ per caso e per sensore (sensor_metrics)   │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼ (Punto 3: Two-Phase Load, validate_records, enrichment)
┌────────────────────────────────────────────────────────┐
│                   GOLD LAYER (MongoDB 8.0)             │
│  - 'vital_signals' (Time Series: 1s bucketing)         │
│  - 'registry' (Metastore con status: "committed")      │
│  - 'track_metadata' (Catalogo sincronizzato da SPECS)  │
└────────────┬─────────────────────────────┬─────────────┘
             │                             │
             │ (Punto 4: solo committed)   │ (Punto 5: Outlier masking pre-ML)
             ▼                             ▼
┌───────────────────────────┐ ┌──────────────────────────┐
│       SERVING & API       │ │     DETECTION LAYER      │
│ - FastAPI REST Endpoints  │ │ - Shock Index & Ipotens. │
│ - Dashboard Interattiva   │ │ - Isolation Forest (IF)  │
│ - Benchmark (Punto 7)     │ │ - LSTM Autoencoder (PyT) │
│ - Evaluator (Punto 6)     │ │ - Insert-before-delete   │
└───────────────────────────┘ └──────────────────────────┘
```

---

## GUIDA RAPIDA PER PRESENTAZIONE PPT (SUGGERIMENTO SLIDE)

1. **Slide 1: Visione d'Insieme & Medallion Architecture**
   - Presentare i tre strati (Bronze, Silver, Gold) e gli obiettivi di qualità del dato clinico.
2. **Slide 2: Data Quality & Silver Layer (Punti 1 e 2)**
   - Focus su `TRACK_SPECS` (unica fonte di verità) e sulla gestione temporale a secondi reali (`interpolate_short_gaps` vs interpolazione cieca).
3. **Slide 3: MongoDB Time Series & Compensazione a Due Fasi (Punti 3 e 4)**
   - Spiegare il vincolo no-ACID delle Time Series Collections e mostrare la macchina a stati: `loading` $\to$ compensazione $\to$ validazione $\to$ `committed`.
4. **Slide 4: Anomaly Detection Consapevole e Resiliente (Punto 5)**
   - Illustrare il mascheramento del rumore sensoriale a `NaN` per non confondere artefatti e patologie; mostrare la persistenza sicura (insert prima di delete).
5. **Slide 5: Rigore Scientifico e Benchmark (Punti 6 e 7)**
   - Mostrare l'unificazione del modello Isolation Forest e il confronto reale di compressione (Storage dati vs Indici).
6. **Slide 6: Robustezza del Software & Testing (Punti 8, 9 e 10)**
   - Evidenziare la suite di 35 unit test e i meccanismi di protezione dei dati operativi.
