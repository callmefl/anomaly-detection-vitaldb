"""Configurazione centralizzata del progetto.

Carica le variabili d'ambiente dal file .env e definisce
path e costanti usate in tutta la pipeline.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Assicura supporto UTF-8 per console Windows (evita UnicodeEncodeError su charmap cp1252)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Carica variabili d'ambiente dal file .env nella root del progetto
ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# === MongoDB ===
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "vitaldb_project")

# === Directory dati ===
DATA_DIR = ROOT_DIR / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
RAW_DIR = DATA_DIR / "raw"

# === Versione e Governance della Pipeline ===
PIPELINE_VERSION = "1.0.0"

# === Specifiche unificate dei tracciati biometrici (Unica fonte di verità per range, unità e metadati) ===
TRACK_SPECS = {
    "Solar8000/HR": {
        "sensor_name": "Solar8000",
        "track_name": "HR",
        "unit": "bpm",
        "min": 20.0,
        "max": 250.0,
        "description": "Heart Rate / Frequenza cardiaca"
    },
    "Solar8000/PLETH_SPO2": {
        "sensor_name": "Solar8000",
        "track_name": "PLETH_SPO2",
        "unit": "%",
        "min": 50.0,
        "max": 100.0,
        "description": "Saturazione periferica d'ossigeno (SpO2)"
    },
    "Solar8000/NIBP_SBP": {
        "sensor_name": "Solar8000",
        "track_name": "NIBP_SBP",
        "unit": "mmHg",
        "min": 40.0,
        "max": 250.0,
        "description": "Pressione arteriosa sistolica non invasiva"
    },
    "Solar8000/NIBP_DBP": {
        "sensor_name": "Solar8000",
        "track_name": "NIBP_DBP",
        "unit": "mmHg",
        "min": 10.0,
        "max": 180.0,
        "description": "Pressione arteriosa diastolica non invasiva"
    },
    "Solar8000/NIBP_MBP": {
        "sensor_name": "Solar8000",
        "track_name": "NIBP_MBP",
        "unit": "mmHg",
        "min": 20.0,
        "max": 220.0,
        "description": "Pressione arteriosa media non invasiva"
    },
}

# Lista ordinata delle tracce biometriche d'interesse
VITAL_TRACKS = list(TRACK_SPECS.keys())

# === Parametri pipeline ===
SAMPLING_INTERVAL = 1.0  # Intervallo di campionamento in secondi
MAX_CASES = 50      # Numero di casi da scaricare per la sperimentazione (50 casi)

# Crea le directory dati se non esistono
for d in [BRONZE_DIR, SILVER_DIR, RAW_DIR]:
    d.mkdir(parents=True, exist_ok=True)
