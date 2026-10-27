"""Valutazione quantitativa delle prestazioni dei modelli di Anomaly Detection."""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import datetime
import json
from sklearn.metrics import classification_report, confusion_matrix, precision_score, recall_score, f1_score, average_precision_score
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))
from src import config
from src.detection.detector import (
    load_from_gold, compute_shock_index, compute_severe_hypotension,
    AnomalyDetector, LSTMAutoencoderDetector, FEATURE_COLS, HR_KEY
)

# Forza il line-buffering su stdout anche quando eseguito via 'docker exec' senza TTY (-t)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass


def evaluate_anomaly_models():
    """Valuta quantitativamente i modelli di Machine Learning rispetto alla concordanza con le regole cliniche."""
    print("=== AVVIO VALUTAZIONE QUANTITATIVA MACHINE LEARNING ===", flush=True)
    
    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]
    
    # Recupera esclusivamente i casi con commit completato dal registry
    registry_cases = list(db['registry'].find({"status": "committed"}, {"_id": 0, "case_id": 1}))
    case_ids = [c["case_id"] for c in registry_cases]
    
    if not case_ids:
        print("Nessun caso committed trovato nel database.", flush=True)
        return
        
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("DataFrame vuoto da MongoDB.", flush=True)
        return
        
    print(f"Estratti {len(df)} punti temporali per {len(case_ids)} casi.", flush=True)
    
    # 1. Calcola Regole Cliniche (Concordanza con euristiche cliniche di riferimento)
    df = compute_shock_index(df)
    df = compute_severe_hypotension(df)
    
    # Concordanza di riferimento clinica: vero se Shock Index O Ipotensione Severa
    y_clinical = (df['shock_index_anomaly'] | df['severe_hypotension_anomaly']).values
    total_samples = len(y_clinical)
    positive_samples = int(y_clinical.sum())
    base_rate = float(positive_samples / total_samples) if total_samples > 0 else 0.0
    trivial_baseline_accuracy = 1.0 - base_rate

    print(f"\n--- ANALISI BASE RATE E ACCURACY PARADOX ---", flush=True)
    print(f"Totale punti esaminati: {total_samples}", flush=True)
    print(f"Eventi critici clinici (Positivi): {positive_samples} ({base_rate * 100:.2f}%)", flush=True)
    print(f"Accuratezza Classificatore Banale (predice sempre Normale): {trivial_baseline_accuracy * 100:.2f}%", flush=True)

    # 2. Calcolo feature omogenee con la pipeline di produzione (raggruppate per case_id, Cython nativo)
    g = df.groupby("case_id", sort=False)[HR_KEY]
    df['HR_rolling_mean'] = g.rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)
    df['HR_rolling_std']  = g.rolling(5, min_periods=1).std().reset_index(level=0, drop=True).fillna(0.0)
    df['HR_delta']        = g.diff().fillna(0.0)
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]

    # 3. Isolation Forest ML: singolo fit con imputazione per caso per predizioni e score PR-AUC
    print("\nAddestramento e scoring Isolation Forest...", flush=True)
    if 'case_id' in df.columns:
        X_df = (
            df.groupby('case_id', sort=False)[feature_cols]
            .ffill()
            .groupby(df['case_id'], sort=False)
            .bfill()
            .fillna(0.0)
        )
    else:
        X_df = df[feature_cols].ffill().bfill().fillna(0.0)
    X_imputed = X_df.values
    del X_df

    from sklearn.ensemble import IsolationForest
    clf_if = IsolationForest(contamination=0.05, random_state=42)
    preds_if = clf_if.fit_predict(X_imputed)
    y_if = (preds_if == -1)
    if_scores = -clf_if.score_samples(X_imputed)
    del X_imputed

    # 4. LSTM Autoencoder Neurale (PyTorch)
    print("Addestramento e scoring LSTM Autoencoder...", flush=True)
    ae = LSTMAutoencoderDetector(percentile=95.0, epochs=10)
    y_ae = ae.fit_predict(df, feature_cols)
    ae_scores = ae.reconstruction_error_

    # Metriche oneste focalizzate sulla sola classe anomala
    p_if = float(precision_score(y_clinical, y_if, pos_label=True, zero_division=0))
    r_if = float(recall_score(y_clinical, y_if, pos_label=True, zero_division=0))
    f1_if = float(f1_score(y_clinical, y_if, pos_label=True, zero_division=0))
    ap_if = float(average_precision_score(y_clinical, if_scores))

    p_ae = float(precision_score(y_clinical, y_ae, pos_label=True, zero_division=0))
    r_ae = float(recall_score(y_clinical, y_ae, pos_label=True, zero_division=0))
    f1_ae = float(f1_score(y_clinical, y_ae, pos_label=True, zero_division=0))
    ap_ae = float(average_precision_score(y_clinical, ae_scores))

    print(f"\n--- METRICHE CLASSE ANOMALIA (Confronto con Baseline {base_rate * 100:.1f}%) ---")
    print(f"Isolation Forest  -> Precision: {p_if:.3f} | Recall: {r_if:.3f} | F1: {f1_if:.3f} | PR-AUC: {ap_if:.3f}")
    print(f"LSTM Autoencoder  -> Precision: {p_ae:.3f} | Recall: {r_ae:.3f} | F1: {f1_ae:.3f} | PR-AUC: {ap_ae:.3f}")

    # Salva il report quantitativo in data/ml_evaluation.json
    run_id = config.get_or_create_run_id()
    evaluation_report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": run_id,
        "pipeline_version": getattr(config, "PIPELINE_VERSION", "1.1.0"),
        "total_samples": total_samples,
        "cases_evaluated": len(case_ids),
        "notes": (
            "La pseudo-ground truth clinica è generata da regole euristiche (Shock Index e Ipotensione Severa) "
            "che utilizzano le medesime feature biometriche fornite ai modelli non supervisionati: "
            "la correlazione riflette la concordanza con tali euristiche e presenta una nota circolarità metodologica."
        ),
        "baseline": {
            "positive_samples": positive_samples,
            "base_rate_pct": round(base_rate * 100, 2),
            "trivial_classifier_accuracy_pct": round(trivial_baseline_accuracy * 100, 2),
            "explanation": f"Un classificatore banale che risponde sempre Normale ottiene il {trivial_baseline_accuracy * 100:.1f}% di accuratezza."
        },
        "isolation_forest": {
            "precision_anomaly": round(p_if, 3),
            "recall_anomaly": round(r_if, 3),
            "f1_anomaly": round(f1_if, 3),
            "average_precision_pr_auc": round(ap_if, 3)
        },
        "lstm_autoencoder": {
            "precision_anomaly": round(p_ae, 3),
            "recall_anomaly": round(r_ae, 3),
            "f1_anomaly": round(f1_ae, 3),
            "average_precision_pr_auc": round(ap_ae, 3)
        }
    }
    eval_json_path = config.DATA_DIR / "ml_evaluation.json"
    with open(eval_json_path, "w", encoding="utf-8") as f:
        json.dump(evaluation_report, f, indent=2)
    print(f"✓ Report ML quantitativo salvato in: {eval_json_path} (run_id: {run_id})")

    img_dir = ROOT_DIR / "relazione" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Grafico Distribuzione Reconstruction Error dell'Autoencoder
    plt.figure(figsize=(8, 5))
    plt.hist(ae.reconstruction_error_, bins=50, color='#3b82f6', alpha=0.7, edgecolor='black')
    plt.axvline(ae.threshold_, color='#ef4444', linestyle='--', linewidth=2, label=f'Soglia 95° percentile ({ae.threshold_:.3f})')
    plt.title('Distribuzione Errore di Ricostruzione (MSE) - Autoencoder')
    plt.xlabel('Mean Squared Error (MSE)')
    plt.ylabel('Conteggio Punti')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.4)
    
    chart1_path = img_dir / "autoencoder_mse_distribution.png"
    plt.tight_layout()
    plt.savefig(chart1_path, dpi=300)
    plt.close()
    print(f"✓ Grafico MSE salvato in: {chart1_path}")
    
    # 4. Matrice di Sovrapposizione (Correlation / Heatmap)
    df_methods = pd.DataFrame({
        'Shock Index': df['shock_index_anomaly'],
        'Ipotensione Severa': df['severe_hypotension_anomaly'],
        'Isolation Forest': y_if,
        'Autoencoder': y_ae
    }).astype(int)
    
    overlap_corr = df_methods.corr()
    
    plt.figure(figsize=(7, 6))
    plt.imshow(overlap_corr, cmap='Blues', vmin=0, vmax=1)
    plt.colorbar()
    plt.xticks(range(len(overlap_corr.columns)), overlap_corr.columns, rotation=45, ha='right')
    plt.yticks(range(len(overlap_corr.columns)), overlap_corr.columns)
    for i in range(len(overlap_corr.columns)):
        for j in range(len(overlap_corr.columns)):
            plt.text(j, i, f"{overlap_corr.iloc[i, j]:.2f}", ha="center", va="center", color="black" if overlap_corr.iloc[i, j] < 0.5 else "white")
    plt.title('Matrice di Concordanza/Correlazione tra Metodi')
    
    chart2_path = img_dir / "anomaly_overlap_matrix.png"
    plt.tight_layout()
    plt.savefig(chart2_path, dpi=300)
    plt.close()
    print(f"✓ Matrice di sovrapposizione salvata in: {chart2_path}")

if __name__ == '__main__':
    evaluate_anomaly_models()
