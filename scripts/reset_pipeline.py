"""Azzera lo stato persistente (MongoDB + Bronze/Silver locali) per garantire run riproducibili.

Utilizzo:
    docker exec -it vitaldb_api python scripts/reset_pipeline.py

Sequenza completa dopo il reset:
    docker exec -it vitaldb_api python src/bronze/download.py
    docker exec -it vitaldb_api python src/silver/clean.py
    docker exec -it vitaldb_api python src/gold/load_mongo.py
    docker exec -it vitaldb_api python src/detection/detector.py
    docker exec -it vitaldb_api python src/analysis/benchmark_etl.py
    docker exec -it vitaldb_api python src/analysis/evaluate_models.py
"""

import sys
import shutil
from pathlib import Path

# Setup importazioni dalla radice del progetto
sys.path.append(str(Path(__file__).resolve().parent.parent))

from pymongo import MongoClient
from src import config


def reset_all(confirm: bool = False):
    """Azzera completamente lo stato persistente della pipeline.

    Args:
        confirm: Se False (default interattivo), chiede conferma all'utente.
                 Se True, esegue senza chiedere (utile per automazione).
    """
    print("=" * 60)
    print("  RESET PIPELINE — Tutte le collection e i dati locali")
    print("  verranno azzerati. Questa operazione è irreversibile.")
    print("=" * 60)

    if not confirm:
        risposta = input("\n  Confermi? [s/N]: ").strip().lower()
        if risposta not in ("s", "si", "sì", "y", "yes"):
            print("❌ Reset annullato.")
            return

    print()

    # ── 1. Svuota le collection MongoDB ──────────────────────────────────────
    print("🗄️  Svuotamento collection MongoDB...")
    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]

    collections_to_reset = ["vital_signals", "registry", "anomalies_detected"]
    for coll_name in collections_to_reset:
        try:
            result = db[coll_name].delete_many({})
            print(f"   ✓ '{coll_name}' svuotata ({result.deleted_count} documenti rimossi).")
        except Exception as e:
            print(f"   ⚠️  Errore su '{coll_name}': {e}")

    client.close()

    # ── 2. Ripulisce i file Bronze/Silver locali (mantiene le cartelle) ───────
    print("\n📂 Pulizia directory locali...")
    dirs_to_clean = [config.BRONZE_DIR, config.SILVER_DIR]
    for d in dirs_to_clean:
        try:
            shutil.rmtree(d, ignore_errors=True)
            d.mkdir(parents=True, exist_ok=True)
            print(f"   ✓ Cartella '{d.relative_to(config.ROOT_DIR)}' ripulita.")
        except Exception as e:
            print(f"   ⚠️  Errore su '{d}': {e}")

    # ── 3. Rimuove i report di analisi (saranno rigenerati da Silver/evaluate/benchmark) ──
    reports_to_remove = [
        config.DATA_DIR / "quality_report.json",
        config.DATA_DIR / "ml_evaluation.json",
        config.DATA_DIR / "benchmark_report.json",
    ]
    for report_file in reports_to_remove:
        if report_file.exists():
            report_file.unlink()
            print(f"   ✓ '{report_file.name}' rimosso.")

    print()
    print("=" * 60)
    print("  RESET COMPLETATO — Pipeline pronta per un run pulito.")
    print(f"  MAX_CASES configurato: {config.MAX_CASES}")
    print("=" * 60)
    print()
    print("Prossimi comandi da eseguire in sequenza:")
    print("  docker exec -it vitaldb_api python src/bronze/download.py")
    print("  docker exec -it vitaldb_api python src/silver/clean.py")
    print("  docker exec -it vitaldb_api python src/gold/load_mongo.py")
    print("  docker exec -it vitaldb_api python src/detection/detector.py")
    print("  docker exec -it vitaldb_api python src/analysis/benchmark_etl.py")
    print("  docker exec -it vitaldb_api python src/analysis/evaluate_models.py")


if __name__ == "__main__":
    # In produzione: passa --yes per eseguire senza prompt (es. in CI/CD)
    import argparse
    parser = argparse.ArgumentParser(description="Reset riproducibile della pipeline VitalDB.")
    parser.add_argument("--yes", "-y", action="store_true", help="Esegui senza chiedere conferma.")
    args = parser.parse_args()

    reset_all(confirm=args.yes)
