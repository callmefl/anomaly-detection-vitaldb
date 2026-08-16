"""Script per il download dei dati grezzi dal database VitalDB e salvataggio nel layer Bronze."""

import sys
from pathlib import Path
import vitaldb
import pandas as pd
from tqdm import tqdm

# Aggiunge src al path per permettere l'importazione di config
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

def find_available_cases(tracks):
    """Trova gli ID dei casi clinici che contengono tutte le tracce richieste.
    
    Args:
        tracks (list): Lista delle tracce VitalDB desiderate (es. 'Solar8000/HR').
        
    Returns:
        list: Lista di interi rappresentanti gli ID dei casi.
    """
    try:
        cases = vitaldb.find_cases(tracks)
        print(f"Trovati {len(cases)} casi con le tracce richieste.")
        return cases
    except Exception as e:
        print(f"Errore nella ricerca dei casi: {e}")
        return []

def download_case(case_id, tracks, interval, output_dir):
    """Scarica un singolo caso clinico e lo salva in formato Parquet.
    
    Args:
        case_id (int): ID del caso.
        tracks (list): Lista di tracce da estrarre.
        interval (float): Intervallo di campionamento in secondi.
        output_dir (Path): Cartella di destinazione.
    """
    try:
        data = vitaldb.load_case(case_id, tracks, interval)
        if data is None or len(data) == 0:
            print(f"Nessun dato recuperato per il caso {case_id}")
            return
            
        df = pd.DataFrame(data, columns=tracks)
        df['Time'] = df.index * interval
        
        output_file = output_dir / f"case_{case_id}.parquet"
        df.to_parquet(output_file, index=False)
    except Exception as e:
        print(f"Errore durante il download del caso {case_id}: {e}")

def download_all_cases(tracks, interval, output_dir, max_cases=None):
    """Scarica più casi e mostra il progresso."""
    cases = find_available_cases(tracks)
    if max_cases is not None:
        cases = cases[:max_cases]
        
    for case_id in tqdm(cases, desc="Download casi in corso"):
        download_case(case_id, tracks, interval, output_dir)

def download_clinical_data(output_dir):
    """Scarica i dati clinici e di laboratorio e li salva come Parquet."""
    try:
        df_clinical = vitaldb.load_clinical_data()
        output_file = output_dir / "clinical_data.parquet"
        df_clinical.to_parquet(output_file, index=False)
        print("Dati clinici scaricati correttamente.")
    except Exception as e:
        print(f"Errore nel download dei dati clinici: {e}")

if __name__ == '__main__':
    print("Inizio fase di download (Layer Bronze)...")
    config.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    
    download_clinical_data(config.BRONZE_DIR)
    
    # Per testing/debug scarica solo 5 casi di default, ma usa config.MAX_CASES se settato
    max_c = 5 if config.MAX_CASES is None else config.MAX_CASES
    download_all_cases(config.VITAL_TRACKS, config.SAMPLING_INTERVAL, config.BRONZE_DIR, max_c)
    print("Download completato.")
