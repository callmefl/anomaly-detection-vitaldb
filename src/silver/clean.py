"""Script per la pulizia dei dati grezzi dal layer Bronze verso il layer Silver."""

import sys
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import os

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

UNKNOWN_DEPARTMENT = "UNKNOWN"


def load_department_map(bronze_dir):
    """Costruisce una mappa case_id -> reparto (department) dai dati clinici.

    Legge `clinical_data.parquet` (scaricato da `download_clinical_data`) e
    restituisce un dizionario per associare rapidamente ogni caso al proprio
    reparto chirurgico, usato per il partizionamento fisico del layer Silver.

    Args:
        bronze_dir (Path): Cartella del layer Bronze.

    Returns:
        dict: Mappa {case_id (int): department (str)}. Vuota se il file
            clinico non esiste o non contiene le colonne attese.
    """
    clinical_path = bronze_dir / "clinical_data.parquet"
    if not clinical_path.exists():
        print(f"Attenzione: {clinical_path} non trovato, i casi non avranno 'department'.")
        return {}

    df_clinical = pd.read_parquet(clinical_path)
    if "caseid" in df_clinical.columns:
        id_col = "caseid"
    elif "case_id" in df_clinical.columns:
        id_col = "case_id"
    else:
        print("Attenzione: nessuna colonna id caso trovata in clinical_data.parquet.")
        return {}

    if "department" not in df_clinical.columns:
        print("Attenzione: colonna 'department' assente in clinical_data.parquet.")
        return {}

    dept_series = df_clinical.set_index(id_col)["department"]
    return dept_series.to_dict()


def resolve_department(department_map, case_id):
    """Restituisce il reparto per un caso, con fallback a UNKNOWN_DEPARTMENT."""
    dept = department_map.get(case_id)
    if dept is None or (isinstance(dept, float) and pd.isna(dept)):
        return UNKNOWN_DEPARTMENT
    return str(dept)

def load_bronze_case(case_id, bronze_dir):
    """Carica un file Parquet dal layer Bronze.
    
    Args:
        case_id (int): ID del caso.
        bronze_dir (Path): Cartella del layer Bronze.
        
    Returns:
        pd.DataFrame: DataFrame contenente i dati, None se non esiste.
    """
    file_path = bronze_dir / f"case_{case_id}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    return None

def clean_case(df, case_id):
    """Pulisce i dati di un singolo caso.
    
    - Rimuove righe con tutti valori NaN.
    - Interpola piccoli buchi temporali.
    - Applica flag per outlier base fisiologici.
    """
    # Rimuove le righe in cui tutte le tracce vitali sono NaN
    tracks = [c for c in df.columns if c != 'Time']
    df_clean = df.dropna(subset=tracks, how='all').copy()
    
    # Interpolazione lineare su piccoli buchi
    df_clean[tracks] = df_clean[tracks].interpolate(method='linear', limit=5)
    
    # Flag outlier base
    if 'Solar8000/HR' in df_clean.columns:
        df_clean['HR_outlier'] = (df_clean['Solar8000/HR'] < 20) | (df_clean['Solar8000/HR'] > 250)
        
    if 'Solar8000/PLETH_SPO2' in df_clean.columns:
        df_clean['SPO2_outlier'] = (df_clean['Solar8000/PLETH_SPO2'] < 50) | (df_clean['Solar8000/PLETH_SPO2'] > 100)
        
    if 'Solar8000/NIBP_SBP' in df_clean.columns:
        df_clean['SBP_outlier'] = (df_clean['Solar8000/NIBP_SBP'] < 40) | (df_clean['Solar8000/NIBP_SBP'] > 250)

    if 'Solar8000/NIBP_DBP' in df_clean.columns:
        df_clean['DBP_outlier'] = (df_clean['Solar8000/NIBP_DBP'] < 10) | (df_clean['Solar8000/NIBP_DBP'] > 180)

    if 'Solar8000/NIBP_MBP' in df_clean.columns:
        df_clean['MBP_outlier'] = (df_clean['Solar8000/NIBP_MBP'] < 20) | (df_clean['Solar8000/NIBP_MBP'] > 220)

    df_clean['case_id'] = case_id
    return df_clean

def save_silver(df, case_id, silver_dir, department=UNKNOWN_DEPARTMENT):
    """Salva il DataFrame pulito nel layer Silver, partizionato per reparto.

    I file vengono organizzati in sottocartelle `department=<REPARTO>/`,
    permettendo il partition pruning quando si leggono i dati Silver
    filtrando per reparto chirurgico.

    Args:
        df (pd.DataFrame): Dati puliti del caso.
        case_id (int): ID del caso.
        silver_dir (Path): Cartella radice del layer Silver.
        department (str): Reparto chirurgico associato al caso.
    """
    partition_dir = silver_dir / f"department={department}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    output_file = partition_dir / f"case_{case_id}.parquet"
    df.to_parquet(output_file, index=False)

def process_all_cases(bronze_dir, silver_dir):
    """Processa tutti i file Parquet nel layer Bronze."""
    silver_dir.mkdir(parents=True, exist_ok=True)

    department_map = load_department_map(bronze_dir)
    parquet_files = list(bronze_dir.glob("case_*.parquet"))
    
    for p_file in tqdm(parquet_files, desc="Pulizia dati (Bronze -> Silver)"):
        # Estrai case_id dal nome file (es. case_12.parquet -> 12)
        try:
            case_id = int(p_file.stem.split('_')[1])
            df = pd.read_parquet(p_file)
            df_clean = clean_case(df, case_id)
            department = resolve_department(department_map, case_id)
            save_silver(df_clean, case_id, silver_dir, department)
        except Exception as e:
            print(f"Errore durante l'elaborazione di {p_file.name}: {e}")

if __name__ == '__main__':
    print("Inizio elaborazione dati (Layer Silver)...")
    process_all_cases(config.BRONZE_DIR, config.SILVER_DIR)
    print("Elaborazione completata.")
