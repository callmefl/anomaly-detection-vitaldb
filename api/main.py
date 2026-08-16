"""REST API per esporre il layer Gold (MongoDB) e l'Anomaly Detection.

Il servizio viene eseguito da Vercel tramite `experimentalServices` (vedi
`vercel.json` nella root del progetto). Le rotte sono definite senza il
prefisso `/api`: Vercel lo rimuove automaticamente prima di instradare la
richiesta a questo backend.

Rotte esposte:
- GET  /health                        Controllo di stato del servizio.
- GET  /cases                         Elenco dei casi caricati (dal registry).
- GET  /cases/{case_id}/series        Serie temporale di un caso (con downsampling opzionale).
- POST /cases/{case_id}/detect        Esegue l'anomaly detection su un caso e ne salva i risultati.
"""

import sys
from pathlib import Path
from typing import Optional

import fastapi
import fastapi.middleware.cors
from fastapi import HTTPException
from pymongo import MongoClient

# Aggiunge la root del progetto al path per importare i moduli in src/
sys.path.append(str(Path(__file__).resolve().parent.parent))
from src import config
from src.analysis.queries import get_case_series, downsample_case, list_loaded_cases
from src.detection.detector import run_detection_pipeline

app = fastapi.FastAPI(title="VitalDB Anomaly Detection API")

app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_client: Optional[MongoClient] = None


def get_db():
    """Restituisce il database configurato, riutilizzando la connessione tra le richieste."""
    global _client
    if _client is None:
        _client = MongoClient(config.MONGO_URI)
    return _client[config.DB_NAME]


@app.get("/health")
async def health():
    """Controllo di stato minimale del servizio."""
    return {"status": "ok"}


@app.get("/cases")
async def get_cases():
    """Restituisce la lista dei casi caricati, letta dalla collezione `registry`."""
    db = get_db()
    df = list_loaded_cases(db)
    if df.empty:
        return []
    return df.to_dict(orient="records")


@app.get("/cases/{case_id}/series")
async def get_series(case_id: int, window_seconds: Optional[int] = None):
    """Restituisce la serie temporale di un caso.

    Args:
        case_id: ID del caso da interrogare.
        window_seconds: se fornito, applica un downsampling lato MongoDB
            (media per finestra temporale) invece di restituire ogni punto.
    """
    db = get_db()

    if window_seconds:
        df = downsample_case(db, case_id, window_seconds=window_seconds)
        if not df.empty:
            df = df.rename(columns={"window_start": "timestamp"})
    else:
        df = get_case_series(db, case_id)

    if df.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato trovato per case_id={case_id}")

    df["timestamp"] = df["timestamp"].astype(str)
    return df.to_dict(orient="records")


@app.post("/cases/{case_id}/detect")
async def detect_case(case_id: int):
    """Esegue la detection (statistica, clinica, ML) su un caso e salva i risultati.

    I punti anomali vengono persistiti nella collezione `anomalies_detected`
    (tramite `save_anomalies_to_mongo`, chiamata internamente da
    `run_detection_pipeline`) e restituiti nella risposta.
    """
    db = get_db()
    df = run_detection_pipeline(db, [case_id])

    if df.empty:
        raise HTTPException(status_code=404, detail=f"Nessun dato trovato per case_id={case_id}")

    flag_cols = [c for c in df.columns if c.endswith("_anomaly")]
    anomalous_rows = df[df[flag_cols].any(axis=1)]

    anomalies = []
    for _, row in anomalous_rows.iterrows():
        methods = [c.replace("_anomaly", "") for c in flag_cols if bool(row[c])]
        anomalies.append({"timestamp": str(row["timestamp"]), "methods": methods})

    return {
        "case_id": case_id,
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }
