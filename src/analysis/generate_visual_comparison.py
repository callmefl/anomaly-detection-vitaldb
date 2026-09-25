"""Genera grafici prima/dopo per mostrare l'evoluzione visiva del dato da Bronze a Silver."""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(ROOT_DIR))
from src import config

def plot_before_after():
    """Crea un grafico comparativo 'Before & After' della pulizia del segnale."""
    print("=== GENERAZIONE GRAFICO PRIMA vs DOPO (BRONZE vs SILVER) ===")
    
    # Cerca il primo caso disponibile sia in Bronze che in Silver
    bronze_files = sorted(list(config.BRONZE_DIR.glob("case_*.parquet")))
    if not bronze_files:
        print("Nessun file Bronze trovato.")
        return
        
    case_file = bronze_files[0]
    case_id = case_file.stem.split("_")[1]
    
    df_bronze = pd.read_parquet(case_file)
    
    # Carica la versione Silver corrispondente
    silver_files = list(config.SILVER_DIR.rglob(f"case_{case_id}.parquet"))
    if not silver_files:
        print(f"File Silver per il caso {case_id} non trovato.")
        return
        
    df_silver = pd.read_parquet(silver_files[0])
    
    # Seleziona una finestra di 300 punti temporali (es. 5 minuti) dove sono presenti variazioni
    window_start = 500
    window_end = window_start + 300
    
    sub_b = df_bronze.iloc[window_start:window_end]
    sub_s = df_silver.iloc[window_start:window_end]
    
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    
    # 1. Tracciato Bronze (Grezzo con vuoti o picchi)
    time_b = sub_b['Time'] if 'Time' in sub_b.columns else sub_b.index
    hr_b = sub_b['Solar8000/HR'] if 'Solar8000/HR' in sub_b.columns else sub_b.iloc[:, 0]
    
    axes[0].plot(time_b, hr_b, color='#ef4444', label='Frequenza Cardiaca (Bronze Grezzo)', linewidth=1.5, marker='o', markersize=3)
    axes[0].set_title(f'Caso #{case_id} - Layer BRONZE (Dati Grezzi con Missing Values/Outlier)', fontsize=11, fontweight='bold')
    axes[0].set_ylabel('HR (bpm)')
    axes[0].grid(True, linestyle='--', alpha=0.5)
    axes[0].legend(loc='upper right')
    
    # 2. Tracciato Silver (Pulito ed Interpolato)
    time_s = sub_s['Time'] if 'Time' in sub_s.columns else sub_s.index
    hr_s = sub_s['Solar8000_HR'] if 'Solar8000_HR' in sub_s.columns else sub_s.iloc[:, 0]
    
    axes[1].plot(time_s, hr_s, color='#10b981', label='Frequenza Cardiaca (Silver Pulito)', linewidth=1.8)
    axes[1].set_title(f'Caso #{case_id} - Layer SILVER (Dati Bonificati, Interpolati e Validati)', fontsize=11, fontweight='bold')
    axes[1].set_xlabel('Tempo (secondi)')
    axes[1].set_ylabel('HR (bpm)')
    axes[1].grid(True, linestyle='--', alpha=0.5)
    axes[1].legend(loc='upper right')
    
    img_dir = ROOT_DIR / "relazione" / "img"
    img_dir.mkdir(parents=True, exist_ok=True)
    out_path = img_dir / "before_after_cleaning.png"
    
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print(f"✓ Grafico Prima/Dopo salvato in: {out_path}")

if __name__ == '__main__':
    plot_before_after()
