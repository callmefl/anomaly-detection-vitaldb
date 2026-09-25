"""Modulo per il caricamento dei dati bonificati dal layer Silver verso il layer Gold (MongoDB Time Series).

Il layer Gold rappresenta il vertice dell'architettura Medallion e l'interfaccia principale per query/ML:
- Inserisce le misurazioni temporali ad alta frequenza nella Time Series Collection nativa `vital_signals`.
- Sfrutta il campo `metaField` (`metadata`) per associare informazioni strutturate su paziente e reparto (`case_id`, `department`, `age`, `sex`).
- Registra ogni caricamento completato nel catalogo di Data Governance `registry` inserendo versione dello schema e provenance.
"""

import sys
from pathlib import Path
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import datetime
from tqdm import tqdm

# Setup importazioni radice
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Nome del sensore sorgente primario
SENSOR_NAME = "Solar8000"


def get_mongo_client():
    """Crea e restituisce il client di connessione PyMongo configurato."""
    return MongoClient(config.MONGO_URI)


def load_clinical_info(bronze_dir):
    """Costruisce la mappa hash `case_id -> {department, age, sex}` partendo dalle informazioni cliniche nel Bronze.

    Questi metadati vengono inseriti nel `metaField` di MongoDB per consentire il query pushdown
    ed il filtraggio rapido a livello di bucket compressi senza leggere la serie storica intera.

    Args:
        bronze_dir (Path): Cartella sorgente del layer Bronze.

    Returns:
        dict: Mappa dei metadati clinici per ciascun paziente.
    """
    clinical_path = bronze_dir / "clinical_data.parquet"
    if not clinical_path.exists():
        print(f"⚠️ Attenzione: {clinical_path} non trovato, metadati clinici non disponibili.")
        return {}

    df_clinical = pd.read_parquet(clinical_path)
    if "caseid" in df_clinical.columns:
        id_col = "caseid"
    elif "case_id" in df_clinical.columns:
        id_col = "case_id"
    else:
        print("⚠️ Attenzione: Nessuna colonna ID caso reperita in clinical_data.parquet.")
        return {}

    info = {}
    for _, row in df_clinical.iterrows():
        case_id = int(row[id_col])
        info[case_id] = {
            "department": row.get("department"),
            "age": row.get("age"),
            "sex": row.get("sex"),
        }
    return info


def init_track_metadata(db):
    """Inizializza la collezione track_metadata (Data Dictionary di Governance)."""
    initial_metadata = [
        {
            "sensor_name": "Solar8000",
            "track_name": "HR",
            "schema_version": "1.0",
            "unit_of_measure": "bpm",
            "expected_range": {"min": 20, "max": 250}
        },
        {
            "sensor_name": "Solar8000",
            "track_name": "PLETH_SPO2",
            "schema_version": "1.0",
            "unit_of_measure": "%",
            "expected_range": {"min": 50, "max": 100}
        },
        {
            "sensor_name": "Solar8000",
            "track_name": "NIBP_SBP",
            "schema_version": "1.0",
            "unit_of_measure": "mmHg",
            "expected_range": {"min": 40, "max": 250}
        },
        {
            "sensor_name": "Solar8000",
            "track_name": "NIBP_DBP",
            "schema_version": "1.0",
            "unit_of_measure": "mmHg",
            "expected_range": {"min": 10, "max": 200}
        },
        {
            "sensor_name": "Solar8000",
            "track_name": "NIBP_MBP",
            "schema_version": "1.0",
            "unit_of_measure": "mmHg",
            "expected_range": {"min": 20, "max": 220}
        }
    ]
    for meta in initial_metadata:
        db['track_metadata'].update_one(
            {"track_name": meta["track_name"]},
            {"$set": meta},
            upsert=True
        )


def ensure_timeseries_collections(db):
    """Verifica l'esistenza della Time Series Collection 'vital_signals' e delle collezioni di governance."""
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
        print("✓ Collezione Time Series 'vital_signals' creata con successo su MongoDB.")

    # Indice per accelerare query e bucketing su vital_signals
    db['vital_signals'].create_index([("metadata.case_id", 1), ("timestamp", 1)])

    # Registry e indice univoco per case_id
    if 'registry' not in collections:
        db.create_collection('registry')
        print("✓ Collezione 'registry' creata.")
    db['registry'].create_index("case_id", unique=True)

    # Inizializza il Data Dictionary
    init_track_metadata(db)


def build_metadata(case_id, clinical_info):
    """Costruisce il sotto-documento `metadata` (metaField) per un dato paziente.

    Args:
        case_id (int): Identificativo univoco del caso.
        clinical_info (dict): Mappa dei metadati clinici.

    Returns:
        dict: Documento strutturato pronto per il metaField di MongoDB.
    """
    info = clinical_info.get(case_id, {})
    department = info.get("department")
    age = info.get("age")
    sex = info.get("sex")

    return {
        "case_id": int(case_id),
        "sensor_name": SENSOR_NAME,
        "department": str(department) if pd.notna(department) else None,
        "age": int(age) if pd.notna(age) else None,
        "sex": str(sex) if pd.notna(sex) else None,
    }


