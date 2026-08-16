---
name: vitaldb-anomaly-detection-execution-plan
description: Guida operativa dettagliata per il completamento end-to-end del progetto VitalDB Anomaly Detection (Layer Bronze/Silver/Gold, Governance MongoDB, Anomaly Detection e REST API).
---

# 🚀 Guida di Esecuzione e Completamento del Progetto VitalDB

Questo documento contiene le istruzioni tecniche precise e sequenziali per completare l'implementazione del progetto **VitalDB Anomaly Detection**, in stretta conformità con le specifiche concordate e riportate in `SKILL.md`.

---

## 📍 Fase 1: Ingestione Dati Completa (Layer Bronze)

### Obiettivi:
1. Integrazione dei dati di laboratorio tramite `vitaldb.load_lab_data()`.
2. Ingestione scalabile con supporto alla ripresa automatica in caso di disconnessioni di rete.

### Istruzioni Precise per l'Agent/LLM:
1. **Modificare `src/bronze/download.py`**:
   - Aggiungere la funzione `download_lab_data(output_dir)` che richiama `vitaldb.load_lab_data()`, converte in `pd.DataFrame` e salva in `data/bronze/lab_data.parquet`.
   - Aggiungere la gestione delle interruzioni creando/aggiornando un file `data/bronze/download_manifest.json` che registra gli ID dei casi già scaricati con successo per evitare download duplicati.
   - Consentire l'esecuzione da riga di comando specificando il numero di casi via argomento `--cases N` o variabile d'ambiente `MAX_CASES`.

---

## 📍 Fase 2: Partizionamento e Pulizia Avanzata (Layer Silver)

### Obiettivi:
1. Inserimento regole outlier per tutte le 5 tracce biometriche (`HR`, `SpO2`, `NIBP_SBP`, `NIBP_DBP`, `NIBP_MBP`).
2. Partizionamento fisico dei dati Silver per reparto chirurgico (`department`).

### Istruzioni Precise per l'Agent/LLM:
1. **Modificare `src/silver/clean.py`**:
   - Nella funzione `clean_case(df, case_id)` aggiungere i seguenti range di outlier fisiologici:
     - `Solar8000/NIBP_DBP`: range valido `[10, 180]` mmHg.
     - `Solar8000/NIBP_MBP`: range valido `[20, 220]` mmHg.
   - Integrare la lettura di `data/bronze/clinical_data.parquet` per associare la colonna `department` (reparto) a ciascun `case_id`.
   - Nella funzione `save_silver(df, case_id, silver_dir)`, salvare i file Parquet organizzandoli in cartelle partizionate per reparto: `data/silver/department=<REPARTO>/case_<ID>.parquet`.

---

## 📍 Fase 3: Transazioni Multi-Documento e Governance Lakehouse (Layer Gold)

### Obiettivi:
1. Implementare le transazioni multi-documento native di MongoDB (`pymongo.client_session`) per garantire atomicità tra il caricamento delle serie temporali in `vital_signals` e la registrazione dei metadati in `registry`.
2. Arricchire il campo `metaField` (`metadata`) della Time Series Collection.

### Istruzioni Precise per l'Agent/LLM:
1. **Modificare `src/gold/load_mongo.py`**:
   - Nella funzione `load_case_to_mongo`, espandere l'oggetto `metadata` di ogni documento Time Series inserendo:
     ```python
     "metadata": {
         "case_id": int(case_id),
         "sensor_name": "Solar8000",
         "department": str(dept),
         "age": int(age) if pd.notna(age) else None,
         "sex": str(sex) if pd.notna(sex) else None
     }
     ```
   - Nella funzione `process_silver_to_gold`, implementare la scrittura transazionale multi-documento usando `client.start_session()`:
     ```python
     with client.start_session() as session:
         with session.start_transaction():
             # 1. Inserimento record Time Series
             db.vital_signals.insert_many(records, session=session)
             # 2. Aggiornamento atomico del registry
             db.registry.insert_one(registry_doc, session=session)
     ```
   - Inserire la gestione delle eccezioni con `session.abort_transaction()` in caso di errore per garantire il rollback completo.

---

## 📍 Fase 4: Anomaly Detection Clinica e Salvataggio Risultati

### Obiettivi:
1. Integrazione di indici clinicamente motivati (es. **Shock Index** e **Ipotensione Severa**).
2. Modello Machine Learning non supervisionato basato su ricostruzione d'errore (**Autoencoder**).
3. Scrittura delle anomalie identificate direttamente su MongoDB Gold per persistenza e query veloci.

### Istruzioni Precise per l'Agent/LLM:
1. **Modificare `src/detection/detector.py`**:
   - Aggiungere il calcolo dello **Shock Index**: $$\text{SI} = \frac{\text{HR}}{\text{NIBP\_SBP}}$$. Marcare come anomalia clinica se $$\text{SI} > 0.9$$.
   - Aggiungere la regola dell'**Ipotensione Severa**: $$\text{NIBP\_MBP} < 65 \text{ mmHg}$$ E $$\text{SpO2} < 90\%$$.
   - Aggiungere una classe `AutoencoderDetector` basata su `sklearn.neural_network.MLPRegressor` che calcola l'errore di ricostruzione (MSE) e marca come anomalia i punti in cui l'errore supera il $95^\circ$ percentile.
   - Creare la funzione `save_anomalies_to_mongo(db, df_anomalies)` che scrive i punti anomali nella collezione MongoDB `anomalies_detected`.

---

## 📍 Fase 5: REST API (FastAPI) e Deployment

### Obiettivi:
1. Esporre le funzionalità del database Gold e dell'Anomaly Detection via API REST.
2. Fornire una configurazione pronta per il deployment su Vercel.

### Istruzioni Precise per l'Agent/LLM:
1. **Creare la cartella `api/` e il file `api/main.py`**:
   - Usare `FastAPI` e `uvicorn`.
   - Rotte richieste:
     - `GET /api/cases`: Restituisce la lista dei casi dal `registry`.
     - `GET /api/cases/{case_id}/series`: Restituisce le serie temporali da `vital_signals` con opzione di downsampling.
     - `POST /api/cases/{case_id}/detect`: Esegue la detection (statistica, clinica, ML) su un caso e restituisce i timestamp anomali.
2. **Creare `vercel.json` nella root**:
   - Configurazione per l'hosting serverless dell'API FastAPI su Vercel.
