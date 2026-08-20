"""Unit test per il modulo di Anomaly Detection src/detection/detector.py."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.detection.detector import (
    compute_shock_index,
    compute_severe_hypotension,
    apply_clinical_rules,
    detect_isolation_forest,
    AutoencoderDetector
)


def test_compute_shock_index():
    """Verifica il calcolo dello Shock Index (HR / SBP > 0.9)."""
    df = pd.DataFrame({
        "Solar8000_HR": [100.0, 60.0],
        "Solar8000_NIBP_SBP": [100.0, 120.0],  # 100/100 = 1.0 (Anomalia Shock Index > 0.9)
    })

    res = compute_shock_index(df)

    assert "shock_index" in res.columns
    assert res["shock_index"].iloc[0] == 1.0
    assert res["shock_index_anomaly"].iloc[0] == True
    assert res["shock_index_anomaly"].iloc[1] == False


def test_compute_severe_hypotension():
    """Verifica il calcolo dell'Ipotensione Severa (MBP < 65 & SpO2 < 90%)."""
    df = pd.DataFrame({
        "Solar8000_NIBP_MBP": [50.0, 90.0],
        "Solar8000_PLETH_SPO2": [85.0, 98.0]
    })

    res = compute_severe_hypotension(df)

    assert "severe_hypotension_anomaly" in res.columns
    assert res["severe_hypotension_anomaly"].iloc[0] == True
    assert res["severe_hypotension_anomaly"].iloc[1] == False


def test_detect_isolation_forest():
    """Verifica l'esecuzione di Isolation Forest su dati fittizi."""
    np.random.seed(42)
    data = np.random.normal(loc=100, scale=5, size=(100, 5))
    outlier = np.array([[300.0, 10.0, 10.0, 10.0, 10.0]])
    data = np.vstack([data, outlier])

    df = pd.DataFrame(data, columns=[
        "Solar8000_HR", "Solar8000_PLETH_SPO2", "Solar8000_NIBP_SBP", "Solar8000_NIBP_DBP", "Solar8000_NIBP_MBP"
    ])

    preds = detect_isolation_forest(df, contamination=0.05)

    assert isinstance(preds, np.ndarray)
    assert preds[-1] == True  # L'outlier deve essere rilevato


def test_autoencoder_detector():
    """Verifica l'esecuzione dell'Autoencoder Neurale MLPRegressor su dati fittizi."""
    np.random.seed(42)
    data = np.random.normal(loc=80, scale=2, size=(100, 5))
    outlier = np.array([[500.0, 1.0, 1.0, 1.0, 1.0]])
    data = np.vstack([data, outlier])

    feature_cols = ["Solar8000_HR", "Solar8000_PLETH_SPO2", "Solar8000_NIBP_SBP", "Solar8000_NIBP_DBP", "Solar8000_NIBP_MBP"]
    df = pd.DataFrame(data, columns=feature_cols)

    detector = AutoencoderDetector(percentile=95.0, max_iter=200)
    preds = detector.fit_predict(df, feature_cols)

    assert isinstance(preds, np.ndarray)
    assert preds[-1] == True  # L'outlier deve superare il 95° percentile MSE
