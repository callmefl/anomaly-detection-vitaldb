"""Unit test per il modulo di Ingestione Bronze (src/bronze/download.py)."""

import json
from pathlib import Path
import sys
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.bronze.download import download_case, download_clinical_data, download_lab_data


def test_download_case_skips_existing(tmp_path):
    """Verifica che download_case salti i file già scaricati e non vuoti."""
    fake_case_file = tmp_path / "case_42.parquet"
    df = pd.DataFrame({"Solar8000/HR": [70, 72], "Time": [0.0, 1.0]})
    df.to_parquet(fake_case_file, index=False)

    res = download_case(42, ["Solar8000/HR"], 1.0, tmp_path)
    assert res["status"] == "skipped_existing"
    assert res["case_id"] == 42


def test_download_clinical_data_raises_on_failure(tmp_path):
    """Verifica che un fallimento totale nel download dei dati clinici sollevi eccezione esplicita."""
    mock_vitaldb = MagicMock()
    mock_vitaldb.load_clinical_data.side_effect = Exception("SDK error")
    with patch("pandas.read_csv", side_effect=Exception("Network error")):
        with patch("src.bronze.download.vitaldb", mock_vitaldb):
            with patch("src.bronze.download._VITALDB_AVAILABLE", True):
                with pytest.raises(RuntimeError, match="Errore irreversibile nel download dei dati clinici"):
                    download_clinical_data(tmp_path)


def test_download_lab_data_graceful_fallback(tmp_path):
    """Verifica che download_lab_data gestisca il fallback senza bloccare la pipeline se lab non è accessibile."""
    mock_vitaldb = MagicMock()
    mock_vitaldb.load_lab_data.side_effect = Exception("No lab data")
    with patch("pandas.read_csv", side_effect=Exception("REST 404")):
        with patch("src.bronze.download.vitaldb", mock_vitaldb):
            with patch("src.bronze.download._VITALDB_AVAILABLE", True):
                ok = download_lab_data(tmp_path, case_ids=[1, 2])
                assert ok is False
