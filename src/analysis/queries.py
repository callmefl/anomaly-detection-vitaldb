"""Utility di analisi per interrogare il layer Gold (MongoDB Time Series Collections).

Questo modulo raccoglie query e aggregazioni riutilizzabili sulla collezione
`vital_signals` e sul `registry`. Le funzioni sono pensate per essere usate
sia in fase esplorativa (notebook/REPL) sia a monte dell'anomaly detection,
sfruttando le aggregazioni native di MongoDB anziché scaricare tutto lato client.

Convenzioni sui dati (coerenti con src/gold/load_mongo.py):
- I documenti hanno `timestamp`, `metadata.case_id` e un sotto-documento `metrics`.
- Le chiavi delle metriche derivano da config.VITAL_TRACKS sostituendo '/' con '_'
  (es. 'Solar8000/HR' -> 'Solar8000_HR').
"""

import sys
from pathlib import Path
import pandas as pd
from pymongo import MongoClient

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config


def get_mongo_client():
    """Restituisce una connessione al client MongoDB."""
    return MongoClient(config.MONGO_URI)


def get_db():
    """Restituisce l'oggetto database configurato."""
    return get_mongo_client()[config.DB_NAME]


def metric_key(track):
    """Converte un nome traccia VitalDB nella chiave usata dentro `metrics`.

    Args:
        track (str): Nome traccia, es. 'Solar8000/HR'.

    Returns:
        str: Chiave metrica sanificata, es. 'Solar8000_HR'.
    """
    return track.replace('/', '_')


def metric_keys():
    """Restituisce le chiavi metrica per tutte le tracce in config.VITAL_TRACKS."""
    return [metric_key(t) for t in config.VITAL_TRACKS]


def list_loaded_cases(db):
    """Elenca i casi già caricati nel layer Gold usando il registry.

    Args:
        db: Oggetto database pymongo.

    Returns:
        pd.DataFrame: Righe del registry (case_id, record_count, provenance, ...).
    """
    cursor = db['registry'].find({}, {"_id": 0}).sort("case_id", 1)
    return pd.DataFrame(list(cursor))


def count_points_by_case(db):
    """Conta i punti temporali memorizzati per ciascun caso.

    Utile per un controllo di coerenza rispetto a `registry.record_count`.

    Args:
        db: Oggetto database pymongo.

    Returns:
        pd.DataFrame: Colonne ['case_id', 'points'] ordinate per case_id.
    """
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
    """Estrae la serie temporale di un caso come DataFrame.

    Args:
        db: Oggetto database pymongo.
        case_id (int): ID del caso.
        tracks (list, optional): Sottoinsieme di tracce VitalDB da estrarre.
            Se None usa tutte quelle in config.VITAL_TRACKS.

    Returns:
        pd.DataFrame: Colonne ['timestamp', <chiavi metrica>] ordinate per tempo.
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
    # Garantisce la presenza di tutte le colonne richieste anche se assenti
    for k in keys:
        if k not in df.columns:
            df[k] = pd.NA
    return df


def summary_stats(db, case_id, tracks=None):
    """Calcola statistiche descrittive per traccia via aggregazione MongoDB.

    Args:
        db: Oggetto database pymongo.
        case_id (int): ID del caso.
        tracks (list, optional): Tracce da analizzare (default: tutte).

    Returns:
        pd.DataFrame: Righe per traccia con count/avg/min/max/stddev.
    """
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
    """Aggrega la serie in finestre temporali (media per finestra).

    Sfrutta $dateTrunc per un downsampling efficiente lato database, utile per
    visualizzazioni o per ridurre il rumore prima dell'anomaly detection.

    Args:
        db: Oggetto database pymongo.
        case_id (int): ID del caso.
        window_seconds (int): Ampiezza della finestra in secondi.
        tracks (list, optional): Tracce da aggregare (default: tutte).

    Returns:
        pd.DataFrame: Colonne ['window_start', <chiavi metrica>] ordinate per tempo.
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

    print("=== Casi caricati (registry) ===")
    print(list_loaded_cases(db).to_string(index=False))

    cases = count_points_by_case(db)
    if cases.empty:
        print("\nNessun dato presente in 'vital_signals'.")
    else:
        first_case = int(cases.iloc[0]["case_id"])
        print(f"\n=== Statistiche descrittive (case_id={first_case}) ===")
        print(summary_stats(db, first_case).to_string(index=False))

        print(f"\n=== Downsampling a finestre di 60s (case_id={first_case}) ===")
        print(downsample_case(db, first_case, window_seconds=60).head().to_string(index=False))
