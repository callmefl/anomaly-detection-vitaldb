"""Modulo per l'estrazione ed il download dei dati grezzi dal database clinico VitalDB (Layer Bronze).

Il layer Bronze rappresenta la prima fase della Medallion Architecture:
- Interroga le API ufficiali di VitalDB per individuare i casi contenenti i 5 parametri vitali d'interesse.
- Estrae sia i tracciati temporali numerici ad alta frequenza sia le tabelle dei dati clinici/di laboratorio.
- Memorizza i dati grezzi così come scaricati in formato binario Parquet all'interno di `data/bronze/`.
- Registra gli esiti dell'ingestione nel manifest `download_manifest.json` per tracciabilità e riproducibilità.
"""

import sys
from pathlib import Path
import json
import datetime
try:
    import vitaldb
    _VITALDB_AVAILABLE = True
except ImportError:
    vitaldb = None
    _VITALDB_AVAILABLE = False
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
    
    Se il file esiste già ed ha dimensione maggiore di 0 byte, il download viene saltato.

    Args:
        case_id (int): Identificativo univoco del caso clinico.
        tracks (list): Nomi delle tracce sensoristiche da estrarre.
        interval (float): Intervallo di campionamento in secondi (es. 1.0s).
        output_dir (Path): Cartella di destinazione nel layer Bronze.

    Returns:
        dict: Dizionario con esito dell'operazione per il manifest.
    """
    output_file = output_dir / f"case_{case_id}.parquet"
    if output_file.exists() and output_file.stat().st_size > 0:
        return {
            "case_id": case_id,
            "status": "skipped_existing",
            "file": str(output_file.name),
            "size_bytes": output_file.stat().st_size
        }

    try:
        data = vitaldb.load_case(case_id, tracks, interval)
        if data is None or len(data) == 0:
            raise ValueError(f"Nessun punto temporale restituito da VitalDB per il caso #{case_id}")
            
        df = pd.DataFrame(data, columns=tracks)
        df['Time'] = df.index * interval
        
        df.to_parquet(output_file, index=False)
        return {
            "case_id": case_id,
            "status": "downloaded",
            "records": len(df),
            "file": str(output_file.name),
            "size_bytes": output_file.stat().st_size
        }
    except Exception as e:
        print(f"❌ Errore durante il download del caso #{case_id}: {e}")
        return {
            "case_id": case_id,
            "status": "failed",
            "error": str(e)
        }

def download_all_cases(tracks, interval, output_dir, max_cases=None):
    """Itera su tutti i casi disponibili e scarica i file con una barra di avanzamento visiva."""
    cases = find_available_cases(tracks)
    if not cases:
        raise RuntimeError("Nessun caso disponibile trovato per le tracce specificate.")
    if max_cases is not None:
        cases = cases[:max_cases]
        
    results = []
    for case_id in tqdm(cases, desc="Download casi Bronze in corso"):
        res = download_case(case_id, tracks, interval, output_dir)
        results.append(res)
    return cases, results

def download_clinical_data(output_dir):
    """Scarica i metadati clinici perioperatori (età, sesso, tipo intervento, reparto) e li salva nel Bronze.

    Nota di robustezza:
    L'implementazione di `vitaldb.load_clinical_data()` presenta un bug noto che restituisce 0 righe
    se invocata senza parametri. Per garantire la persistenza corretta, interroghiamo direttamente l'endpoint
    REST ufficiale di VitalDB (https://api.vitaldb.net/cases) con fallback su SDK parametrizzato.
    Se entrambi falliscono, solleva un'eccezione esplicita per impedire il completamento silente.
    """
    df_clinical = None
    try:
        url = "https://api.vitaldb.net/cases"
        df_clinical = pd.read_csv(url)
        if df_clinical.empty:
            raise ValueError("Endpoint REST /cases ha restituito una tabella vuota.")
    except Exception as e_rest:
        print(f"⚠️ Avviso: Download da {url} non riuscito ({e_rest}), fallback su SDK VitalDB...")
        try:
            df_clinical = vitaldb.load_clinical_data(caseids=list(range(1, 6389)))
            if df_clinical is None or (isinstance(df_clinical, pd.DataFrame) and df_clinical.empty):
                raise ValueError("SDK VitalDB ha restituito una tabella clinica vuota.")
        except Exception as e_sdk:
            raise RuntimeError(f"Errore irreversibile nel download dei dati clinici: {e_sdk}") from e_sdk

    output_file = output_dir / "clinical_data.parquet"
    df_clinical.to_parquet(output_file, index=False)
    print(f"✓ Dati clinici e demografici scaricati correttamente ({len(df_clinical)} pazienti censiti).")
    return len(df_clinical)

def download_lab_data(output_dir, case_ids=None):
    """Scarica i parametri di laboratorio perioperatori per i casi selezionati e li salva nel Bronze."""
    try:
        url = "https://api.vitaldb.net/lab"
        df_lab = pd.read_csv(url)
        if df_lab.empty:
            raise ValueError("Endpoint REST /lab vuoto.")
        if case_ids is not None:
            id_col = "caseid" if "caseid" in df_lab.columns else "case_id"
            if id_col in df_lab.columns:
                df_lab = df_lab[df_lab[id_col].isin(case_ids)]
    except Exception as e_rest:
        print(f"ℹ Avviso: Endpoint /lab non accessibile ({e_rest}), fallback su SDK VitalDB...")
        try:
            df_lab = vitaldb.load_lab_data(caseids=case_ids)
            if df_lab is not None and not isinstance(df_lab, pd.DataFrame):
                df_lab = pd.DataFrame(df_lab)
        except Exception as e_sdk:
            print(f"ℹ Dati di laboratorio non scaricabili ({e_sdk}); prosecuzione con sole tracce e dati clinici.")
            return False

    if df_lab is not None and not df_lab.empty:
        output_file = output_dir / "lab_data.parquet"
        df_lab.to_parquet(output_file, index=False)
        print(f"✓ Dati di laboratorio scaricati ({len(df_lab)} record).")
        return True
    return False

if __name__ == '__main__':
    print("=== INIZIO FASE DI INGESTIONE BRONZE ===")
    config.BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = config.DATA_DIR / "download_manifest.json"

    manifest = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "max_cases_configured": config.MAX_CASES,
        "sampling_interval": config.SAMPLING_INTERVAL,
        "tracks": config.VITAL_TRACKS,
        "clinical_data": None,
        "lab_data": None,
        "cases": [],
        "success": False
    }

    try:
        # 1. Scarica la tabella dei dati clinici di contesto (obbligatoria)
        n_clinical = download_clinical_data(config.BRONZE_DIR)
        manifest["clinical_data"] = {"status": "success", "records": n_clinical}

        # 2. Scarica i tracciati temporali dei casi
        max_c = config.MAX_CASES if config.MAX_CASES is not None else 50
        case_ids, results = download_all_cases(config.VITAL_TRACKS, config.SAMPLING_INTERVAL, config.BRONZE_DIR, max_c)
        manifest["cases"] = results

        # 3. Scarica i dati di laboratorio (opzionale per contesto, filtrato sui casi estratti)
        lab_ok = download_lab_data(config.BRONZE_DIR, case_ids)
        manifest["lab_data"] = {"status": "success" if lab_ok else "unavailable"}

        # Verifica se vi sono fallimenti
        failed_cases = [r for r in results if r.get("status") == "failed"]
        if failed_cases:
            manifest["success"] = False
            manifest["error"] = f"{len(failed_cases)} casi su {len(results)} non sono stati scaricati con successo."
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
            print(f"❌ Ingestione Bronze fallita: {len(failed_cases)} casi in errore.")
            sys.exit(1)

        manifest["success"] = True
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"✓ Manifest di download salvato in: {manifest_path}")
        print("=== INGESTIONE BRONZE COMPLETATA CON SUCCESSO ===")

    except Exception as e:
        manifest["success"] = False
        manifest["error"] = str(e)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"❌ Errore irreversibile durante l'ingestione Bronze: {e}")
        sys.exit(1)
