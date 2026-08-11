---
name: anomaly-detection-vitaldb
description: Guida allo sviluppo del progetto universitario di rilevamento anomalie su dati biometrici (VitalDB) attraverso una pipeline a layer Bronze/Silver/Gold, caricamento su MongoDB Time Series Collections, gestione artigianale dei metadata in ottica data-lakehouse governance, e anomaly detection finale. Usare questa skill ogni volta che si lavora su qualsiasi parte del progetto: download/esplorazione di VitalDB, scripting della pipeline, progettazione dello schema Mongo, gestione dei metadata/registry, o costruzione/valutazione del modello di anomaly detection. Attivare anche se l'utente fa riferimento solo a "il progetto", "la tesi", "la pipeline", "VitalDB", "Bronze/Silver/Gold", senza nominare esplicitamente tutti i dettagli.
---

# Progetto: Anomaly Detection su dati biometrici (VitalDB)

## Contesto del progetto

Progetto universitario (tesi/elaborato) di rilevamento anomalie su dati sensoristici time-series, concordato con la docente relatrice dopo un confronto via email in cui sono stati chiariti scope e vincoli. Il progetto è deliberatamente centrato su **data engineering + anomaly detection**, non su signal processing biomedico: per questo si è scelto di partire da parametri biometrici già estratti (HR, HRV, pressione, saturazione) invece che da segnali grezzi (es. PPG), che avrebbero richiesto una fase di stima non centrale rispetto agli obiettivi.

## Dataset: VitalDB

- Dataset scelto per il progetto tra le due opzioni proposte dalla docente (VitalDB e MIMIC-IV). Scelto per: struttura più semplice e diretta, accesso senza credentialing (a differenza di MIMIC-IV che richiede training PhysioNet), formato già pensato per il ML, contenuto equivalente a MIMIC-IV ai fini del progetto (misurazioni ripetute nel tempo di parametri biometrici per caso/paziente).
- Contiene ~6.388 casi chirurgici (monitoraggio intraoperatorio), con tracce numeriche (risoluzione 1-7 secondi) e waveform (62,5-500 Hz), oltre 196 parametri di monitoraggio intraoperatorio, dati clinici perioperatori e di laboratorio.
- Accesso tramite libreria Python ufficiale `vitaldb` (`pip install vitaldb`):
  - `vitaldb.find_cases("traccia1,traccia2")` — trova i casi che contengono le tracce di interesse (es. `Solar8000/HR`, `Solar8000/PLETH_SPO2`, `SNUADC/ECG_II`).
  - `vitaldb.load_case(caseid, "tracce", interval=1.0)` — carica i dati numerici di un caso a un intervallo di campionamento scelto.
  - `vitaldb.load_clinical_data()` / `vitaldb.load_lab_data()` — dati clinici perioperatori e di laboratorio, utili sia come contesto sia per popolare i metadata di governance.
  - `VitalFile` — classe per leggere file `.vital` locali e listare/estrarre tracce (`get_track_names()`, `to_numpy()`, `to_pandas()`).
- Per il progetto vanno privilegiati i parametri biometrici numerici già estratti (HR, SpO2, pressione, ecc.), coerentemente con la scelta comunicata alla docente, non i segnali waveform grezzi.

## Architettura della pipeline

### Layer Bronze (dati grezzi)
- Dati così come scaricati da VitalDB tramite `find_cases`/`load_case`, salvati in locale (es. CSV/Parquet) organizzati per caso/parametro, senza trasformazioni.
- Include anche i dati clinici/di laboratorio grezzi da `load_clinical_data()`/`load_lab_data()`.

### Layer Silver (dati puliti e partizionati)
- Pulizia (gestione missing values, outlier evidenti da errore di misurazione, normalizzazione dei timestamp), partizionamento (es. per caso, per parametro, per finestra temporale).
- Output ancora in formato file (es. Parquet partizionato), pronto per il caricamento nel layer Gold.

### Layer Gold (MongoDB Time Series Collections)
- Caricamento dei dati Silver in MongoDB, sfruttando le **Time Series Collections** (funzionalità nativa di MongoDB per dati time-series, non un datastore separato — chiarimento esplicito ricevuto dalla docente).
- Ogni misurazione è un documento con timestamp, valore, e metadati associati (vedi sezione metadata sotto).

## Gestione artigianale dei metadata (data governance in ottica lakehouse)

Punto chiarito esplicitamente con la docente: il riferimento ai metadata è legato al paradigma **data lakehouse** (governance dei dati + atomicità delle scritture), non alle sole proprietà interne delle time series collection. MongoDB non offre nativamente un metastore transazionale come Delta Lake/Iceberg/Hudi: l'obiettivo NON è costruire un vero stack lakehouse (niente Spark/Trino/storage a oggetti separato), ma **emulare in modo "artigianale" le proprietà chiave usando gli strumenti nativi di MongoDB**:

1. **Collection registry/catalogo**: traccia schema, versioning e provenance di ogni sensore/serie — è l'equivalente artigianale del metastore lakehouse.
2. **`metaField` delle time series collection**: porta i metadati strutturati (es. id paziente/caso, tipo di sensore, unità di misura) accanto ai dati, a supporto del bucketing e di query temporali più efficienti — è anche il cuore dell'approfondimento sulla progettazione dei metadata per la qualità delle query.
3. **JSON Schema validation nativa di MongoDB**: forma di schema enforcement lato database.
4. **Transazioni multi-documento**: usate per avvicinarsi all'atomicità tra scritture correlate (es. passaggio Silver→Gold su più collection), con la consapevolezza esplicita — da riportare anche nella discussione finale del progetto — che non equivalgono alle garanzie di un vero transaction log lakehouse.

Nella stesura/discussione, questo punto va sempre presentato onestamente come soluzione semplificata/artigianale dentro i limiti di MongoDB, con un confronto critico rispetto a un'implementazione lakehouse nativa: è il tipo di riflessione che la docente si aspetta.

## Anomaly Detection

- Applicato sui dati già strutturati nel layer Gold (parametri biometrici: HR, HRV, pressione, saturazione).
- Obiettivo: etichettare ogni punto come normale o anomalo.
- Le soglie/criteri di anomalia dovrebbero avere un razionale clinico minimo (es. range fisiologici per HR/SpO2), essendo più difendibili in sede di discussione rispetto ad anomalie su ampiezza di segnale grezzo.
- Non è stato ancora scelto un modello specifico: valutare in base ai dati disponibili (es. metodi statistici, isolation forest, autoencoder) quando si arriva a questa fase.

## Come usare questa skill

Quando l'utente chiede aiuto su una qualunque parte del progetto (script di download/pulizia dati, design dello schema Mongo, query time series, implementazione del registry/metadata, scelta/implementazione del modello di anomaly detection, o stesura di parti della tesi/report), fare sempre riferimento a questo contesto per:
- mantenere coerenza con le decisioni già prese (dataset VitalDB, dati biometrici strutturati e non segnali grezzi, niente stack lakehouse "vero", struttura a 4 punti concordata con la docente);
- evitare di reintrodurre scope non concordato (es. stima BP da PPG, motori lakehouse esterni a MongoDB);
- suggerire soluzioni coerenti con gli strumenti nativi di MongoDB per la parte di governance/metadata.
