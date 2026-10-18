# SINTESI COMPLETA DELLE MODIFICHE ARCHITETTURALI E DI DATA GOVERNANCE
**Progetto:** VitalDB Multimodal Real-Time Anomaly Detection & Lakehouse Architecture  
**Documento per:** Allineamento Relazione Tecnica e Presentazione Slide (PPT)  
**Versione Pipeline:** 1.1.0  
**Stato Test Suite:** 37/37 Test Superati (100% Pass Rate)

---

## INTRODUZIONE E OBIETTIVI DEL REFACTORING

Il presente documento formalizza gli interventi di ingegnerizzazione architetturale, irrobustimento metodologico e data governance implementati sulla pipeline end-to-end del progetto VitalDB (suddivisi nel **Blocco Primario: Punti 1–10** e nel **Secondo Ciclo di Raffinamento: Punti 11–16**).

L'architettura segue il paradigma **Medallion Lakehouse** (Bronze $\to$ Silver $\to$ Gold), integrando:
1. **Bronze Layer:** Landing grezzo ad alta fedeltà di tracciati biometrici Solar8000 (500 casi standard configurabili), parametri clinici e referti di laboratorio, con verifica di compatibilità dello schema prima dello skip dei file esistenti.
2. **Silver Layer:** Bonifica temporale rigorosa (secondi reali a 1 Hz), identificazione degli outlier fisiologici *prima* dell'imputazione (per impedire la propagazione degli artefatti), interpolazione dei soli buchi fisiologici brevi ($\le 5\text{s}$), staleness tracking NIBP (LOCF con scadenza a 300 s), tracciamento esplicito per ogni singolo canale (`HR_imputed`, `SPO2_imputed`, `SBP_imputed`, `DBP_imputed`, `MBP_imputed`), denominatori omogenei nei conteggi DQ e partizionamento fisico per reparto chirurgico (`department=<REPARTO>`).
3. **Gold Layer:** Storage analitico columnar su MongoDB 8.0 in Time Series Collections con bucketing a 1 secondo, compensazione a 2 fasi con stato di caricamento logico (`loading` $\to$ `committed`), recupero automatico di eventuali caricamenti interrotti (`recover_incomplete_loads`), validazione applicativa preventiva e catalogo metadata centralizzato.
4. **Detection Layer:** Algoritmo multilivello combinato (Shock Index, Ipotensione Severa, Isolation Forest spaziale, LSTM Autoencoder ricorrente PyTorch), consapevole sia della qualità dei dati (mascheramento outlier a `NaN`) sia della freschezza emodinamica (`nibp_age_s <= 120s`), e protetto da cancellazioni distruttive.
5. **Governance, Provenance & Analytics:** Collegamento end-to-end tramite `run_id` e `pipeline_version` condivisi tra tutti gli artefatti JSON e MongoDB, metriche di benchmark misurate sullo stesso perimetro di casi `committed` separando `storageSize` da `totalIndexSize`, e dashboard web allineata alle metriche PR-AUC e alla definizione di Pseudo-Ground Truth.

---

## MATRICE RIASSUNTIVA DEGLI INTERVENTI (PUNTI 1–16)