def build_records(df, case_id, clinical_info):
    """Trasforma le righe della tabella Silver in un array di documenti BSON pronti per il caricamento su MongoDB Gold.

    Args:
        df (pd.DataFrame): Dati bonificati dal layer Silver.
        case_id (int): ID del caso.
        clinical_info (dict): Metadati clinici di contesto.

    Returns:
        list: Lista di documenti BSON pronti per l'inserimento in `vital_signals`.
    """
    records = []
    metadata = build_metadata(case_id, clinical_info)
    base_time = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    # Nomi delle colonne contenenti i flag di outlier dal Silver
    OUTLIER_COLS = ['HR_outlier', 'SPO2_outlier', 'SBP_outlier', 'DBP_outlier', 'MBP_outlier']
    for _, row in df.iterrows():
        current_time = base_time + datetime.timedelta(seconds=float(row.get('Time', 0)))
        doc = {
            "timestamp": current_time,
            "metadata": metadata,
            "metrics": {},
            "quality_flags": {}  # <-- CAMPO GOVERNANCE DAL SILVER
        }
        # Metriche vitali
        for col in config.VITAL_TRACKS:
            if col in row and pd.notna(row[col]):
                safe_col = col.replace('/', '_')
                doc["metrics"][safe_col] = float(row[col])
        # Flag di qualità generati nel layer Silver
        for col in OUTLIER_COLS:
            if col in row and pd.notna(row[col]):
                doc["quality_flags"][col] = bool(row[col])
        if doc["metrics"]:
            records.append(doc)
    return records


def build_registry_doc(case_id, record_count, quality_summary=None):
    """Crea il documento di tracciamento di Data Governance da inserire nel catalogo `registry`."""
    doc = {
        "case_id": int(case_id),
        "record_count": int(record_count),
        "schema_version": "1.0",
        "provenance": {
            "step": "silver_to_gold",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
        }
    }
    if quality_summary:
        doc["quality_summary"] = quality_summary
    return doc


def load_case_to_mongo(client, db, df, case_id, clinical_info):
    """Effettua l'inserimento atomico (transazionale) delle serie temporali e la registrazione nel catalog `registry`."""
    records = build_records(df, case_id, clinical_info)
    if not records:
        return 0

    OUTLIER_COLS = ['HR_outlier', 'SPO2_outlier', 'SBP_outlier', 'DBP_outlier', 'MBP_outlier']
    quality_summary = {
        col: int(df[col].sum()) for col in OUTLIER_COLS if col in df.columns
    }
    registry_doc = build_registry_doc(case_id, len(records), quality_summary)

    try:
        # Avvia una sessione e una transazione atomica ACID su Replica Set
        with client.start_session() as session:
            try:
                with session.start_transaction():
                    db['vital_signals'].insert_many(records, session=session)
                    db['registry'].insert_one(registry_doc, session=session)
            except PyMongoError as pe:
                # Fallback trasparente per deployment standalone (senza replica set attivo)
                if "Transaction numbers are only allowed on a replica set member" in str(pe) or "replica set" in str(pe):
                    db['vital_signals'].insert_many(records)
                    db['registry'].insert_one(registry_doc)
                else:
                    raise
    except PyMongoError as e:
        print(f"❌ Errore durante l'inserimento atomico su MongoDB per il caso #{case_id}: {e}")
        raise
    return len(records)


def process_silver_to_gold(silver_dir, bronze_dir=None):
    """Itera su tutti i file Parquet del layer Silver e li inserisce in MongoDB Gold."""
    bronze_dir = bronze_dir or config.BRONZE_DIR
    client = get_mongo_client()
    db = client[config.DB_NAME]
    ensure_timeseries_collections(db)

    clinical_info = load_clinical_info(bronze_dir)
    parquet_files = list(silver_dir.rglob("case_*.parquet"))

    for p_file in tqdm(parquet_files, desc="Caricamento in MongoDB (Gold)"):
        try:
            case_id = int(p_file.stem.split('_')[1])
            df = pd.read_parquet(p_file)

            # Salta i casi già caricati nel registro per evitare duplicazioni
            if db['registry'].find_one({"case_id": case_id}):
                continue

            load_case_to_mongo(client, db, df, case_id, clinical_info)

        except Exception as e:
            print(f"❌ Errore nel caricamento del caso da {p_file.name}: {e}")


if __name__ == '__main__':
    print("=== INIZIO CARICAMENTO IN MONGODB GOLD ===")
    process_silver_to_gold(config.SILVER_DIR)
    print("=== PIPELINE GOLD COMPLETATA CON SUCCESSO ===")
