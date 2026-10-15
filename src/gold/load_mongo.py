"""Modulo per il caricamento dei dati bonificati dal layer Silver verso il layer Gold (MongoDB Time Series).

Il layer Gold rappresenta il vertice dell'architettura Medallion e l'interfaccia principale per query/ML:
- Inserisce le misurazioni temporali ad alta frequenza nella Time Series Collection nativa `vital_signals`.
- Sfrutta il campo `metaField` (`metadata`) per associare informazioni strutturate su paziente e reparto (`case_id`, `department`, `age`, `sex`).
- Registra ogni caricamento completato nel catalogo di Data Governance `registry` inserendo versione dello schema e provenance.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import datetime
from tqdm import tqdm

# Setup importazioni radice
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

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
        # Forza a int Python puro: evita mismatch np.int64 vs int in dict.get()
        case_id = int(row[id_col])
        info[case_id] = {
            "department": row.get("department"),
            "age": row.get("age"),
            "sex": row.get("sex"),
        }
    return info


def ensure_timeseries_collections(db):
    """Verifica l'esistenza della Time Series Collection 'vital_signals' su MongoDB ed la crea se assente."""
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


def seed_track_metadata(db):
    """Sincronizza la collezione 'track_metadata' da config.TRACK_SPECS come unica fonte di verità."""
    try:
        if 'track_metadata' not in db.list_collection_names():
            db.create_collection("track_metadata")

        for full_track, spec in getattr(config, "TRACK_SPECS", {}).items():
            doc = {
                "sensor_name": spec.get("sensor_name", SENSOR_NAME),
                "track_name": spec.get("track_name", full_track.split('/')[-1]),
                "full_track": full_track,
                "schema_version": "1.0",
                "unit_of_measure": spec.get("unit", ""),
                "expected_range": {"min": spec.get("min"), "max": spec.get("max")},
                "description": spec.get("description", "")
            }
            db['track_metadata'].update_one(
                {"track_name": doc["track_name"]},
                {"$set": doc},
                upsert=True
            )
        print("✓ Catalogo 'track_metadata' sincronizzato con config.TRACK_SPECS.")
    except Exception as e:
        print(f"⚠️ Impossibile sincronizzare track_metadata: {e}")


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

    Include le metriche vitali, i flag di outlier, eventuali flag di imputazione (*_imputed)
    e lo stato di staleness emodinamica 'nibp_age_s'.

    Args:
        df (pd.DataFrame): Dati bonificati dal layer Silver.
        case_id (int): ID del caso.
        clinical_info (dict): Metadati clinici di contesto.

    Returns:
        list: Lista di documenti BSON pronti per l'inserimento in `vital_signals`.
    """
    records = []
    metadata = build_metadata(case_id, clinical_info)
    base_time = datetime.datetime(2020, 1, 1)
    OUTLIER_COLS = ['HR_outlier', 'SPO2_outlier', 'SBP_outlier', 'DBP_outlier', 'MBP_outlier']

    for _, row in df.iterrows():
        current_time = base_time + datetime.timedelta(seconds=float(row.get('Time', 0)))
        doc = {
            "timestamp": current_time,
            "metadata": metadata,
            "metrics": {},
            "quality_flags": {}
        }
        # Metriche vitali
        for col in config.VITAL_TRACKS:
            if col in row and pd.notna(row[col]):
                safe_col = col.replace('/', '_')
                doc["metrics"][safe_col] = float(row[col])

        # Flag di qualità da Silver (outlier fisiologici)
        for col in OUTLIER_COLS:
            if col in row and pd.notna(row[col]):
                doc["quality_flags"][col] = bool(row[col])

        # Flag di imputazione per segnali interpolati o forward-filled
        for col in row.index:
            if col.endswith('_imputed') and pd.notna(row[col]):
                doc["quality_flags"][col] = bool(row[col])

        # Metadato di freschezza della pressione (staleness in secondi)
        if 'nibp_age_s' in row and pd.notna(row['nibp_age_s']):
            doc["quality_flags"]["nibp_age_s"] = float(row['nibp_age_s'])

        if doc["metrics"]:
            records.append(doc)
    return records


def validate_records(records):
    """Esegue la validazione applicativa preventiva sui record destinati a MongoDB Gold prima dell'inserimento."""
    if not records:
        return True

    for i, doc in enumerate(records):
        # 1. Timestamp obbligatorio e di tipo datetime
        ts = doc.get("timestamp")
        if not ts or not isinstance(ts, datetime.datetime):
            raise ValueError(f"Record #{i}: timestamp mancante o non di tipo datetime ({type(ts)}).")

        # 2. Metadata obbligatorio con case_id intero e sensor_name
        meta = doc.get("metadata")
        if not meta or not isinstance(meta, dict):
            raise ValueError(f"Record #{i}: metaField 'metadata' mancante o non dizionario.")
        if "case_id" not in meta or not isinstance(meta["case_id"], int):
            raise ValueError(f"Record #{i}: 'metadata.case_id' mancante o non intero nativo.")
        if "sensor_name" not in meta or not isinstance(meta["sensor_name"], str):
            raise ValueError(f"Record #{i}: 'metadata.sensor_name' mancante o non stringa.")

        # 3. Metriche: deve contenere almeno un valore numerico valido
        metrics = doc.get("metrics")
        if not metrics or not isinstance(metrics, dict):
            raise ValueError(f"Record #{i}: 'metrics' vuoto o non dizionario.")
        for k, v in metrics.items():
            if not isinstance(v, (float, int)) or pd.isna(v) or np.isinf(v):
                raise ValueError(f"Record #{i}: valore non valido per metrica '{k}': {v}")

    return True