| # | Ambito Architetturale | Intervento Principale | File Coinvolti | Beneficio Principale |
|---|---|---|---|---|
| **1** | **Configurazione & Schemi** | `TRACK_SPECS` unica fonte di verità, `PIPELINE_VERSION = "1.1.0"` e `get_or_create_run_id()` | `src/config.py`, `mongo/registry_schema.js` | Elimina divergenze sui range clinici; abilita data lineage end-to-end |
| **2** | **Silver Layer & Cleansing** | `interpolate_short_gaps` ($\le 5\text{s}$), `*_imputed`, range centralizzati e DQ report per sensore | `src/silver/clean.py` | Preserva i secondi reali; non maschera interruzioni lunghe di segnale |
| **3** | **Gold Layer & Ingestion** | Caricamento idempotente a 2 fasi (`loading` $\to$ `committed`), `validate_records` e metadati arricchiti | `src/gold/load_mongo.py` | Idempotenza senza transazioni su Time Series; scarto dati corrotti |
| **4** | **Serving & API** | Filtro rigoroso `status: "committed"` nelle interrogazioni del registry | `src/analysis/queries.py` | Esclude casi parziali o incompleti da dashboard e query analitiche |
| **5** | **Detection & Persistenza** | Mascheramento outlier a NaN, imputazione isolata per paziente, persistenza insert-before-delete | `src/detection/detector.py` | Evita falsi allarmi da artefatti e garantisce tolleranza ai guasti |
| **6** | **Valutazione Modelli** | Singolo fit Isolation Forest, baseline dinamica da prevalenza reale e dichiarazione pseudo-ground truth | `src/analysis/evaluate_models.py` | Rigore scientifico: metriche coerenti e baseline non hardcoded |
| **7** | **Benchmark & Storage** | Separazione `storageSize` vs `totalIndexSize`, confronto Silver vs Gold e null rate reale con `$exists` | `src/analysis/benchmark_etl.py` | Metriche di compressione e qualità credibili e confrontabili |
| **8** | **Bronze Layer & Ingestion** | Manifest `download_manifest.json`, verifica schema/frequenza sui file esistenti, fail-fast e lab data | `src/bronze/download.py` | Pipeline Bronze deterministica, tracciabile e resiliente a download parziali |
| **9** | **Isolamento & Test Suite** | Monkeypatch isolato per `/detect`, 37 test unitari su download, ETL gap, NIBP freshness e idempotenza | `tests/test_*.py` | Test suite non distruttiva sui dati clinici; copertura completa dei corner case |
| **10**| **Manutenzione & Reset** | Pulizia selettiva dei manifest storici e di `.current_run_id` in fase di reset dell'ambiente | `scripts/reset_pipeline.py` | Ripristino trasparente dell'ambiente di calcolo senza residui inconsistenti |
| **11**| **Allineamento Perimetro Run** | Riallineamento automatico del perimetro dei casi tra Bronze, Silver, Gold, Benchmark ed Evaluator | `src/config.py`, `src/silver/clean.py`, `src/gold/load_mongo.py` | Impedisce che report diversi descrivano esecuzioni con numero di casi differente |
| **12**| **Omogeneità Conteggi DQ Silver**| Calcolo outlier *prima* del forward-fill, flag `SBP/DBP/MBP_imputed` e denominatore unico `rows_cleaned` | `src/silver/clean.py`, `tests/test_etl.py` | Identità esatta $\text{observed} + \text{imputed} + \text{missing} = \text{rows\_cleaned}$; zero propagazione di outlier |
| **13**| **Freschezza NIBP in Detection** | Uso di `nibp_age_s <= 120s` nelle regole cliniche (Shock Index e Ipotensione Severa) | `src/detection/detector.py`, `tests/test_detection.py` | Impedisce che una misura pressoria obsoleta trascinata per LOCF generi allarmi continui |
| **14**| **Commit Enforcement Globale** | Filtro `status: "committed"` applicato a tutti i lettori Gold (`detector`, `evaluator`, `benchmark`) e recovery automatico | `src/detection/detector.py`, `src/analysis/evaluate_models.py`, `src/analysis/benchmark_etl.py`, `src/gold/load_mongo.py` | Nessun modulo analitico legge casi rimasti in `loading` o `failed` |
| **15**| **Provenance Cross-Layer** | Condivisione automatica di `run_id` e `pipeline_version` in tutti i 4 report JSON e nel `registry` MongoDB | `src/config.py`, `download.py`, `clean.py`, `load_mongo.py`, `evaluate_models.py`, `benchmark_etl.py` | Tracciabilità formale: ogni report certifica l'esatto run e la versione da cui proviene |
| **16**| **Allineamento Dashboard UI** | Intestazione `PR-AUC (Average Precision)`, titoli dinamici da JSON, dicitura Pseudo-Ground Truth e dettaglio Storage vs Indici | `dashboard/partials/lakehouse-view.html`, `dashboard/js/lakehouse.js` | Coerenza totale tra ciò che calcola il backend e ciò che mostra l'interfaccia grafica |

---

## PARTE I — ANALISI DETTAGLIATA DEI PRIMI 10 PUNTI FONDAMENTALI

### PUNTO 1: FONTE UNICA DEI RANGE CLINICI E PROVENANCE DELLA PIPELINE
* **Layer:** Trasversale (Configurazione, Governance & Catalog)
* **File Modificati:** `src/config.py`, `mongo/registry_schema.js`

