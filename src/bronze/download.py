"""Modulo per l'estrazione ed il download dei dati grezzi dal database clinico VitalDB (Layer Bronze).

Il layer Bronze rappresenta la prima fase della Medallion Architecture:
- Interroga le API ufficiali di VitalDB per individuare i casi contenenti i 5 parametri vitali d'interesse.
- Estrae sia i tracciati temporali numerici ad alta frequenza sia le tabelle dei dati clinici/di laboratorio.
- Memorizza i dati grezzi così come scaricati in formato binario Parquet all'interno di `data/bronze/`.
"""

import sys
from pathlib import Path
import vitaldb
import pandas as pd
from tqdm import tqdm

# Aggiunge la radice del progetto al sys.path per importare le configurazioni centralizzate
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

def find_available_cases(tracks):
    """Interroga VitalDB per trovare gli identificativi dei casi clinici che contengono tutte le tracce richieste.
    
    Args:
        tracks (list): Lista delle tracce biometriche desiderate (es. 'Solar8000/HR', 'Solar8000/PLETH_SPO2').
        
    Returns:
        list: Lista di numeri interi contenente gli ID dei casi clinici compatibili.
    """
    try:
        cases = vitaldb.find_cases(tracks)
        print(f"✓ Trovati {len(cases)} casi chirurgici con la presenza completa delle tracce richieste.")
        return cases
    except Exception as e:
        print(f"❌ Errore durante la ricerca dei casi in VitalDB: {e}")
        return []

def download_case(case_id, tracks, interval, output_dir):
    """Scarica il tracciato biometrico temporale di un singolo caso e lo salva in formato Parquet grezzo.
    
    Args:
        case_id (int): Identificativo univoco del caso clinico.
        tracks (list): Nomi delle tracce sensoristiche da estrarre.
        interval (float): Intervallo di campionamento in secondi (es. 1.0s).
        output_dir (Path): Cartella di destinazione nel layer Bronze.
    """
    try:
        # Carica la matrice numerica dei dati grezzi tramite l'SDK VitalDB
        data = vitaldb.load_case(case_id, tracks, interval)
        if data is None or len(data) == 0:
            print(f"⚠️ Nessun punto temporale recuperato per il caso #{case_id}")
            return
            
        # Converte la matrice in DataFrame Pandas e calcola l'offset temporale in secondi
        df = pd.DataFrame(data, columns=tracks)
        df['Time'] = df.index * interval
        
        # Scrive il file Parquet grezzo senza applicare filtri (storicizzazione immutabile)
        output_file = output_dir / f"case_{case_id}.parquet"
        df.to_parquet(output_file, index=False)
    except Exception as e:
        print(f"❌ Errore durante il download del caso #{case_id}: {e}")

def download_all_cases(tracks, interval, output_dir, max_cases=None):
    """Itera su tutti i casi disponibili e scarica i file con una barra di avanzamento visiva."""
    cases = find_available_cases(tracks)
    if max_cases is not None:
        cases = cases[:max_cases]
        
    for case_id in tqdm(cases, desc="Download casi Bronze in corso"):
        download_case(case_id, tracks, interval, output_dir)

def download_clinical_data(output_dir):
    """Scarica i metadati clinici perioperatori (età, sesso, tipo intervento, reparto) e li salva nel Bronze."""
    try:
        df_clinical = vitaldb.load_clinical_data()
        output_file = output_dir / "clinical_data.parquet"
        df_clinical.to_parquet(output_file, index=False)
        print("✓ Dati clinici e demografici scaricati correttamente.")
    except Exception as e:
        print(f"❌ Errore nel download dei dati clinici: {e}")

if __name__ == '__main__':
    print("=== INIZIO FASE DI INGESTIONE BRONZE ===")
    config.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. Scarica la tabella dei dati clinici di contesto
    download_clinical_data(config.BRONZE_DIR)
    
    # 2. Scarica i tracciati temporali dei casi (utilizza config.MAX_CASES)
    max_c = config.MAX_CASES if config.MAX_CASES is not None else 50
    download_all_cases(config.VITAL_TRACKS, config.SAMPLING_INTERVAL, config.BRONZE_DIR, max_c)
    print("=== INGESTIONE BRONZE COMPLETATA CON SUCCESSO ===")
