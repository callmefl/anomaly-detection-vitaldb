"""Unit test per il modulo di Data Cleaning ed ETL (src/silver/clean.py)."""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.silver.clean import clean_case, resolve_department, UNKNOWN_DEPARTMENT


def test_resolve_department():
    """Verifica il recupero del reparto chirurgico con fallback 'UNKNOWN'."""
    dept_map = {1: "General Surgery", 2: "Cardiac Surgery"}
    
    assert resolve_department(dept_map, 1) == "General Surgery"
    assert resolve_department(dept_map, 2) == "Cardiac Surgery"
    assert resolve_department(dept_map, 99) == UNKNOWN_DEPARTMENT


def test_clean_case():
    """Verifica la bonifica, l'interpolazione e la marcatura degli outlier fisiologici."""
    df = pd.DataFrame({
        "Time": [0, 1, 2, 3, 4],
        "Solar8000/HR": [70.0, np.nan, 80.0, 15.0, 300.0],  # 15 e 300 sono outlier fisiologici
        "Solar8000/PLETH_SPO2": [98.0, 98.0, 98.0, 40.0, 98.0],  # 40 è outlier (<50)
        "Solar8000/NIBP_SBP": [120.0, 120.0, 120.0, 120.0, 120.0]
    })

    cleaned = clean_case(df, case_id=1)

    assert cleaned["case_id"].iloc[0] == 1
    assert cleaned["Solar8000/HR"].iloc[1] == 75.0  # Interpolato linearmente tra 70 e 80
    assert cleaned["HR_outlier"].iloc[3] == True   # 15 < 20
    assert cleaned["HR_outlier"].iloc[4] == True   # 300 > 250
    assert cleaned["SPO2_outlier"].iloc[3] == True # 40 < 50