#### Contesto e Problema Iniziale (As-Is)
I limiti fisiologici dei parametri vitali erano duplicati tra `src/silver/clean.py` e `mongo/registry_schema.js`, con una divergenza sulla pressione diastolica (`NIBP_DBP` max 180 mmHg nel cleaning contro 200 mmHg nel catalogo MongoDB). Mancava inoltre un meccanismo di versionamento e di identificazione della corsa (`run_id`).

#### Soluzione Implementata (To-Be)
1. Centralizzato in `src/config.py` il dizionario `TRACK_SPECS` per i 5 tracciati biometrici primari (HR, SpO₂, SBP, DBP, MBP).
2. Definita la costante `PIPELINE_VERSION = "1.1.0"` e la funzione `get_or_create_run_id()` che persiste in `data/.current_run_id` l'identificativo univoco della corsa corrente.
3. Riallineato `mongo/registry_schema.js` e sincronizzata la collezione `track_metadata` in `src/gold/load_mongo.py` direttamente da `TRACK_SPECS`.

---

### PUNTO 2: SILVER CONSAPEVOLE DEL TEMPO REALE E REPORT DQ MULTI-SENSORE
* **Layer:** Silver (Data Cleansing & Partitioning)
* **File Modificati:** `src/silver/clean.py`, `tests/test_etl.py`

#### Contesto e Problema Iniziale (As-Is)
La funzione di cleaning eseguiva un `dropna(how='all')` iniziale che alterava la continuità dell'asse temporale a 1 Hz, e usava `interpolate(method='linear', limit=5)` che riempiva i primi 5 campioni anche dentro buchi lunghi minuti.

#### Soluzione Implementata (To-Be)
1. **Griglia temporale intatta:** Nessun `dropna` iniziale; lo scarto delle righe completamente vuote avviene solo a fine elaborazione.
2. **Funzione `interpolate_short_gaps(series, max_gap=5)`:** Interpola linearmente esclusivamente i buchi interni di durata $\le 5\,\text{s}$, lasciando a `NaN` le interruzioni strumentali prolungate ($> 5\,\text{s}$) e i `NaN` periferici.
3. **Report Multi-Sensore:** Generazione del dizionario `sensor_metrics` per ogni caso e per ogni traccia.

---

### PUNTO 3: IDEMPOTENZA GOLD, TRANSIZIONE A DUE FASI E VALIDAZIONE APPLICATIVA
* **Layer:** Gold (MongoDB 8.0 Time Series & Metadata Ingestion)
* **File Modificati:** `src/gold/load_mongo.py`, `tests/test_gold.py`

#### Contesto e Problema Iniziale (As-Is)
Le Time Series Collections di MongoDB non supportano transazioni ACID multi-documento (errore 263). Un retry a metà caricamento causava duplicazione dei punti temporali.

#### Soluzione Implementata (To-Be)
1. **Protocollo Two-Phase Load:** Scrittura di `status: "loading"` nel `registry` $\to$ pulizia preventiva con `delete_many({"metadata.case_id": case_id})` $\to$ validazione applicativa `validate_records()` $\to$ `insert_many` $\to$ aggiornamento a `status: "committed"`.
2. **Gestione Errori e Cleanup:** In caso di eccezione durante l'insert, il caso viene marcato come `status: "failed"`, i punti parziali vengono rimossi e la funzione `recover_incomplete_loads()` bonifica eventuali caricamenti interrotti al run successivo.

---

### PUNTO 4: SERVING LAYER CON FILTRO SUI SOLI CASI COMMITTED
* **Layer:** Serving, Analysis & REST API
* **File Modificati:** `src/analysis/queries.py`

#### Soluzione Implementata (To-Be)
La funzione `list_loaded_cases()` applica il filtro rigoroso `{"status": "committed"}`, garantendo che API e dashboard espongano esclusivamente casi il cui caricamento si è concluso integralmente.

---

### PUNTO 5: DETECTION RESILIENTE, ISOLAMENTO DEI CASI E PERSISTENZA SICURA
* **Layer:** Anomaly Detection & ML Modeling
* **File Modificati:** `src/detection/detector.py`, `tests/test_detection.py`

