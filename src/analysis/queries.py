"""Modulo di utility per le query di aggregazione ed analisi sul layer Gold (MongoDB Time Series).

Fornisce funzioni riutilizzabili per:
- Consultare la lista dei casi registrati ed il conteggio dei punti temporali nel catalog `registry`.
- Estrarre la serie temporale di un paziente per la visualizzazione nella dashboard web.
- Eseguire il downsampling temporale efficiente lato database usando `$dateTrunc`.
- Calcolare le statistiche descrittive (media, min, max, stddev) direttamente a livello di MongoDB.
"""

import sys
from pathlib import Path
import pandas as pd
from pymongo import MongoClient

# Setup importazioni dalla radice del progetto
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config


def get_mongo_client():
    """Crea e restituisce il client di connessione PyMongo."""
    return MongoClient(config.MONGO_URI)


def get_db():
    """Restituisce l'istanza del database MongoDB configurato."""
    return get_mongo_client()[config.DB_NAME]


def metric_key(track):
    """Converte il nome di una traccia VitalDB nella chiave corrispondente memorizzata nel documento BSON.

    Args:
        track (str): Nome traccia originale (es. 'Solar8000/HR').

    Returns:
        str: Chiave sanificata per MongoDB (es. 'Solar8000_HR').
    """
    return track.replace('/', '_')


def metric_keys():
    """Restituisce la lista di tutte le chiavi sanificate dei parametri vitali configurati."""
    return [metric_key(t) for t in config.VITAL_TRACKS]


def list_loaded_cases(db):
    """Restituisce l'elenco di tutti i casi clinici caricati, consultando la collezione `registry`.

    Args:
        db: Istanza PyMongo del database.

    Returns:
        pd.DataFrame: Tabella dei casi registrati con `case_id`, `record_count`, `schema_version`, `provenance`.
    """
    cursor = db['registry'].find({}, {"_id": 0}).sort("case_id", 1)
    return pd.DataFrame(list(cursor))


def count_points_by_case(db):
    """Calcola il numero effettivo di misurazioni per ciascun caso nella collezione `vital_signals`."""
    pipeline = [
        {"$group": {"_id": "$metadata.case_id", "points": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    rows = [
        {"case_id": d["_id"], "points": d["points"]}
        for d in db['vital_signals'].aggregate(pipeline)
    ]
    return pd.DataFrame(rows)


def get_case_series(db, case_id, tracks=None):
    """Estrae l'intera serie temporale di un caso dal layer Gold ordinata per timestamp.

    Args:
        db: Istanza PyMongo del database.
        case_id (int): ID del caso.
        tracks (list, optional): Sottoinsieme di tracce da estrarre (default: tutte).

    Returns:
        pd.DataFrame: DataFrame contenente la colonna `timestamp` e le metriche vitali.
    """
    keys = metric_keys() if tracks is None else [metric_key(t) for t in tracks]
    projection = {"_id": 0, "timestamp": 1}
    for k in keys:
        projection[f"metrics.{k}"] = 1

    cursor = db['vital_signals'].find(
        {"metadata.case_id": case_id},
        projection,
    ).sort("timestamp", 1)

    rows = []
    for doc in cursor:
        row = {"timestamp": doc["timestamp"]}
        row.update(doc.get("metrics", {}))
        rows.append(row)

    df = pd.DataFrame(rows)
    for k in keys:
        if k not in df.columns:
            df[k] = pd.NA
    return df


def summary_stats(db, case_id, tracks=None):
    """Calcola le statistiche descrittive (conteggio, media, min, max, deviazione standard) via aggregazione MongoDB."""
    keys = metric_keys() if tracks is None else [metric_key(t) for t in tracks]

    group = {"_id": None}
    for k in keys:
        field = f"$metrics.{k}"
        group[f"{k}__count"] = {"$sum": {"$cond": [{"$ne": [field, None]}, 1, 0]}}
        group[f"{k}__avg"] = {"$avg": field}
        group[f"{k}__min"] = {"$min": field}
        group[f"{k}__max"] = {"$max": field}
        group[f"{k}__std"] = {"$stdDevPop": field}

    pipeline = [
        {"$match": {"metadata.case_id": case_id}},
        {"$group": group},
    ]
    result = list(db['vital_signals'].aggregate(pipeline))
    if not result:
        return pd.DataFrame(columns=["track", "count", "avg", "min", "max", "std"])

    agg = result[0]
    rows = []
    for k in keys:
        rows.append({
            "track": k,
            "count": agg.get(f"{k}__count"),
            "avg": agg.get(f"{k}__avg"),
            "min": agg.get(f"{k}__min"),
            "max": agg.get(f"{k}__max"),
            "std": agg.get(f"{k}__std"),
        })
    return pd.DataFrame(rows)


def downsample_case(db, case_id, window_seconds=60, tracks=None):
    """Esegue l'aggregazione della serie temporale in finestre di ampiezza `window_seconds` sfruttando `$dateTrunc`.

    Questo downsampling viene eseguito interamente all'interno del motore MongoDB, riducendo il traffico
    di rete verso l'API e rendendo l'interfaccia utente fluida.
    """
    keys = metric_keys() if tracks is None else [metric_key(t) for t in tracks]

    group = {
        "_id": {
            "$dateTrunc": {
                "date": "$timestamp",
                "unit": "second",
                "binSize": int(window_seconds),
            }
        }
    }
    for k in keys:
        group[k] = {"$avg": f"$metrics.{k}"}

    pipeline = [
        {"$match": {"metadata.case_id": case_id}},
        {"$group": group},
        {"$sort": {"_id": 1}},
    ]

    rows = []
    for doc in db['vital_signals'].aggregate(pipeline):
        row = {"window_start": doc["_id"]}
        for k in keys:
            row[k] = doc.get(k)
        rows.append(row)
    return pd.DataFrame(rows)


if __name__ == '__main__':
    db = get_db()
    print("=== TEST QUERY MONGODB GOLD ===")
    print("Casi registrati:")
    print(list_loaded_cases(db).to_string(index=False))
