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
    2. Identificazione outlier fisiologici PRIMA dell'imputazione leggendo min/max da config.TRACK_SPECS:
       in questo modo un artefatto sensoriale viene marcato nella riga originale ma non viene propagato
       dalle fasi successive di interpolazione o forward-fill.
    3. Segnali continui (HR e SpO2): interpolazione lineare solo su buchi brevi (<= 5s) con tracciamento *_imputed.
    4. Segnali emodinamici a intervalli (NIBP): LOCF per singola traccia (limit=300s) con tracciamento esplicito
       di SBP_imputed, DBP_imputed, MBP_imputed e calcolo di nibp_age_s.
    5. Scarto finale delle sole righe in cui tutte le tracce biometriche risultano simultaneamente vuote.
    """
    df_clean = df.copy()

    # 1. Identifica e marca gli outlier fisiologici SUI DATI GREZZI (prima di ffill e interpolazione)
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
            # Valore outlier solo se osservato e strettamente fuori dal range fisiologico
            df_clean[flag_col] = val.notna() & ((val < min_val) | (val > max_val))

    # 2. Segnali continui (HR e SpO2): interpolazione lineare circoscritta a gap <= 5s (senza propagare outlier)
    if 'Solar8000/HR' in df_clean.columns:
        raw_hr = df_clean['Solar8000/HR']
        out_hr = df_clean['HR_outlier']
        clean_hr, hr_imp = interpolate_short_gaps(raw_hr.mask(out_hr), max_gap=5)
        df_clean['Solar8000/HR'] = clean_hr.where(~out_hr, raw_hr)
        df_clean['HR_imputed'] = hr_imp & (~out_hr)

    if 'Solar8000/PLETH_SPO2' in df_clean.columns:
        raw_spo2 = df_clean['Solar8000/PLETH_SPO2']
        out_spo2 = df_clean['SPO2_outlier']
        clean_spo2, spo2_imp = interpolate_short_gaps(raw_spo2.mask(out_spo2), max_gap=5)
        df_clean['Solar8000/PLETH_SPO2'] = clean_spo2.where(~out_spo2, raw_spo2)
        df_clean['SPO2_imputed'] = spo2_imp & (~out_spo2)

    # 3. Segnali emodinamici a intervalli (NIBP): LOCF con tetto di staleness a 300s (5 minuti) per traccia
    nibp_map = [
        ('Solar8000/NIBP_SBP', 'SBP_outlier', 'SBP_imputed'),
        ('Solar8000/NIBP_DBP', 'DBP_outlier', 'DBP_imputed'),
        ('Solar8000/NIBP_MBP', 'MBP_outlier', 'MBP_imputed'),
    ]
    present_nibp = [(t, o, i) for t, o, i in nibp_map if t in df_clean.columns]
    if present_nibp:
        time_series = df_clean['Time'] if 'Time' in df_clean.columns else pd.Series(df_clean.index, index=df_clean.index, dtype=float)
        # Identifica quando è avvenuta una misurazione reale valida su almeno un canale del bracciale NIBP
        any_valid_nibp = pd.Series(False, index=df_clean.index)
        for t, o, _ in present_nibp:
            any_valid_nibp = any_valid_nibp | (df_clean[t].notna() & (~df_clean[o]))
        last_measure_time = time_series.where(any_valid_nibp).ffill()
        df_clean['nibp_age_s'] = (time_series - last_measure_time).fillna(9999.0).astype(float)

        # LOCF individuale per ciascuna traccia NIBP senza trascinare eventuali outlier
        for t, o, imp_col in present_nibp:
            raw_col = df_clean[t]
            out_mask = df_clean[o]
            was_na = raw_col.isna()
            filled_col = raw_col.mask(out_mask).ffill(limit=300)
            df_clean[t] = filled_col.where(~out_mask, raw_col)
            df_clean[imp_col] = was_na & df_clean[t].notna()
    else:
        df_clean['nibp_age_s'] = 9999.0

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
    """Itera sui casi del layer Bronze ed esegue la trasformazione verso Silver con generazione di Quality Report."""
    silver_dir.mkdir(parents=True, exist_ok=True)
    department_map = load_department_map(bronze_dir)
    all_bronze_files = sorted(
        bronze_dir.glob("case_*.parquet"),
        key=lambda p: int(p.stem.split('_')[1]) if p.stem.split('_')[1].isdigit() else 0
    )

    # Allinea il perimetro dei casi al manifest corrente (se presente) o a config.MAX_CASES
    manifest_file = bronze_dir.parent / "download_manifest.json"
    manifest_case_ids = None
    if manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as mf:
                m_data = json.load(mf)
            if m_data.get("max_cases_configured") == config.MAX_CASES and m_data.get("cases"):
                manifest_case_ids = {
                    int(c["case_id"]) for c in m_data["cases"]
                    if c.get("status") in ("downloaded", "skipped_existing")
                }
        except Exception:
            manifest_case_ids = None

    if manifest_case_ids:
        parquet_files = [p for p in all_bronze_files if int(p.stem.split('_')[1]) in manifest_case_ids]
    elif config.MAX_CASES is not None:
        parquet_files = all_bronze_files[:config.MAX_CASES]
    else:
        parquet_files = all_bronze_files

    # Rimuove eventuali file Silver obsoleti di run precedenti con perimetro differente
    active_case_ids = {int(p.stem.split('_')[1]) for p in parquet_files}
    for old_silver in silver_dir.rglob("case_*.parquet"):
        try:
            old_id = int(old_silver.stem.split('_')[1])
            if old_id not in active_case_ids:
                old_silver.unlink()
        except Exception:
            pass

    quality_metrics = []  # Lista per il tracking di Data Governance
    sensor_defs = [
        ('HR_outlier', 'HR_imputed', 'Solar8000/HR'),
        ('SPO2_outlier', 'SPO2_imputed', 'Solar8000/PLETH_SPO2'),
        ('SBP_outlier', 'SBP_imputed', 'Solar8000/NIBP_SBP'),
        ('DBP_outlier', 'DBP_imputed', 'Solar8000/NIBP_DBP'),
        ('MBP_outlier', 'MBP_imputed', 'Solar8000/NIBP_MBP'),
    ]

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
                "temporal_retention_pct": round((rows_after / rows_before * 100), 2) if rows_before > 0 else 0.0,
                "department": department,
                "outliers_count": {},
                "sensor_metrics": {}
            }
            
            # Conteggio omogeneo sul perimetro delle righe Silver (observed + imputed + missing == rows_cleaned)
            for flag, imp_col, track in sensor_defs:
                if flag in df_clean.columns:
                    case_report["outliers_count"][flag] = int(df_clean[flag].sum())

                if track in df_clean.columns:
                    imp_series = df_clean[imp_col] if imp_col in df_clean.columns else pd.Series(False, index=df_clean.index)
                    imputed = int(imp_series.sum())
                    observed = int((df_clean[track].notna() & (~imp_series)).sum())
                    missing = int(df_clean[track].isna().sum())
                    outliers = int(df_clean[flag].sum()) if flag in df_clean.columns else 0

                    observed_pct = round((observed / rows_after * 100), 2) if rows_after > 0 else 0.0
                    coverage_pct = round(((observed + imputed) / rows_after * 100), 2) if rows_after > 0 else 0.0
                    temporal_coverage_bronze_pct = round(((observed + imputed) / rows_before * 100), 2) if rows_before > 0 else 0.0

                    case_report["sensor_metrics"][track] = {
                        "observed": observed,
                        "imputed": imputed,
                        "missing": missing,
                        "outliers": outliers,
                        "observed_pct": observed_pct,
                        "coverage_pct": coverage_pct,
                        "temporal_coverage_bronze_pct": temporal_coverage_bronze_pct
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

    run_id = config.get_or_create_run_id()
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "run_id": run_id,
            "pipeline_version": getattr(config, "PIPELINE_VERSION", "1.1.0"),
            "sampling_interval": config.SAMPLING_INTERVAL,
            "max_cases_configured": config.MAX_CASES,
            "cases_found_in_bronze": len(parquet_files),
            "total_cases_processed": len(quality_metrics),
            "overall_null_pct_silver": overall_null_pct,
            "total_null_cells_silver": total_nulls_all,
            "cases_detail": quality_metrics
        }, f, indent=2)

    print(f"✓ Quality Report salvato con successo in: {report_file} (Null residui Silver: {overall_null_pct}%, run_id: {run_id})")


if __name__ == '__main__':
    print("=== INIZIO FASE DI PULIZIA E BONIFICA SILVER ===")
    process_all_cases(config.BRONZE_DIR, config.SILVER_DIR)
    print("=== PIPELINE SILVER COMPLETATA CON SUCCESSO ===")

