"""Script per l'esecuzione orchestrata end-to-end dell'intera pipeline Medallion.

Esegue in sequenza:
1. Ingestione Bronze (download dei casi mancanti fino a MAX_CASES)
2. Bonifica e partizionamento Silver
3. Ingestion in MongoDB Time Series (Gold)
4. Rilevamento anomalie multilivello (Clinico + ML)
5. Benchmark ETL e calcolo metriche di storage
6. Valutazione quantitativa dei modelli ML

Utilizzo:
    docker exec vitaldb_api python -u scripts/run_pipeline.py
"""

import sys
import time
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from src import config

STEPS = [
    ("Bronze Ingestion", [sys.executable, "-m", "src.bronze.download"]),
    ("Silver Cleansing", [sys.executable, "-m", "src.silver.clean"]),
    ("Gold Ingestion (MongoDB)", [sys.executable, "-m", "src.gold.load_mongo"]),
    ("Anomaly Detection (ML + Clinical)", [sys.executable, "-m", "src.detection.detector"]),
    ("ETL & Storage Benchmark", [sys.executable, "-m", "src.analysis.benchmark_etl"]),
    ("ML Quantitative Evaluation", [sys.executable, "-m", "src.analysis.evaluate_models"]),
]


def main():
    print("=" * 70, flush=True)
    print("🚀 AVVIO PIPELINE END-TO-END VITALDB", flush=True)
    print(f"   Target casi (MAX_CASES): {config.MAX_CASES}", flush=True)
    print(f"   Sampling interval:       {config.SAMPLING_INTERVAL}s", flush=True)
    print(f"   Pipeline version:        {getattr(config, 'PIPELINE_VERSION', '1.1.0')}", flush=True)
    print("=" * 70, flush=True)

    start_total = time.time()

    for idx, (name, cmd) in enumerate(STEPS, start=1):
        print(f"\n[{idx}/{len(STEPS)}] >>> Inizio step: {name}", flush=True)
        t0 = time.time()
        ret = subprocess.run(cmd, cwd=str(ROOT_DIR))
        elapsed = time.time() - t0

        if ret.returncode != 0:
            print(f"\n❌ Step '{name}' FALLITO con exit code {ret.returncode} dopo {elapsed:.1f}s", flush=True)
            sys.exit(ret.returncode)

        print(f"✓ Step '{name}' completato con successo in {elapsed:.1f}s.", flush=True)

    total_elapsed = time.time() - start_total
    print("\n" + "=" * 70, flush=True)
    print(f"🎉 PIPELINE COMPLETATA CON SUCCESSO IN {total_elapsed / 60:.1f} MINUTI!", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
