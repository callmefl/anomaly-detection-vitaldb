"""Configurazione centralizzata del progetto.

Carica le variabili d'ambiente dal file .env e definisce
path e costanti usate in tutta la pipeline.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

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

# === Parametri biometrici di interesse ===
# Parametri numerici già estratti, come concordato con la docente
VITAL_TRACKS = [
    "Solar8000/HR",           # Heart Rate
    "Solar8000/PLETH_SPO2",   # Saturazione O2 (SpO2)
    "Solar8000/NIBP_SBP",     # Pressione sistolica non invasiva
    "Solar8000/NIBP_DBP",     # Pressione diastolica non invasiva
    "Solar8000/NIBP_MBP",     # Pressione media non invasiva
]

# === Parametri pipeline ===
SAMPLING_INTERVAL = 1.0  # Intervallo di campionamento in secondi
MAX_CASES = None          # Numero massimo di casi da scaricare (None = tutti)

# Crea le directory dati se non esistono
for d in [BRONZE_DIR, SILVER_DIR, RAW_DIR]:
    d.mkdir(parents=True, exist_ok=True)
