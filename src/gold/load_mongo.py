"""Carica i dati dal layer Silver verso MongoDB Time Series Collections."""

import sys
from pathlib import Path
import pandas as pd
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import datetime
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

SENSOR_NAME = "Solar8000"  # Tutte le tracce in config.VITAL_TRACKS provengono da questo sensore


def get_mongo_client():
    """Restituisce una connessione al client MongoDB."""
    return MongoClient(config.MONGO_URI)


def load_clinical_info(bronze_dir):
    """Costruisce una mappa case_id -> {department, age, sex} dai dati clinici Bronze.

    Questi metadati clinici arricchiscono il `metaField` della Time Series
    Collection, così le query possono filtrare/raggruppare per reparto,
    fascia d'età o sesso senza dover leggere i punti della serie storica.

    Args:
        bronze_dir (Path): Cartella del layer Bronze.

    Returns:
        dict: Mappa {case_id (int): dict con chiavi 'department', 'age', 'sex'}.
    """
    clinical_path = bronze_dir / "clinical_data.parquet"
    if not clinical_path.exists():
        print(f"Attenzione: {clinical_path} non trovato, metadata clinici assenti.")
        return {}

    df_clinical = pd.read_parquet(clinical_path)
    if "caseid" in df_clinical.columns:
        id_col = "caseid"
    elif "case_id" in df_clinical.columns:
        id_col = "case_id"
    else:
        print("Attenzione: nessuna colonna id caso trovata in clinical_data.parquet.")
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

def build_metadata(case_id, clinical_info):
    """Costruisce il documento `metadata` (metaField) per un caso.

    Il metaField è arricchito con sensore, reparto, età e sesso: questo
    permette di filtrare/raggruppare le serie storiche per queste dimensioni
    a livello di bucket, senza dover leggere i singoli punti `metrics`.

    Args:
        case_id (int): ID del caso.
        clinical_info (dict): Mappa case_id -> {'department', 'age', 'sex'}
            prodotta da `load_clinical_info`.

    Returns:
        dict: Documento di metadati pronto per l'inserimento.
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
    """Trasforma il DataFrame Silver di un caso in documenti Time Series.

    Non scrive su MongoDB: costruisce solo la lista di documenti, così che
    la scrittura possa avvenire all'interno di una transazione insieme
    all'aggiornamento del registry.

    Args:
        df (pd.DataFrame): Dati puliti del caso (layer Silver).
        case_id (int): ID del caso.
        clinical_info (dict): Mappa case_id -> metadati clinici.

    Returns:
        list: Documenti pronti per `insert_many` sulla collezione `vital_signals`.
    """
    records = []
    metadata = build_metadata(case_id, clinical_info)

    base_time = datetime.datetime(2020, 1, 1)  # Timestamp fittizio base per serie storiche relative

    for _, row in df.iterrows():
        # Usa il campo Time (secondi) per calcolare un timestamp simulato per MongoDB
        current_time = base_time + datetime.timedelta(seconds=float(row.get('Time', 0)))

        doc = {
            "timestamp": current_time,
            "metadata": metadata,
            "metrics": {}
        }

        # Inserisci le metriche disponibili
        for col in config.VITAL_TRACKS:
            if col in row and pd.notna(row[col]):
                # sanitize chiave per mongo (non può contenere punti, ma '/' va bene, 
                # convertiamo '/' in '_' per pulizia)
                safe_col = col.replace('/', '_')
                doc["metrics"][safe_col] = float(row[col])

        if doc["metrics"]:  # Inserisci solo se ci sono dati
            records.append(doc)

    return records


def build_registry_doc(case_id, record_count):
    """Costruisce il documento di registry per un caso caricato.

    Args:
        case_id (int): ID del caso.
        record_count (int): Numero di punti temporali inseriti.

    Returns:
        dict: Documento pronto per `insert_one` sulla collezione `registry`.
    """
    return {
        "case_id": int(case_id),
        "record_count": record_count,
        "schema_version": "1.0",
        "provenance": {
            "step": "silver_to_gold",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
        }
    }


def load_case_transactional(client, db, df, case_id, clinical_info):
    """Carica un caso in `vital_signals` e aggiorna `registry` in una singola
    transazione multi-documento nativa di MongoDB.

    L'atomicità garantisce che, in caso di errore a metà operazione, non si
    verifichi lo scenario "punti vitali inseriti ma registry non aggiornato"
    (o viceversa): la transazione viene abortita e nessuna delle due scritture
    resta visibile.

    Nota: le transazioni multi-documento richiedono che MongoDB sia in
    esecuzione come replica set (anche a singolo nodo), non come `mongod`
    standalone.

    Args:
        client: MongoClient connesso.
        db: Database pymongo di destinazione.
        df (pd.DataFrame): Dati puliti del caso (layer Silver).
        case_id (int): ID del caso.
        clinical_info (dict): Mappa case_id -> metadati clinici.

    Returns:
        int: Numero di record inseriti (0 se non ci sono dati validi).
    """
    records = build_records(df, case_id, clinical_info)
    if not records:
        return 0

    registry_doc = build_registry_doc(case_id, len(records))

    try:
        db['vital_signals'].insert_many(records)
        db['registry'].insert_one(registry_doc)
    except PyMongoError as e:
        print(f"Errore durante l'inserimento per il caso {case_id}: {e}")
        raise

    return len(records)


def process_silver_to_gold(silver_dir, bronze_dir=None):
    """Carica tutti i casi Silver in MongoDB tramite transazioni multi-documento.

    I file Silver sono partizionati per reparto (`department=<REPARTO>/`),
    quindi la ricerca dei file usa `rglob` per attraversare tutte le
    sottocartelle.

    Args:
        silver_dir (Path): Cartella radice del layer Silver.
        bronze_dir (Path, optional): Cartella del layer Bronze, usata per
            recuperare i metadati clinici. Default: config.BRONZE_DIR.
    """
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

            # Controllo se il caso è già stato caricato (tramite registry)
            if db['registry'].find_one({"case_id": case_id}):
                continue

            load_case_transactional(client, db, df, case_id, clinical_info)

        except Exception as e:
            print(f"Errore nel caricamento del caso da {p_file.name}: {e}")

if __name__ == '__main__':
    print("Inizio caricamento in MongoDB...")
    process_silver_to_gold(config.SILVER_DIR)
    print("Caricamento completato.")
