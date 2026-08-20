"""Unit test per il modulo di configurazione src/config.py."""

from pathlib import Path
import sys

# Aggiunge la radice del progetto al sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src import config


def test_config_variables():
    """Verifica che le variabili di configurazione siano definite e corrette."""
    assert config.DB_NAME is not None
    assert config.MONGO_URI is not None
    assert isinstance(config.BRONZE_DIR, Path)
    assert isinstance(config.SILVER_DIR, Path)


def test_vital_tracks_definition():
    """Verifica la presenza dei 5 tracciati vitali chiave."""
    tracks = config.VITAL_TRACKS
    assert "Solar8000/HR" in tracks
    assert "Solar8000/PLETH_SPO2" in tracks
    assert "Solar8000/NIBP_SBP" in tracks
    assert "Solar8000/NIBP_DBP" in tracks
    assert "Solar8000/NIBP_MBP" in tracks
