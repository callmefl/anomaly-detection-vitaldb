"""Unit test per il modulo di Data Cleaning ed ETL (src/silver/clean.py)."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.silver.clean import clean_case, resolve_department, UNKNOWN_DEPARTMENT, interpolate_short_gaps


def test_resolve_department():
    """Verifica il recupero del reparto chirurgico con fallback 'UNKNOWN'."""
    dept_map = {1: "General Surgery", 2: "Cardiac Surgery"}
    
    assert resolve_department(dept_map, 1) == "General Surgery"
    assert resolve_department(dept_map, 2) == "Cardiac Surgery"
    assert resolve_department(dept_map, 99) == UNKNOWN_DEPARTMENT


def test_interpolate_short_gaps():
    """Verifica l'interpolazione selettiva: buchi <= 5s interpolati, buchi > 5s o periferici intatti."""
    # Serie con buco corto (3 NaN), buco lungo (6 NaN), leading (1 NaN) e trailing (1 NaN)
    s = pd.Series([
        np.nan,          # 0: leading NaN -> non interpolare
        10.0,            # 1
        np.nan, np.nan, np.nan,  # 2, 3, 4: gap di 3 campioni (<= 5) -> interpolare
        20.0,            # 5
        np.nan, np.nan, np.nan, np.nan, np.nan, np.nan,  # 6-11: gap di 6 campioni (> 5) -> preservare NaN
        50.0,            # 12
        np.nan           # 13: trailing NaN -> non interpolare
    ])

    interpolated, imputed = interpolate_short_gaps(s, max_gap=5)

    # Leading e trailing non toccati
    assert pd.isna(interpolated.iloc[0])
    assert not imputed.iloc[0]
    assert pd.isna(interpolated.iloc[13])
    assert not imputed.iloc[13]

    # Gap corto interpolato correttamente
    assert interpolated.iloc[2:5].notna().all()
    assert imputed.iloc[2:5].all()
    assert interpolated.iloc[3] == 15.0

    # Gap lungo lasciato a NaN
    assert interpolated.iloc[6:12].isna().all()
    assert not imputed.iloc[6:12].any()


def test_clean_case():
    """Verifica la bonifica, l'interpolazione e la marcatura degli outlier fisiologici da TRACK_SPECS."""
    df = pd.DataFrame({
        "Time": [0, 1, 2, 3, 4],
        "Solar8000/HR": [70.0, np.nan, 80.0, 15.0, 300.0],  # 15 e 300 sono outlier fisiologici (<20 o >250)
        "Solar8000/PLETH_SPO2": [98.0, 98.0, 98.0, 40.0, 98.0],  # 40 è outlier (<50)
        "Solar8000/NIBP_SBP": [120.0, 120.0, 120.0, 120.0, 120.0],
        "Solar8000/NIBP_DBP": [80.0, 80.0, 80.0, 190.0, 80.0]  # 190 è outlier da TRACK_SPECS (>180)
    })

    cleaned = clean_case(df, case_id=1)

    assert cleaned["case_id"].iloc[0] == 1
    assert cleaned["Solar8000/HR"].iloc[1] == 75.0  # Interpolato linearmente tra 70 e 80
    assert "HR_imputed" in cleaned.columns
    assert cleaned["HR_imputed"].iloc[1] == True
    assert cleaned["HR_imputed"].iloc[0] == False

    assert "SPO2_imputed" in cleaned.columns
    assert cleaned["HR_outlier"].iloc[3] == True   # 15 < 20
    assert cleaned["HR_outlier"].iloc[4] == True   # 300 > 250
    assert cleaned["SPO2_outlier"].iloc[3] == True # 40 < 50
    assert cleaned["DBP_outlier"].iloc[3] == True  # 190 > 180 (da TRACK_SPECS)
    assert "nibp_age_s" in cleaned.columns