#### Soluzione Implementata (To-Be)
1. **Mascheramento Outlier Fisiologici:** `load_from_gold` proietta `quality_flags` e maschera a `np.nan` i valori contrassegnati come outlier prima delle regole cliniche e dei modelli ML.
2. **Imputazione Raggruppata per Paziente:** `detect_isolation_forest` e `AnomalyDetector` eseguono `ffill().bfill()` raggruppando per `case_id`, eliminando ogni data leakage tra pazienti consecutivi.
3. **Pattern Insert-Before-Delete:** `save_anomalies_to_mongo` inserisce prima i nuovi documenti con `detected_at = now` e solo dopo rimuove quelli obsoleti con `delete_many({"case_id": {"$in": analyzed_cases}, "detected_at": {"$ne": now}})`.

---

### PUNTO 6: VALUTAZIONE SCIENTIFICA: MODELLO UNIFICATO E BASELINE DINAMICA
* **Layer:** Model Evaluation & Validation
* **File Modificati:** `src/analysis/evaluate_models.py`

#### Soluzione Implementata (To-Be)
Unificato l'addestramento di Isolation Forest in un singolo fit da cui si ricavano sia le predizioni binarie sia gli score continui per la PR-AUC; calcolata dinamicamente la baseline dalla prevalenza reale (`base_rate`); aggiunta la nota metodologica `notes` nel JSON.

---

### PUNTO 7: BENCHMARK ACCURATO: STORAGE BREAKDOWN E NULL RATE REALE
* **Layer:** Analytics, Governance & Performance Benchmarking
* **File Modificati:** `src/analysis/benchmark_etl.py`

#### Soluzione Implementata (To-Be)
Separato lo spazio puro compresso della Time Series (`storageSize`) dal peso degli indici B-Tree (`totalIndexSize`); aggiunto il confronto `reduction_silver_vs_gold_pct`; calcolato `null_pct_gold` tramite query reali `$exists` su MongoDB anziché usare `0.0` fisso.

---

### PUNTO 8: BRONZE ROBUSTO, MANIFEST DI TRACCIABILITÀ E GESTIONE LAB DATA
* **Layer:** Bronze (Raw Landing & Data Extraction)
* **File Modificati:** `src/bronze/download.py`, `tests/test_bronze.py`

#### Soluzione Implementata (To-Be)
Introdotto `download_manifest.json`, blocco fail-fast con `sys.exit(1)` se i dati clinici falliscono, funzione `download_lab_data()` filtrata sui casi estratti, e verifica di compatibilità (presenza di tutte le tracce e corrispondenza del `SAMPLING_INTERVAL`) prima di saltare i file Parquet già presenti su disco.

---

### PUNTO 9: TEST SUITE ISOLATA, UNITARIA E NON DISTRUTTIVA
* **Layer:** Testing, CI/CD & Verification
* **File Modificati:** `tests/test_api.py`, `tests/test_bronze.py`, `tests/test_detection.py`, `tests/test_etl.py`, `tests/test_gold.py`

#### Soluzione Implementata (To-Be)
Isolato il test dell'endpoint `/cases/1/detect` tramite monkeypatch di `save_anomalies_to_mongo` ed estesa la test suite a **37 unit test** (100% pass rate).

---

### PUNTO 10: MANUTENZIONE, RESET COORDINATO E PULIZIA ARTEFATTI
* **Layer:** Operations, DevOps & Environment Management
* **File Modificati:** `scripts/reset_pipeline.py`

#### Soluzione Implementata (To-Be)
Aggiornato lo script di reset per rimuovere coordinatamente le collezioni MongoDB, le directory Bronze/Silver, tutti i 4 file JSON di report/manifest e il file `.current_run_id`.

---

## PARTE II — SECONDO CICLO DI RAFFINAMENTO (PUNTI 11–16)

Questi ulteriori 6 interventi risolvono le sottigliezze metodologiche emerse dall'ispezione incrociata dei report generati e della dashboard web.

---

### PUNTO 11: ALLINEAMENTO DEL PERIMETRO DEI CASI TRA TUTTI I LAYER
* **File Modificati:** `src/config.py`, `src/silver/clean.py`, `src/gold/load_mongo.py`, `src/analysis/benchmark_etl.py`

