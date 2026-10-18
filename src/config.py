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
PIPELINE_VERSION = "1.1.0"
RUN_ID_FILE = DATA_DIR / ".current_run_id"


def get_or_create_run_id(force_new: bool = False) -> str:
    """Restituisce il run_id condiviso dall'esecuzione corrente della pipeline per collegare tutti gli strati.

    Se `force_new=True` (es. all'avvio del layer Bronze) oppure se non esiste ancora un run_id attivo,
    ne genera uno nuovo e lo persiste in `data/.current_run_id`.
    """
    env_run_id = os.getenv("PIPELINE_RUN_ID")
    if env_run_id:
        return env_run_id

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not force_new and RUN_ID_FILE.exists():
        existing = RUN_ID_FILE.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    import datetime
    new_run_id = f"run_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    try:
        RUN_ID_FILE.write_text(new_run_id, encoding="utf-8")
    except OSError:
        pass
    return new_run_id


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
SAMPLING_INTERVAL = 1.0           # Intervallo di campionamento in secondi (1 Hz)
MAX_CASES = int(os.getenv("MAX_CASES", "500"))  # Perimetro standard per la sperimentazione (default: 500 casi)
NIBP_MAX_CLINICAL_AGE_S = 120.0   # Età massima (s) di una misura NIBP per attivare regole cliniche acute

# Crea le directory dati se non esistono
for d in [BRONZE_DIR, SILVER_DIR, RAW_DIR]:
    d.mkdir(parents=True, exist_ok=True)

