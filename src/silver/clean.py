"""Modulo per la pulizia, la bonifica ed il partizionamento dei dati (Layer Silver).

Il layer Silver costituisce la seconda fase della Medallion Architecture:
- Rimuove i record totalmente vuoti (con tutti i parametri biometrici a NaN).
- Effettua l'interpolazione lineare su brevi buchi temporali di misurazione (fino a 5 secondi contigui).
- Etichetta gli outlier fisiologicamente impossibili tramite flag booleani dominio-specifici.
- Organizza ed arricchisce i file Parquet partizionandoli fisicamente in sottodirectory basate sul reparto chirurgico (`department=<REPARTO>`).
"""

import sys
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import os
import json
import datetime
import shutil

# Setup importazioni dalla radice del progetto
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

# Costante per identificare i casi privi di indicazione sul reparto chirurgico
UNKNOWN_DEPARTMENT = "UNKNOWN"


def load_department_map(bronze_dir):
    """Costruisce una mappa hash `case_id -> department` partendo dal file dei dati clinici.

    Legge `clinical_data.parquet` scaricato nel layer Bronze per associare ad ogni paziente
    il relativo reparto chirurgico (es. General Surgery, Cardiac Surgery, ICU).

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

    dept_series = df_clinical.set_index(id_col)["department"]
    # Forza le chiavi a int Python puro: np.int64 e int non matchano in dict.get()
    return {int(k): v for k, v in dept_series.to_dict().items()}


def resolve_department(department_map, case_id):
    """Restituisce il nome del reparto associato ad un caso, applicando il valore di fallback 'UNKNOWN'."""
    dept = department_map.get(case_id)
    if dept is None or (isinstance(dept, float) and pd.isna(dept)):
        return UNKNOWN_DEPARTMENT
    return str(dept)


def load_bronze_case(case_id, bronze_dir):
    """Legge il file Parquet grezzo di un caso dal layer Bronze."""
    file_path = bronze_dir / f"case_{case_id}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    return None


def interpolate_short_gaps(series: pd.Series, max_gap: int = 5):
    """Interpola linearmente solo i buchi interni di valori mancanti con durata <= max_gap campioni.

    I buchi interni di durata > max_gap e i NaN periferici (leading/trailing) non vengono toccati,
    evitando di riempire fittiziamente interruzioni prolungate di segnale (a differenza di interpolate(limit=max_gap)).

    Args:
        series (pd.Series): Serie numerica da interpolare.
        max_gap (int): Durata massima in campioni (secondi a 1Hz) del buco da imputare.

    Returns:
        tuple[pd.Series, pd.Series]: (serie_interpolata, maschera_booleana_imputed).
    """
    is_na = series.isna()
    if not is_na.any():
        return series.copy(), pd.Series(False, index=series.index)

    # Identifica i NaN strettamente interni (compresi tra un valore valido a monte e uno a valle)
    not_na = ~is_na
    has_prev = not_na.cummax()
    has_next = not_na[::-1].cummax()[::-1]
    is_internal = is_na & has_prev & has_next

    if not is_internal.any():
        return series.copy(), pd.Series(False, index=series.index)

    # Raggruppa i blocchi contigui di valori e ne calcola la lunghezza
    group_ids = (is_na != is_na.shift()).cumsum()
    gap_sizes = is_na.groupby(group_ids).transform('size')

    # Solo i buchi interni con dimensione <= max_gap sono candidati all'interpolazione
    short_gap = is_internal & (gap_sizes <= max_gap)

    interpolated = series.interpolate(method='linear')
    res = series.where(~short_gap, interpolated)
    imputed_mask = short_gap & series.isna() & res.notna()
    return res, imputed_mask


def clean_case(df, case_id):
    """Esegue la bonifica ed il filtraggio di Data Quality sui tracciati temporali del caso.

    Fasi di trasformazione:
    1. Griglia temporale intatta: nessun dropna iniziale per preservare i secondi reali (1 Hz).
    2. Segnali continui (HR e SpO2): interpolazione lineare solo su buchi brevi (<= 5s) con tracciamento *_imputed.
    3. Segnali emodinamici a intervalli (NIBP): LOCF con tetto di staleness a 300s (5 minuti) calcolato su griglia piena.
    4. Identificazione outlier fisiologici leggendo min/max da config.TRACK_SPECS come unica fonte di verità.
    5. Scarto finale delle sole righe in cui tutte le tracce biometriche risultano simultaneamente vuote.
    """
    df_clean = df.copy()

    # 1. Segnali continui (HR e SpO2): interpolazione lineare circoscritta a gap <= 5s
    if 'Solar8000/HR' in df_clean.columns:
        clean_hr, hr_imp = interpolate_short_gaps(df_clean['Solar8000/HR'], max_gap=5)
        df_clean['Solar8000/HR'] = clean_hr
        df_clean['HR_imputed'] = hr_imp

    if 'Solar8000/PLETH_SPO2' in df_clean.columns:
        clean_spo2, spo2_imp = interpolate_short_gaps(df_clean['Solar8000/PLETH_SPO2'], max_gap=5)
        df_clean['Solar8000/PLETH_SPO2'] = clean_spo2
        df_clean['SPO2_imputed'] = spo2_imp

    # 2. Segnali emodinamici a intervalli (NIBP): LOCF con tetto di staleness a 300s (5 minuti)
    nibp_tracks = [c for c in ['Solar8000/NIBP_SBP', 'Solar8000/NIBP_DBP', 'Solar8000/NIBP_MBP'] if c in df_clean.columns]
    if nibp_tracks:
        time_series = df_clean['Time'] if 'Time' in df_clean.columns else pd.Series(df_clean.index, index=df_clean.index, dtype=float)
        # Identifica quando è avvenuta una misurazione reale con bracciale
        nibp_measured = df_clean[nibp_tracks[0]].notna()
        last_measure_time = time_series.where(nibp_measured).ffill()
        df_clean['nibp_age_s'] = (time_series - last_measure_time).fillna(9999.0).astype(float)
        # LOCF su NIBP (fino a 300 secondi di validità clinica)
        df_clean[nibp_tracks] = df_clean[nibp_tracks].ffill(limit=300)
    else:
        df_clean['nibp_age_s'] = 9999.0

    # 3. Identifica e marca gli outlier fisiologici leggendo i range da config.TRACK_SPECS
    outlier_map = {
        'Solar8000/HR': 'HR_outlier',
        'Solar8000/PLETH_SPO2': 'SPO2_outlier',
        'Solar8000/NIBP_SBP': 'SBP_outlier',
        'Solar8000/NIBP_DBP': 'DBP_outlier',
        'Solar8000/NIBP_MBP': 'MBP_outlier',
    }
    track_specs = getattr(config, "TRACK_SPECS", {})
    for track_name, flag_col in outlier_map.items():
        if track_name in df_clean.columns:
            spec = track_specs.get(track_name, {})
            min_val = spec.get("min", -float("inf"))
            max_val = spec.get("max", float("inf"))
            val = df_clean[track_name]
            # Valore outlier solo se presente e strettamente fuori dal range fisiologico
            df_clean[flag_col] = val.notna() & ((val < min_val) | (val > max_val))

    # 4. Scarta solo alla fine le righe in cui tutte le tracce vitali risultano contemporaneamente nulle
    vital_cols = [c for c in config.VITAL_TRACKS if c in df_clean.columns]
    if not vital_cols:
        vital_cols = [c for c in df_clean.columns if c not in ('Time', 'case_id', 'nibp_age_s') and not c.endswith('_outlier') and not c.endswith('_imputed')]
    df_clean = df_clean.dropna(subset=vital_cols, how='all').copy()

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
            # Raccoglie i dati per il Report di Qualità (preserva campi per compatibilità dashboard)
            case_report = {
                "case_id": case_id,
                "rows_original": rows_before,
                "rows_cleaned": rows_after,
                "rows_dropped": rows_before - rows_after,
                "department": department,
                "outliers_count": {},
                "sensor_metrics": {}
            }
            
            # Conteggio degli outlier per segnale
            outlier_flags = [
                ('HR_outlier', 'Solar8000/HR'),
                ('SPO2_outlier', 'Solar8000/PLETH_SPO2'),
                ('SBP_outlier', 'Solar8000/NIBP_SBP'),
                ('DBP_outlier', 'Solar8000/NIBP_DBP'),
                ('MBP_outlier', 'Solar8000/NIBP_MBP')
            ]
            for flag, track in outlier_flags:
                if flag in df_clean.columns:
                    case_report["outliers_count"][flag] = int(df_clean[flag].sum())

            # Metriche dettagliate per sensore (osservati, imputati, mancanti, outlier, copertura)
            for flag, track in outlier_flags:
                if track in df.columns:
                    observed = int(df[track].notna().sum())
                    outliers = int(df_clean[flag].sum()) if flag in df_clean.columns else 0
                    missing = int(df_clean[track].isna().sum()) if track in df_clean.columns else 0
                    
                    # Calcolo imputati
                    short_col = flag.replace('_outlier', '')
                    imp_col = f"{short_col}_imputed"
                    if imp_col in df_clean.columns:
                        imputed = int(df_clean[imp_col].sum())
                    elif 'NIBP' in track and 'nibp_age_s' in df_clean.columns and track in df_clean.columns:
                        imputed = int((df_clean[track].notna() & (df_clean['nibp_age_s'] > 0)).sum())
                    else:
                        imputed = 0

                    coverage_pct = round(((observed + imputed) / rows_after * 100), 2) if rows_after > 0 else 0.0
                    case_report["sensor_metrics"][track] = {
                        "observed": observed,
                        "imputed": imputed,
                        "missing": missing,
                        "outliers": outliers,
                        "coverage_pct": min(coverage_pct, 100.0)
                    }

            # Misurazione reale dei valori nulli residui post-bonifica (LOCF + interpolazione)
            vital_cols = [c for c in config.VITAL_TRACKS if c in df_clean.columns]
            nulls_remaining = int(df_clean[vital_cols].isna().sum().sum()) if vital_cols else 0
            total_cells = int(df_clean[vital_cols].size) if vital_cols else 1
            case_report["nulls_remaining"] = nulls_remaining
            case_report["null_pct_cleaned"] = round((nulls_remaining / total_cells) * 100, 2)

            quality_metrics.append(case_report)
        except Exception as e:
            print(f"❌ Errore durante la bonifica di {p_file.name}: {e}")

    # Calcolo metriche aggregate reali
    total_cells_all = sum(c.get("rows_cleaned", 0) * len(config.VITAL_TRACKS) for c in quality_metrics)
    total_nulls_all = sum(c.get("nulls_remaining", 0) for c in quality_metrics)
    overall_null_pct = round((total_nulls_all / total_cells_all * 100), 2) if total_cells_all > 0 else 0.0

    # Salva il report di Data Governance globale in un file JSON
    report_file = silver_dir.parent / "quality_report.json"

    # ── Storicizzazione: archivia il report precedente prima di sovrascriverlo ──
    history_dir = silver_dir.parent / "quality_history"
    history_dir.mkdir(parents=True, exist_ok=True)
    if report_file.exists():
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy(report_file, history_dir / f"quality_report_{ts}.json")
        print(f"✓ Report precedente archiviato in: quality_history/quality_report_{ts}.json")

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "max_cases_configured": config.MAX_CASES,
            "cases_found_in_bronze": len(parquet_files),
            "total_cases_processed": len(quality_metrics),
            "overall_null_pct_silver": overall_null_pct,
            "total_null_cells_silver": total_nulls_all,
            "cases_detail": quality_metrics
        }, f, indent=2)

    print(f"✓ Quality Report salvato con successo in: {report_file} (Null residui Silver: {overall_null_pct}%)")


if __name__ == '__main__':
    print("=== INIZIO FASE DI PULIZIA E BONIFICA SILVER ===")
    process_all_cases(config.BRONZE_DIR, config.SILVER_DIR)
    print("=== PIPELINE SILVER COMPLETATA CON SUCCESSO ===")