#### Problema Riscontrato
Modificando `MAX_CASES` tra un'esecuzione e l'altra o interrompendo la catena prima degli script finali, si potevano avere `download_manifest.json` e `quality_report.json` calcolati su 1.000 casi mentre `benchmark_report.json` e `ml_evaluation.json` restavano fermi a un run precedente su 50 casi.

#### Soluzione Tecnica
1. Impostato in `src/config.py` il valore standard `MAX_CASES = int(os.getenv("MAX_CASES", "500"))` (500 casi clinici), ottimizzando al contempo `LSTMAutoencoderDetector` in `src/detection/detector.py` (precisione `np.float32` e inferenza a blocchi zero-copy `torch.from_numpy`) per elaborare oltre 3,3 milioni di campioni riducendo del ~70% il consumo di RAM.
2. In `src/silver/clean.py`, `process_all_cases()` seleziona esclusivamente i casi appartenenti al manifest attivo (o i primi `MAX_CASES`) e rimuove automaticamente eventuali file Parquet Silver residui di run precedenti con perimetro più ampio.
3. In `src/gold/load_mongo.py`, `recover_incomplete_loads()` rimuove da `vital_signals`, `registry` e `anomalies_detected` eventuali casi fuori dal perimetro Silver attivo.
4. In `src/analysis/benchmark_etl.py`, il calcolo di spazio e null rate confronta i file Bronze e Silver filtrati esattamente sugli stessi `case_id` `committed` presenti in MongoDB Gold.

---

### PUNTO 12: OMOGENEITÀ MATEMATICA DEI CONTEGGI DQ SILVER E NON-PROPAGAZIONE DEGLI OUTLIER
* **File Modificati:** `src/silver/clean.py`, `tests/test_etl.py`

#### Problema Riscontrato
1. Nel report Silver, `observed` veniva contato sul DataFrame Bronze grezzo (prima dello scarto delle righe vuote), mentre `missing` e `coverage_pct` avevano come denominatore `rows_cleaned` (dopo lo scarto).
2. Per le pressioni NIBP (`SBP`, `DBP`, `MBP`), gli imputati venivano stimati indirettamente tramite `nibp_age_s > 0` (calcolato solo su `SBP`), portando in alcuni casi la somma $\text{observed} + \text{imputed} + \text{missing}$ a superare `rows_cleaned`.
3. I flag outlier venivano calcolati *dopo* il forward-fill (`ffill(limit=300)`): una singola lettura errata del bracciale veniva così copiata per 300 secondi e contata come 301 outlier consecutivi.

#### Soluzione Tecnica
1. **Outlier calcolati PRIMA dell'imputazione:** I flag `HR_outlier`, `SPO2_outlier`, `SBP_outlier`, `DBP_outlier`, `MBP_outlier` vengono valutati sui dati grezzi osservati prima di eseguire `interpolate_short_gaps` e `ffill(limit=300)`. Durante l'interpolazione e il forward-fill, i valori outlier vengono temporaneamente mascherati così da **non essere mai propagati** nelle righe successive, pur restando conservati nella riga originale in cui si sono verificati.
2. **Flag di imputazione espliciti per ogni traccia NIBP:** Create le colonne booleane dedicate `SBP_imputed`, `DBP_imputed` e `MBP_imputed` (oltre a `HR_imputed` e `SPO2_imputed`), che confluiscono automaticamente anche in `quality_flags` su MongoDB Gold.
3. **Denominatore unico e partizione esatta:** Tutti i conteggi di `sensor_metrics` sono calcolati sul DataFrame bonificato finale (`rows_cleaned`), garantendo per ogni sensore l'identità matematica:
   $$\text{observed} + \text{imputed} + \text{missing} \equiv \text{rows\_cleaned}$$
   Sono inoltre riportate tre percentuali distinte: `observed_pct` (sole misure native), `coverage_pct` (copertura post-imputazione su righe attive Silver) e `temporal_coverage_bronze_pct` (copertura rispetto alla durata grezza Bronze).

---

### PUNTO 13: USO DELLA FRESCHEZZA NIBP (`nibp_age_s`) NELLE REGOLE CLINICHE DI DETECTION
* **File Modificati:** `src/config.py`, `src/detection/detector.py`, `tests/test_detection.py`

