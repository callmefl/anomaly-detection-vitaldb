"""Carica i dati dal layer Silver verso MongoDB Time Series Collections."""

import sys
from pathlib import Path
import pandas as pd
from pymongo import MongoClient
import datetime
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

def get_mongo_client():
    """Restituisce una connessione al client MongoDB."""
    return MongoClient(config.MONGO_URI)

def ensure_timeseries_collections(db):
    """Verifica e crea la Time Series Collection se non esiste."""
    collections = db.list_collection_names()
    if 'vital_signals' not in collections:
        db.create_collection(
            'vital_signals',
            timeseries={
                'timeField': 'timestamp',
                'metaField': 'metadata',
                'granularity': 'seconds'
            }
        )
        print("Collezione time-series 'vital_signals' creata.")

def load_case_to_mongo(df, case_id, db):
    """Carica un DataFrame pulito nella collezione Time Series.
    
    Trasforma il DataFrame in una struttura di documenti adatta 
    ad una Time Series Collection.
    """
    collection = db['vital_signals']
    records = []
    
    base_time = datetime.datetime(2020, 1, 1) # Timestamp fittizio base per serie storiche relative
    
    for _, row in df.iterrows():
        # Usa il campo Time (secondi) per calcolare un timestamp simulato per MongoDB
        current_time = base_time + datetime.timedelta(seconds=float(row.get('Time', 0)))
        
        doc = {
            "timestamp": current_time,
            "metadata": {
                "case_id": case_id
            },
            "metrics": {}
        }
        
        # Inserisci le metriche disponibili
        for col in config.VITAL_TRACKS:
            if col in row and pd.notna(row[col]):
                # sanitize chiave per mongo (non può contenere punti, ma '/' va bene, 
                # convertiamo '/' in '_' per pulizia)
                safe_col = col.replace('/', '_')
                doc["metrics"][safe_col] = float(row[col])
                
        if doc["metrics"]: # Inserisci solo se ci sono dati
            records.append(doc)
            
    if records:
        collection.insert_many(records)
        return len(records)
    return 0

def update_registry(db, case_id, record_count):
    """Aggiorna la collezione registry con i metadati del caricamento."""
    registry = db['registry']
    registry.insert_one({
        "case_id": case_id,
        "record_count": record_count,
        "schema_version": "1.0",
        "provenance": {
            "step": "silver_to_gold",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
        }
    })

def process_silver_to_gold(silver_dir):
    """Carica tutti i casi Silver in MongoDB."""
    client = get_mongo_client()
    db = client[config.DB_NAME]
    ensure_timeseries_collections(db)
    
    parquet_files = list(silver_dir.glob("case_*.parquet"))
    
    for p_file in tqdm(parquet_files, desc="Caricamento in MongoDB (Gold)"):
        try:
            case_id = int(p_file.stem.split('_')[1])
            df = pd.read_parquet(p_file)
            
            # Controllo se il caso è già stato caricato (tramite registry)
            if db['registry'].find_one({"case_id": case_id}):
                continue
                
            count = load_case_to_mongo(df, case_id, db)
            if count > 0:
                update_registry(db, case_id, count)
                
        except Exception as e:
            print(f"Errore nel caricamento del caso da {p_file.name}: {e}")

if __name__ == '__main__':
    print("Inizio caricamento in MongoDB...")
    process_silver_to_gold(config.SILVER_DIR)
    print("Caricamento completato.")
