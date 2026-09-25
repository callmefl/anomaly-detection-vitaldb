"""Modulo per la pulizia, la bonifica ed il partizionamento dei dati (Layer Silver).

Il layer Silver costituisce la seconda fase della Medallion Architecture:
- Rimuove i record totalmente vuoti (con tutti i parametri biometrici a NaN).
- Effettua l'interpolazione lineare su brevi buchi temporali di misurazione (fino a 5 secondi contigui).
- Etichetta gli outlier fisiologicamente impossibili tramite flag booleani dominio-specifici.
- Organizza ed arricchisce i file Parquet partizionandoli fisicamente in sottodirectory basate sul reparto chirurgico (`department=<REPARTO>`).
"""

import sys
import os
import json
import datetime
from pathlib import Path
import pandas as pd
from tqdm import tqdm

# Setup importazioni dalla radice del progetto
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Costante per identificare i casi privi di indicazione sul reparto chirurgico
UNKNOWN_DEPARTMENT = "UNKNOWN"


def load_department_map(bronze_dir):
    """Costruisce una mappa hash `case_id -> department` partendo dal file dei dati clinici.

    Legge `clinical_data.parquet` scaricato nel layer Bronze per associare ad ogni paziente
    il relativo reparto chirurgico (es. General surgery, Cardiac surgery, ICU).

    Args:
        bronze_dir (Path): Cartella del layer Bronze.

    Returns:
        dict: Mappa `{case_id (int): department (str)}`.
    """
    clinical_path = bronze_dir / "clinical_data.parquet"
    if not clinical_path.exists():
        print(f"⚠️ Attenzione: {clinical_path} non trovato nel Bronze. I casi verranno partizionati sotto 'UNKNOWN'.")
        return {}

    df_clinical = pd.read_parquet(clinical_path)
    if "caseid" in df_clinical.columns:
        id_col = "caseid"
    elif "case_id" in df_clinical.columns:
        id_col = "case_id"
    else:
        print("⚠️ Attenzione: Nessuna colonna di identificazione del caso trovata in clinical_data.parquet.")
        return {}

    if "department" not in df_clinical.columns:
        print("⚠️ Attenzione: Colonna 'department' assente nei dati clinici.")
        return {}

    dept_map = {}
    for _, row in df_clinical.iterrows():
        try:
            cid = int(row[id_col])
            dept = row["department"]
            if pd.notna(dept) and str(dept).strip():
                dept_map[cid] = str(dept).strip()
        except (ValueError, TypeError):
            continue
    return dept_map


def resolve_department(department_map, case_id):
    """Restituisce il nome del reparto associato ad un caso, applicando il valore di fallback 'UNKNOWN'."""
    dept = department_map.get(case_id)
    if dept is None or (isinstance(dept, float) and pd.isna(dept)):
        return UNKNOWN_DEPARTMENT
    clean_str = str(dept).strip()
    return clean_str if clean_str else UNKNOWN_DEPARTMENT


def load_bronze_case(case_id, bronze_dir):
    """Legge il file Parquet grezzo di un caso dal layer Bronze."""
    file_path = bronze_dir / f"case_{case_id}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    return None


def clean_case(df, case_id):
    """Esegue la bonifica ed il filtraggio di Data Quality sui tracciati temporali del caso.

    Fasi di trasformazione:
    1. Scarta le righe in cui tutte le tracce vitali sono nulle contemporaneamente.
    2. Interpola linearmente le piccole interruzioni di segnale (fino a 5 valori consecutivi).
    3. Calcola i flag booleani per identificare eventuali outlier fuori dai range fisiologici.
    """
    # 1. Filtra le righe completamente vuote sulle metriche vitali
    tracks = [c for c in df.columns if c != 'Time']
    df_clean = df.dropna(subset=tracks, how='all').copy()
    
    # 2. Esegue l'interpolazione lineare su vuoti di misurazione brevi (limit=5 secondi)
    df_clean[tracks] = df_clean[tracks].interpolate(method='linear', limit=5)
    
    # 3. Identifica e marca gli outlier fisiologici (range medici di validità)
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
    """Memorizza il DataFrame pulito nel layer Silver, partizionato fisicamente per reparto chirurgico.

    Struttura della directory creata:
    `data/silver/department=<REPARTO>/case_<ID>.parquet`
    """
    partition_dir = silver_dir / f"department={department}"
    partition_dir.mkdir(parents=True, exist_ok=True)
    output_file = partition_dir / f"case_{case_id}.parquet"
    df.to_parquet(output_file, index=False)


def process_all_cases(bronze_dir, silver_dir):
    """Itera su tutti i casi presenti nel layer Bronze ed esegue la trasformazione verso Silver con generazione di Quality Report."""
    silver_dir.mkdir(parents=True, exist_ok=True)
    department_map = load_department_map(bronze_dir)
    parquet_files = list(bronze_dir.glob("case_*.parquet"))
    
    quality_metrics = []  # Lista per il tracking di Data Governance
    for p_file in tqdm(parquet_files, desc="Pulizia dati (Bronze -> Silver)"):
        try:
            case_id = int(p_file.stem.split('_')[1])
            df = pd.read_parquet(p_file)
            
            rows_before = len(df)
            df_clean = clean_case(df, case_id)
            rows_after = len(df_clean)
            
            department = resolve_department(department_map, case_id)
            save_silver(df_clean, case_id, silver_dir, department)
            # Raccoglie i dati per il Report di Qualità
            case_report = {
                "case_id": case_id,
                "rows_original": rows_before,
                "rows_cleaned": rows_after,
                "rows_dropped": rows_before - rows_after,
                "department": department,
                "outliers_count": {}
            }
            
            # Conteggio degli outlier per segnale
            for flag in ['HR_outlier', 'SPO2_outlier', 'SBP_outlier', 'DBP_outlier', 'MBP_outlier']:
                if flag in df_clean.columns:
                    case_report["outliers_count"][flag] = int(df_clean[flag].sum())
            quality_metrics.append(case_report)
        except Exception as e:
            print(f"❌ Errore durante la bonifica di {p_file.name}: {e}")
    # Salva il report di Data Governance globale in un file JSON
    report_file = silver_dir.parent / "quality_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_cases_processed": len(quality_metrics),
            "cases_detail": quality_metrics
        }, f, indent=2)
        
    print(f"✓ Quality Report salvato con successo in: {report_file}")


if __name__ == '__main__':
    print("=== INIZIO FASE DI PULIZIA E BONIFICA SILVER ===")
    process_all_cases(config.BRONZE_DIR, config.SILVER_DIR)
    print("=== PIPELINE SILVER COMPLETATA CON SUCCESSO ===")
