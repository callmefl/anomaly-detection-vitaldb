"""Valutazione quantitativa delle prestazioni dei modelli di Anomaly Detection."""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.metrics import classification_report, confusion_matrix
from pymongo import MongoClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))
from src import config
from src.detection.detector import (
    load_from_gold, compute_shock_index, compute_severe_hypotension,
    AnomalyDetector, AutoencoderDetector
)

def evaluate_anomaly_models():
    """Valuta i modelli di ML rispetto alle regole cliniche di riferimento."""
    print("=== AVVIO VALUTAZIONE QUANTITATIVA MACHINE LEARNING ===")
    
    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]
    
    # Recupera i casi caricati dal registry
    registry_cases = list(db['registry'].find({}, {"_id": 0, "case_id": 1}))
    case_ids = [c["case_id"] for c in registry_cases]
    
    if not case_ids:
        print("Nessun caso trovato nel database.")
        return
        
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("DataFrame vuoto da MongoDB.")
        return
        
    print(f"Estratti {len(df)} punti temporali per i casi: {case_ids}")
    
    # 1. Calcola Regole Cliniche (Verità clinica di riferimento)
    df = compute_shock_index(df)
    df = compute_severe_hypotension(df)
    
    # Verità di riferimento (Ground Truth Clinico): vero se Shock Index O Ipotensione Severa
    y_clinical = df['shock_index_anomaly'] | df['severe_hypotension_anomaly']
    
    # 2. Calcola Modelli ML
    feature_cols = [c for c in ["Solar8000_HR", "Solar8000_PLETH_SPO2", "Solar8000_NIBP_SBP", "Solar8000_NIBP_DBP", "Solar8000_NIBP_MBP"] if c in df.columns]
    
    # Isolation Forest
    if_detector = AnomalyDetector(method='isolation_forest', contamination=0.05)
    y_if = if_detector.fit_predict(df, feature_cols)
    
    # Autoencoder
    ae = AutoencoderDetector(percentile=95.0, max_iter=300)
    y_ae = ae.fit_predict(df, feature_cols)
    
    # Metriche di performance rispetto a Ground Truth Clinico
    print("\n--- Valutazione Isolation Forest (vs Clinica) ---")
    print(classification_report(y_clinical, y_if, target_names=["Normale", "Anomalia"]))
    
    print("\n--- Valutazione Autoencoder (vs Clinica) ---")
    print(classification_report(y_clinical, y_ae, target_names=["Normale", "Anomalia"]))

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
