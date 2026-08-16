"""Script per il download dei dati grezzi dal database VitalDB e salvataggio nel layer Bronze."""

import argparse
import json
import sys
from pathlib import Path
import vitaldb
import pandas as pd
from tqdm import tqdm

# Aggiunge src al path per permettere l'importazione di config
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

MANIFEST_FILENAME = "download_manifest.json"


def load_manifest(output_dir):
    """Carica il manifest dei casi già scaricati con successo.

    Il manifest permette di riprendere un download interrotto (es. per
    disconnessioni di rete) senza riscaricare i casi già completati.

    Args:
        output_dir (Path): Cartella del layer Bronze.

    Returns:
        dict: Manifest con chiave "completed_case_ids" (lista di int).
    """
    manifest_path = output_dir / MANIFEST_FILENAME
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Manifest illeggibile ({e}), verrà ricreato da zero.")
    return {"completed_case_ids": []}


def save_manifest(manifest, output_dir):
    """Salva il manifest aggiornato su disco.

    Args:
        manifest (dict): Manifest da persistere.
        output_dir (Path): Cartella del layer Bronze.
    """
    manifest_path = output_dir / MANIFEST_FILENAME
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def mark_case_completed(manifest, case_id, output_dir):
    """Aggiunge un case_id al manifest e lo salva immediatamente su disco.

    Il salvataggio immediato (non a fine batch) è ciò che rende il download
    ripartibile: se il processo si interrompe a metà, i casi già segnati
    completati non vengono riscaricati al prossimo avvio.
    """
    if case_id not in manifest["completed_case_ids"]:
        manifest["completed_case_ids"].append(case_id)
    save_manifest(manifest, output_dir)

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

def download_case(case_id, tracks, interval, output_dir, manifest=None):
    """Scarica un singolo caso clinico e lo salva in formato Parquet.
    
    Args:
        case_id (int): ID del caso.
        tracks (list): Lista di tracce da estrarre.
        interval (float): Intervallo di campionamento in secondi.
        output_dir (Path): Cartella di destinazione.
        manifest (dict, optional): Manifest di ripresa; se fornito, il caso
            viene marcato come completato subito dopo il salvataggio riuscito.

    Returns:
        bool: True se il caso è stato scaricato (o era già presente), False in caso di errore.
    """
    try:
        data = vitaldb.load_case(case_id, tracks, interval)
        if data is None or len(data) == 0:
            print(f"Nessun dato recuperato per il caso {case_id}")
            return False
            
        df = pd.DataFrame(data, columns=tracks)
        df['Time'] = df.index * interval
        
        output_file = output_dir / f"case_{case_id}.parquet"
        df.to_parquet(output_file, index=False)

        if manifest is not None:
            mark_case_completed(manifest, case_id, output_dir)
        return True
    except Exception as e:
        print(f"Errore durante il download del caso {case_id}: {e}")
        return False

def download_all_cases(tracks, interval, output_dir, max_cases=None):
    """Scarica più casi mostrando il progresso, con ripresa automatica.

    I casi già presenti nel manifest (`download_manifest.json`) vengono
    saltati: questo permette di rilanciare lo script dopo un'interruzione
    di rete senza riscaricare da capo tutto ciò che era già stato ottenuto.
    """
    cases = find_available_cases(tracks)
    if max_cases is not None:
        cases = cases[:max_cases]

    manifest = load_manifest(output_dir)
    already_done = set(manifest["completed_case_ids"])
    remaining = [c for c in cases if c not in already_done]
    skipped = len(cases) - len(remaining)
    if skipped:
        print(f"{skipped} casi già presenti nel manifest, verranno saltati (resume).")

    for case_id in tqdm(remaining, desc="Download casi in corso"):
        download_case(case_id, tracks, interval, output_dir, manifest=manifest)

def download_clinical_data(output_dir):
    """Scarica i dati clinici e di laboratorio e li salva come Parquet."""
    try:
        df_clinical = vitaldb.load_clinical_data()
        output_file = output_dir / "clinical_data.parquet"
        df_clinical.to_parquet(output_file, index=False)
        print("Dati clinici scaricati correttamente.")
    except Exception as e:
        print(f"Errore nel download dei dati clinici: {e}")

def download_lab_data(output_dir):
    """Scarica i dati di laboratorio da VitalDB e li salva come Parquet.

    Args:
        output_dir (Path): Cartella di destinazione (tipicamente config.BRONZE_DIR).
    """
    try:
        df_lab = vitaldb.load_lab_data()
        output_file = output_dir / "lab_data.parquet"
        df_lab.to_parquet(output_file, index=False)
        print("Dati di laboratorio scaricati correttamente.")
    except Exception as e:
        print(f"Errore nel download dei dati di laboratorio: {e}")

def parse_args():
    """Definisce e interpreta gli argomenti da riga di comando."""
    parser = argparse.ArgumentParser(description="Download dati VitalDB (Layer Bronze).")
    parser.add_argument(
        "--cases",
        type=int,
        default=None,
        help="Numero massimo di casi da scaricare. Sovrascrive MAX_CASES/config se fornito.",
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    print("Inizio fase di download (Layer Bronze)...")
    config.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    
    download_clinical_data(config.BRONZE_DIR)
    download_lab_data(config.BRONZE_DIR)

    # Priorità: argomento --cases > variabile MAX_CASES > default di debug (5 casi)
    if args.cases is not None:
        max_c = args.cases
    elif config.MAX_CASES is not None:
        max_c = config.MAX_CASES
    else:
        max_c = 5
    download_all_cases(config.VITAL_TRACKS, config.SAMPLING_INTERVAL, config.BRONZE_DIR, max_c)
    print("Download completato.")
