"""REST API FastAPI per l'interazione con il layer Gold di MongoDB ed i moduli di Anomaly Detection.

Questo backend viene eseguito all'interno del container Docker `vitaldb_api` sulla porta 8000
ed interagisce direttamente con il database MongoDB 8.0 `vitaldb_mongo`.

Rotte REST esposte:
- GET  /health                        Controllo di stato di salute dell'API e della connessione.
- GET  /cases                         Restituisce la lista dei casi clinici registrati nel catalog `registry`.
- GET  /cases/{case_id}/series        Restituisce la serie temporale biometrica di un caso (con downsampling temporale opzionale).
- POST /cases/{case_id}/detect        Esegue la pipeline di Anomaly Detection (Regole Cliniche + ML) e salva le anomalie su MongoDB.
"""

import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import fastapi
import fastapi.middleware.cors
from fastapi import HTTPException
from pymongo import MongoClient

# Aggiunge la radice del progetto al sys.path per importare i moduli interni in src/
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src import config
from src.analysis.queries import get_case_series, downsample_case, list_loaded_cases
from src.detection.detector import run_detection_pipeline

from fastapi.staticfiles import StaticFiles

# Inizializzazione dell'applicazione FastAPI
app = fastapi.FastAPI(
    title="VitalDB Anomaly Detection API",
    description="REST API per l'esplorazione ed il rilevamento anomalie su dati biometrici intraoperatori.",
    version="1.0.0"
)

# Abilita CORS (Cross-Origin Resource Sharing) per consentire le chiamate dal frontend dashboard/index.html
app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Monta la cartella statica della Dashboard web
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

# Monta la cartella statica delle Slide di Presentazione (Slidesgo AI Tech Theme)
presentazione_dir = Path(__file__).resolve().parent.parent / "presentazione"
if presentazione_dir.exists():
    app.mount("/presentazione", StaticFiles(directory=str(presentazione_dir), html=True), name="presentazione")

# Variabile globale per il riutilizzo della connessione PyMongo tra le varie richieste HTTP
_client: Optional[MongoClient] = None


def get_db():
    """Restituisce l'istanza del database MongoDB configurato, riutilizzando il pool di connessioni."""
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI)
    return _client[config.DB_NAME]


@app.get("/health")
async def health():
    """Endpoint di Health Check per verificare l'operatività del container e dell'API."""
    return {"status": "ok", "database": config.DB_NAME}


@app.get("/cases")
async def get_cases():
    """Restituisce l'elenco di tutti i casi clinici caricati nel layer Gold, arricchiti con i metadati di paziente."""
    db = get_db()
    df = list_loaded_cases(db)
    if df.empty:
        return []
    
    records = df.replace({np.nan: None}).to_dict(orient="records")
    for rec in records:
        c_id = rec.get("case_id")
        sample_doc = db['vital_signals'].find_one({"metadata.case_id": c_id}, {"metadata": 1})
        if sample_doc and "metadata" in sample_doc:
            meta = sample_doc["metadata"]
            rec["department"] = meta.get("department") or "Chirurgia Generale"
            rec["age"] = meta.get("age")
            rec["sex"] = meta.get("sex")
        else:
            rec["department"] = "Chirurgia Generale"
            rec["age"] = None
            rec["sex"] = None

    return records


@app.get("/cases/{case_id}/series")
async def get_series(case_id: int, window_seconds: Optional[int] = None):
    """Restituisce la serie temporale dei parametri vitali di un dato paziente.

    Args:
        case_id (int): Identificativo univoco del caso clinico.
        window_seconds (Optional[int]): Se specificato (es. 30, 60, 300), applica l'aggregazione
            temporale lato database ($bucketAuto o media per intervallo) per ridurre i dati inviati.
    """
    db = get_db()

    if window_seconds:
        df = downsample_case(db, case_id, window_seconds=window_seconds)
        if not df.empty:
            df = df.rename(columns={"window_start": "timestamp"})
    else:
        df = get_case_series(db, case_id)

    if df.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato trovato per il caso #{case_id}")

    # Converte il campo timestamp in stringa ISO ed effettua il sanitizing dei valori NaN per JSON
    df["timestamp"] = df["timestamp"].astype(str)
    df = df.replace({np.nan: None})
    return df.to_dict(orient="records")


@app.post("/cases/{case_id}/detect")
async def detect_case(case_id: int):
    """Esegue l'algoritmo multilivello di Anomaly Detection sul caso specificato.

    Calcola le Regole Cliniche (Shock Index ed Ipotensione Severa) e gli algoritmi di Machine Learning
    (Isolation Forest ed Autoencoder Neurale). Salva i punti anomali trovati nella collezione
    MongoDB `anomalies_detected` e restituisce i risultati al chiamante.
    """
    db = get_db()
    df = run_detection_pipeline(db, [case_id])

    if df.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato temporale disponibile per case_id={case_id}")

    # Individua le colonne marcate come anomalia
    flag_cols = [c for c in df.columns if c.endswith("_anomaly")]
    anomalous_rows = df[df[flag_cols].any(axis=1)]

    # Calcola il conteggio dettagliato per ciascuna metodologia di detection
    summary_by_method = {}
    for col in flag_cols:
        method_name = col.replace("_anomaly", "")
        summary_by_method[method_name] = int(df[col].sum())

    anomalies = []
    for _, row in anomalous_rows.iterrows():
        methods = [c.replace("_anomaly", "") for c in flag_cols if bool(row[c])]
        
        # Converte i valori Float di Pandas sanitizzando eventuali NaN
        hr_val = float(row["Solar8000_HR"]) if "Solar8000_HR" in row and pd.notna(row["Solar8000_HR"]) else None
        spo2_val = float(row["Solar8000_PLETH_SPO2"]) if "Solar8000_PLETH_SPO2" in row and pd.notna(row["Solar8000_PLETH_SPO2"]) else None
        sbp_val = float(row["Solar8000_NIBP_SBP"]) if "Solar8000_NIBP_SBP" in row and pd.notna(row["Solar8000_NIBP_SBP"]) else None
        dbp_val = float(row["Solar8000_NIBP_DBP"]) if "Solar8000_NIBP_DBP" in row and pd.notna(row["Solar8000_NIBP_DBP"]) else None
        mbp_val = float(row["Solar8000_NIBP_MBP"]) if "Solar8000_NIBP_MBP" in row and pd.notna(row["Solar8000_NIBP_MBP"]) else None
        si_val = float(row["shock_index"]) if "shock_index" in row and pd.notna(row["shock_index"]) else None

        anomalies.append({
            "timestamp": str(row["timestamp"]),
            "methods": methods,
            "hr": hr_val,
            "spo2": spo2_val,
            "sbp": sbp_val,
            "dbp": dbp_val,
            "mbp": mbp_val,
            "shock_index": round(si_val, 3) if si_val is not None else None
        })

    return {
        "case_id": case_id,
        "anomaly_count": len(anomalies),
        "summary_by_method": summary_by_method,
        "anomalies": anomalies,
    }
