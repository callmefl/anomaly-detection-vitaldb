"""Unit test per il modulo Gold (src/gold/load_mongo.py) e Data Governance."""

import datetime
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.gold.load_mongo import (
    build_metadata,
    build_records,
    build_registry_doc,
    init_track_metadata,
    load_case_to_mongo,
)


def test_build_metadata():
    """Verifica la corretta generazione del sotto-documento metadata."""
    clinical_info = {
        1: {"department": "General surgery", "age": 65, "sex": "M"},
        2: {"department": None, "age": None, "sex": None},
    }

    meta1 = build_metadata(1, clinical_info)
    assert meta1["case_id"] == 1
    assert meta1["sensor_name"] == "Solar8000"
    assert meta1["department"] == "General surgery"
    assert meta1["age"] == 65
    assert meta1["sex"] == "M"

    meta2 = build_metadata(2, clinical_info)
    assert meta2["case_id"] == 2
    assert meta2["department"] is None
    assert meta2["age"] is None


def test_build_records_with_quality_flags():
    """Verifica che i record Gold contengano sia le metriche sia i flag di qualità Silver."""
    df_silver = pd.DataFrame({
        "Time": [0.0, 1.0],
        "Solar8000/HR": [75.0, 18.0],
        "Solar8000/PLETH_SPO2": [98.0, 45.0],
        "Solar8000/NIBP_SBP": [120.0, 115.0],
        "HR_outlier": [False, True],
        "SPO2_outlier": [False, True],
        "SBP_outlier": [False, False],
    })

    clinical_info = {10: {"department": "ICU", "age": 70, "sex": "F"}}
    records = build_records(df_silver, case_id=10, clinical_info=clinical_info)

    assert len(records) == 2

    # Verifica il primo record (fisiologico)
    rec0 = records[0]
    assert rec0["metadata"]["case_id"] == 10
    assert rec0["metrics"]["Solar8000_HR"] == 75.0
    assert rec0["quality_flags"]["HR_outlier"] is False
    assert rec0["quality_flags"]["SPO2_outlier"] is False
    assert rec0["timestamp"].tzinfo == datetime.timezone.utc

    # Verifica il secondo record (con outlier Silver propagati)
    rec1 = records[1]
    assert rec1["metrics"]["Solar8000_HR"] == 18.0
    assert rec1["quality_flags"]["HR_outlier"] is True
    assert rec1["quality_flags"]["SPO2_outlier"] is True


def test_build_registry_doc():
    """Verifica la struttura e i metadati di Data Governance del catalogo registry."""
    quality_summary = {"HR_outlier": 5, "SPO2_outlier": 2}
    doc = build_registry_doc(case_id=42, record_count=1000, quality_summary=quality_summary)

    assert doc["case_id"] == 42
    assert doc["record_count"] == 1000
    assert doc["schema_version"] == "1.0"
    assert "provenance" in doc
    assert doc["provenance"]["step"] == "silver_to_gold"
    assert isinstance(doc["provenance"]["timestamp"], datetime.datetime)
    assert doc["quality_summary"] == quality_summary


def test_load_case_to_mongo_transactional_mock():
    """Verifica che load_case_to_mongo utilizzi session e transazioni ACID multi-documento."""
    mock_client = MagicMock()
    mock_session = MagicMock()
    # Configura il context manager per start_session e start_transaction
    mock_client.start_session.return_value.__enter__.return_value = mock_session
    mock_session.start_transaction.return_value.__enter__.return_value = None

    mock_db = MagicMock()

    df_silver = pd.DataFrame({
        "Time": [0.0],
        "Solar8000/HR": [80.0],
        "HR_outlier": [False],
    })

    clinical_info = {1: {"department": "General surgery", "age": 50, "sex": "M"}}

    count = load_case_to_mongo(mock_client, mock_db, df_silver, case_id=1, clinical_info=clinical_info)

    assert count == 1
    mock_client.start_session.assert_called_once()
    mock_session.start_transaction.assert_called_once()
    mock_db["vital_signals"].insert_many.assert_called_once()
    mock_db["registry"].insert_one.assert_called_once()