def build_registry_doc(case_id, record_count, status="committed", run_id=None, pipeline_version=None):
    """Crea il documento di tracciamento di Data Governance da inserire nel catalogo `registry`."""
    p_version = pipeline_version or getattr(config, "PIPELINE_VERSION", "1.0.0")
    now = datetime.datetime.now(datetime.timezone.utc)
    return {
        "case_id": int(case_id),
        "status": status,
        "record_count": int(record_count),
        "schema_version": "1.0",
        "pipeline_version": p_version,
        "run_id": run_id or now.strftime("%Y%m%d_%H%M%S"),
        "provenance": {
            "step": "silver_to_gold",
            "timestamp": now,
            "pipeline_version": p_version,
            "cleaning_params": {
                "max_gap_seconds": 5.0,
                "nibp_staleness_limit_s": 300.0,
                "sampling_interval_s": config.SAMPLING_INTERVAL
            }
        }
    }


def load_case_to_mongo(client, db, df, case_id, clinical_info, run_id=None):
    """Inserisce le serie temporali e registra il caso nel catalog `registry` con idempotenza a due fasi.

    Strategia di compensazione manuale per MongoDB Time Series Collections:
    1. Registra nel registry status='loading' (evita letture concorrenti di dati parziali).
    2. Cancella i punti precedenti per questo case_id in 'vital_signals' (tramite metadata.case_id).
    3. Valida applicativamente i record tramite validate_records().
    4. Inserisce i record in 'vital_signals'.
    5. Imposta nel registry status='committed' con record_count e provenance arricchita.
    """
    records = build_records(df, case_id, clinical_info)
    if not records:
        return 0

    # Validazione applicativa preliminare
    validate_records(records)

    now = datetime.datetime.now(datetime.timezone.utc)
    p_version = getattr(config, "PIPELINE_VERSION", "1.0.0")
    rid = run_id or now.strftime("%Y%m%d_%H%M%S")

    # 1. Imposta lo stato su 'loading' nel registry
    db['registry'].update_one(
        {"case_id": int(case_id)},
        {"$set": {
            "case_id": int(case_id),
            "status": "loading",
            "schema_version": "1.0",
            "pipeline_version": p_version,
            "run_id": rid,
            "record_count": 0,
            "provenance": {
                "step": "silver_to_gold",
                "timestamp": now,
                "pipeline_version": p_version
            }
        }},
        upsert=True
    )

    # 2. Cancella i residui precedenti per questo caso in vital_signals
    db['vital_signals'].delete_many({"metadata.case_id": int(case_id)})

    # 3. Inserimento dei record nella Time Series Collection
    try:
        db['vital_signals'].insert_many(records)
    except PyMongoError as e:
        print(f"❌ Errore durante l'inserimento in vital_signals per il caso #{case_id}: {e}")
        raise

    # 4. Commit applicativo
    registry_doc = build_registry_doc(
        case_id=case_id,
        record_count=len(records),
        status="committed",
        run_id=rid,
        pipeline_version=p_version
    )
    try:
        db['registry'].update_one(
            {"case_id": int(case_id)},
            {"$set": registry_doc},
            upsert=True
        )
    except PyMongoError as e:
        print(f"⚠️ Punti inseriti in vital_signals per il caso #{case_id}, ma commit in 'registry' fallito: {e}")
        raise

    return len(records)


def process_silver_to_gold(silver_dir, bronze_dir=None):
    """Itera su tutti i file Parquet del layer Silver e li inserisce in MongoDB Gold."""
    bronze_dir = bronze_dir or config.BRONZE_DIR
    client = get_mongo_client()
    db = client[config.DB_NAME]
    ensure_timeseries_collections(db)
    seed_track_metadata(db)

    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    clinical_info = load_clinical_info(bronze_dir)
    parquet_files = list(silver_dir.rglob("case_*.parquet"))

    for p_file in tqdm(parquet_files, desc="Caricamento in MongoDB (Gold)"):
        try:
            case_id = int(p_file.stem.split('_')[1])
            df = pd.read_parquet(p_file)

            # Salta solo i casi già committed
            existing = db['registry'].find_one({"case_id": case_id})
            if existing and existing.get("status") == "committed":
                continue

            load_case_to_mongo(client, db, df, case_id, clinical_info, run_id=run_id)

        except Exception as e:
            print(f"❌ Errore nel caricamento del caso da {p_file.name}: {e}")


if __name__ == '__main__':
    print("=== INIZIO CARICAMENTO IN MONGODB GOLD ===")
    process_silver_to_gold(config.SILVER_DIR)
    print("=== PIPELINE GOLD COMPLETATA CON SUCCESSO ===")