#### Problema Riscontrato
Le pressioni propagate in avanti per LOCF fino a 300 secondi restavano attive per l'intero intervallo senza che le regole cliniche (`compute_shock_index` e `compute_severe_hypotension`) verificassero quanto fosse recente la misura pressoria. Un singolo valore basso poteva così generare allarmi clinici continui per 5 minuti.

#### Soluzione Tecnica
Introdotta in `src/config.py` la soglia `NIBP_MAX_CLINICAL_AGE_S = 120.0` (2 minuti). In `compute_shock_index()` e `compute_severe_hypotension()`, quando la colonna `nibp_age_s` è presente nel DataFrame, l'anomalia clinica viene attivata solo se la misura pressoria è fresca (`nibp_age_s <= 120.0`), evitando che valori LOCF obsoleti producano falsi positivi prolungati.

---

### PUNTO 14: FILTRO `status: "committed"` COERENTE SU TUTTI I LETTORI GOLD
* **File Modificati:** `src/analysis/queries.py`, `src/detection/detector.py`, `src/analysis/evaluate_models.py`, `src/analysis/benchmark_etl.py`

#### Problema Riscontrato
Mentre l'API passava da `list_loaded_cases()` (che accettava anche record privi del campo `status`), gli script `detector.py`, `evaluate_models.py` e `benchmark_etl.py` interrogavano direttamente `db['registry'].find({})` senza filtrare lo stato di commit.

#### Soluzione Tecnica
1. Reso rigoroso il filtro `{"status": "committed"}` in `list_loaded_cases()`.
2. Applicato il filtro `{"status": "committed"}` anche in `detector.py`, `evaluate_models.py` e `benchmark_etl.py`, garantendo che nessun componente analitico o di machine learning legga mai casi parziali.

---

### PUNTO 15: PROVENANCE END-TO-END CON `run_id` E `pipeline_version` CONDIVISI
* **File Modificati:** `src/config.py`, `src/bronze/download.py`, `src/silver/clean.py`, `src/gold/load_mongo.py`, `src/analysis/evaluate_models.py`, `src/analysis/benchmark_etl.py`

#### Soluzione Tecnica
Quando inizia l'ingestione Bronze (`download.py`), viene generato un nuovo `run_id` tramite `config.get_or_create_run_id(force_new=True)`. Tutti gli step successivi (`clean.py`, `load_mongo.py`, `evaluate_models.py`, `benchmark_etl.py`) leggono il medesimo `run_id` e lo scrivono, insieme a `pipeline_version: "1.1.0"`, dentro:
- `data/download_manifest.json`
- `data/quality_report.json`
- Collezione MongoDB `registry`
- `data/ml_evaluation.json`
- `data/benchmark_report.json`

In questo modo è verificabile istantaneamente che tutti i report e i documenti Gold appartengano alla stessa identica esecuzione.

---

### PUNTO 16: ALLINEAMENTO ETICHETTE E METRICHE NELLA DASHBOARD WEB
* **File Modificati:** `dashboard/partials/lakehouse-view.html`, `dashboard/js/lakehouse.js`

#### Problema Riscontrato
Nella vista Lakehouse della dashboard, il codice JavaScript inseriva nella prima colonna della tabella ML il valore `PR-AUC 0.xxx`, ma l'intestazione HTML della colonna riportava ancora la scritta statica *"Accuratezza Globale"* e il titolo riportava conteggi fissi cablati nell'HTML. Inoltre non era esplicitato visivamente se il peso del layer Gold includesse o meno gli indici.

#### Soluzione Tecnica
1. Sostituita l'intestazione della tabella HTML con `PR-AUC (Average Precision)`.
2. Resi dinamici in `lakehouse.js` il titolo e il sottotitolo della sezione ML (`#mlEvalTitle`, `#mlEvalSubtitle`), che ora mostrano il numero reale di casi, campioni e prevalenza della baseline letti da `/evaluation`, specificando chiaramente la natura di **Concordanza con Pseudo-Ground Truth Euristico**.
3. Esplicitato nella card dello Storage che la barra del Layer Gold rappresenta lo **Storage Puro Time Series (`storageSize`)**, aggiungendo una riga informativa dinamica (`#benchGoldIndexInfo`) che riporta separatamente il peso degli indici B-Tree (`gold_index_mb`), il totale `collStats` e la riduzione percentuale rispetto al layer Silver.
