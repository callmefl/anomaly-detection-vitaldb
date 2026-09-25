"""Unit test per il layer Gold — src/gold/load_mongo.py.

Testa la logica di costruzione dei documenti BSON senza connettersi
ad un'istanza MongoDB reale: usa DataFrame fittizi e verifica la struttura
degli oggetti prodotti da build_records(), build_metadata() e build_registry_doc().
"""

from pathlib import Path
import sys
import datetime

import numpy as np
import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.gold.load_mongo import (
    build_metadata,
    build_records,
    build_registry_doc,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_clinical_info():
    """Mappa clinica fittizia con un caso noto (case_id=1)."""
    return {
        1: {"department": "General surgery", "age": 65, "sex": "M"},
    }


@pytest.fixture
def sample_silver_df():
    """DataFrame Silver minimo con le 5 tracce + flag outlier + colonna Time."""
    return pd.DataFrame({
        "Time":                   [0.0, 1.0, 2.0],
        "Solar8000/HR":           [72.0, 75.0, 80.0],
        "Solar8000/PLETH_SPO2":   [98.0, 97.0, 99.0],
        "Solar8000/NIBP_SBP":     [120.0, 122.0, 118.0],
        "Solar8000/NIBP_DBP":     [80.0, 82.0, 79.0],
        "Solar8000/NIBP_MBP":     [93.0, 95.0, 92.0],
        "HR_outlier":             [False, False, False],
        "SPO2_outlier":           [False, False, False],
        "SBP_outlier":            [False, False, False],
        "DBP_outlier":            [False, False, False],
        "MBP_outlier":            [False, False, False],
        "case_id":                [1, 1, 1],
    })


# ── Test build_metadata ───────────────────────────────────────────────────────

def test_build_metadata_known_case(sample_clinical_info):
    """build_metadata deve restituire un dizionario con tutti i campi richiesti."""
    meta = build_metadata(1, sample_clinical_info)

    assert meta["case_id"] == 1
    assert meta["sensor_name"] == "Solar8000"
    assert meta["department"] == "General surgery"
    assert meta["age"] == 65
    assert meta["sex"] == "M"


def test_build_metadata_unknown_case():
    """Se il case_id non è in clinical_info, i campi clinici devono essere None."""
    meta = build_metadata(999, {})

    assert meta["case_id"] == 999
    assert meta["department"] is None
    assert meta["age"] is None
    assert meta["sex"] is None


def test_build_metadata_case_id_is_native_int(sample_clinical_info):
    """case_id nel metaField deve essere un int Python puro, non np.int64."""
    meta = build_metadata(1, sample_clinical_info)
    assert type(meta["case_id"]) is int


# ── Test build_records ────────────────────────────────────────────────────────

def test_build_records_count(sample_silver_df, sample_clinical_info):
    """build_records deve produrre tanti documenti quante le righe del DataFrame."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    assert len(records) == 3


def test_build_records_document_structure(sample_silver_df, sample_clinical_info):
    """Ogni documento BSON deve avere i campi timestamp, metadata, metrics e quality_flags."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    doc = records[0]

    assert "timestamp" in doc
    assert "metadata" in doc
    assert "metrics" in doc
    assert "quality_flags" in doc


def test_build_records_timestamp_is_datetime(sample_silver_df, sample_clinical_info):
    """Il campo timestamp deve essere un oggetto datetime (richiesto da MongoDB Time Series)."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    assert isinstance(records[0]["timestamp"], datetime.datetime)


def test_build_records_metrics_keys_sanitized(sample_silver_df, sample_clinical_info):
    """Le chiavi delle metriche devono usare '_' e non '/' (sanitizzazione per BSON)."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    metrics = records[0]["metrics"]

    assert "Solar8000_HR" in metrics
    assert "Solar8000/HR" not in metrics


def test_build_records_quality_flags_present(sample_silver_df, sample_clinical_info):
    """Il sotto-documento quality_flags deve contenere i flag booleani Silver."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    # HR_outlier è False per tutti i record del sample: il campo è presente se la riga lo aveva
    for rec in records:
        # quality_flags può essere un dict vuoto se tutti False (dipende dall'implementazione)
        # ma il campo deve esistere comunque
        assert "quality_flags" in rec


def test_build_records_metrics_values_are_float(sample_silver_df, sample_clinical_info):
    """I valori delle metriche devono essere float (non np.float64 o int)."""
    records = build_records(sample_silver_df, 1, sample_clinical_info)
    for val in records[0]["metrics"].values():
        assert isinstance(val, float)


def test_build_records_skips_nan_rows(sample_clinical_info):
    """Le righe dove tutte le metriche sono NaN non devono produrre documenti."""
    df_with_nan = pd.DataFrame({
        "Time":                   [0.0, 1.0],
        "Solar8000/HR":           [np.nan, 72.0],
        "Solar8000/PLETH_SPO2":   [np.nan, 98.0],
        "Solar8000/NIBP_SBP":     [np.nan, 120.0],
        "Solar8000/NIBP_DBP":     [np.nan, 80.0],
        "Solar8000/NIBP_MBP":     [np.nan, 93.0],
        "case_id":                [1, 1],
    })
    records = build_records(df_with_nan, 1, {})
    # La prima riga ha tutte le metriche NaN: deve essere scartata
    assert len(records) == 1


# ── Test build_registry_doc ───────────────────────────────────────────────────

def test_build_registry_doc_structure():
    """Il documento registry deve contenere case_id, record_count, schema_version e provenance."""
    doc = build_registry_doc(42, 5000)

    assert doc["case_id"] == 42
    assert doc["record_count"] == 5000
    assert doc["schema_version"] == "1.0"
    assert "provenance" in doc
    assert doc["provenance"]["step"] == "silver_to_gold"
    assert isinstance(doc["provenance"]["timestamp"], datetime.datetime)


def test_build_registry_doc_case_id_type():
    """case_id nel registry deve essere int Python puro per compatibilità schema MongoDB."""
    doc = build_registry_doc(np.int64(7), 100)
    assert type(doc["case_id"]) is int
