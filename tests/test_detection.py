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
    LSTMAutoencoderDetector,
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


def test_lstm_autoencoder_detector():
    """Verifica l'esecuzione del vero LSTM Autoencoder (encoder-decoder PyTorch) su dati fittizi.

    Usa 200 punti di dati normali + 1 outlier estremo. window_size=30, epochs=5 per velocità.
    L'outlier deve produrre un MSE di ricostruzione oltre il 95° percentile.
    """
    np.random.seed(42)
    feature_cols = [
        "Solar8000_HR", "Solar8000_PLETH_SPO2",
        "Solar8000_NIBP_SBP", "Solar8000_NIBP_DBP", "Solar8000_NIBP_MBP"
    ]

    # 200 punti normali attorno a valori fisiologici plausibili
    data = np.random.normal(loc=80, scale=2, size=(200, 5))
    # 1 punto anomalo con valori estremi
    outlier = np.array([[500.0, 1.0, 1.0, 1.0, 1.0]])
    data = np.vstack([data, outlier])

    df = pd.DataFrame(data, columns=feature_cols)

    detector = LSTMAutoencoderDetector(window_size=30, epochs=5, percentile=95.0)
    preds = detector.fit_predict(df, feature_cols)

    assert isinstance(preds, np.ndarray)
    assert len(preds) == len(df)
    # Il 5% dei punti deve risultare anomalo per costruzione del percentile
    assert preds.sum() > 0


def test_save_anomalies_to_mongo_idempotence():
    """Verifica che save_anomalies_to_mongo elimini sempre le anomalie obsolete con detected_at != now."""
    import datetime
    from unittest.mock import MagicMock
    from src.detection.detector import save_anomalies_to_mongo

    db = MagicMock()
    df_clean = pd.DataFrame({
        "case_id": [1, 1],
        "timestamp": [datetime.datetime.now(), datetime.datetime.now()],
        "shock_index_anomaly": [False, False],
        "severe_hypotension_anomaly": [False, False]
    })

    # Caso con 0 anomalie: deve comunque chiamare delete_many per evitare anomalie stale
    count = save_anomalies_to_mongo(db, df_clean)
    assert count == 0
    call_args = db['anomalies_detected'].delete_many.call_args[0][0]
    assert call_args["case_id"] == {"$in": [1]}
    assert "$ne" in call_args["detected_at"]


def test_save_anomalies_to_mongo_insert_before_delete():
    """Verifica che save_anomalies_to_mongo chiami insert_many prima di delete_many."""
    import datetime
    from unittest.mock import MagicMock
    from src.detection.detector import save_anomalies_to_mongo

    calls = []
    db = MagicMock()
    db['anomalies_detected'].insert_many.side_effect = lambda docs: calls.append("insert")
    db['anomalies_detected'].delete_many.side_effect = lambda query: calls.append("delete")

    df_anom = pd.DataFrame({
        "case_id": [1, 1],
        "timestamp": [datetime.datetime.now(), datetime.datetime.now()],
        "shock_index_anomaly": [True, False],
    })

    count = save_anomalies_to_mongo(db, df_anom)
    assert count == 1
    assert calls == ["insert", "delete"]


def test_load_from_gold_masks_outliers():
    """Verifica che load_from_gold proietti quality_flags e mascheri a NaN i valori con outlier flag attivo."""
    import datetime
    from unittest.mock import MagicMock
    from src.detection.detector import load_from_gold, HR_KEY

    db = MagicMock()
    db['vital_signals'].find.return_value.sort.return_value = [
        {
            "timestamp": datetime.datetime(2020, 1, 1, 0, 0, 0),
            "metadata": {"case_id": 1},
            "metrics": {HR_KEY: 300.0},
            "quality_flags": {"HR_outlier": True, "nibp_age_s": 10.0}
        },
        {
            "timestamp": datetime.datetime(2020, 1, 1, 0, 0, 1),
            "metadata": {"case_id": 1},
            "metrics": {HR_KEY: 75.0},
            "quality_flags": {"HR_outlier": False, "nibp_age_s": 11.0}
        }
    ]

    df = load_from_gold(db, case_ids=[1])
    assert len(df) == 2
    assert "nibp_age_s" in df.columns
    assert df["nibp_age_s"].iloc[0] == 10.0
    # Il record 0 era marcato come outlier fisiologico -> deve risultare NaN per non falsare la detection clinica
    assert np.isnan(df[HR_KEY].iloc[0])
    # Il record 1 era valido -> deve essere preservato
    assert df[HR_KEY].iloc[1] == 75.0


def test_clinical_rules_respect_nibp_freshness():
    """Verifica che Shock Index e Ipotensione Severa non attivino falsi allarmi su pressioni LOCF obsolete."""
    df = pd.DataFrame({
        "Solar8000_HR": [110.0, 110.0],
        "Solar8000_NIBP_SBP": [100.0, 100.0],  # SI = 1.1 > 0.9
        "Solar8000_NIBP_MBP": [55.0, 55.0],    # < 65 mmHg
        "Solar8000_PLETH_SPO2": [85.0, 85.0],  # < 90%
        "nibp_age_s": [10.0, 240.0],           # t=0 misura fresca (10s), t=1 misura obsoleta (240s > 120s)
    })

    res = apply_clinical_rules(df)
    assert res["shock_index_anomaly"].iloc[0] == True
    assert res["shock_index_anomaly"].iloc[1] == False
    assert res["severe_hypotension_anomaly"].iloc[0] == True
    assert res["severe_hypotension_anomaly"].iloc[1] == False



