"""Integration test per le rotte REST API FastAPI (api/main.py)."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pytest
from api.main import app, get_db

client = TestClient(app)


def _is_mongo_connected():
    """Verifica se MongoDB è attivo e raggiungibile."""
    try:
        db = get_db()
        db.command("ping")
        return True
    except Exception:
        return False


def test_api_health_endpoint():
    """Verifica l'endpoint GET /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data


def test_api_get_cases_endpoint():
    """Verifica l'endpoint GET /cases."""
    if not _is_mongo_connected():
        pytest.skip("MongoDB non raggiungibile per il test /cases")
    response = client.get("/cases")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        first_case = data[0]
        assert "case_id" in first_case
        assert "department" in first_case


def test_api_get_series_endpoint():
    """Verifica l'endpoint GET /cases/{id}/series con asserzioni deterministiche sia positive che negative."""
    if not _is_mongo_connected():
        pytest.skip("MongoDB non raggiungibile per il test /cases/{id}/series")
    # Caso positivo (il caso 1 è registrato nel Gold)
    response = client.get("/cases/1/series?window_seconds=60")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "timestamp" in data[0]

    # Caso negativo deterministico: un ID inesistente deve restituire 404
    response_404 = client.get("/cases/999999/series")
    assert response_404.status_code == 404


def test_api_detect_endpoint():
    """Verifica l'endpoint POST /cases/{id}/detect con asserzioni deterministiche."""
    if not _is_mongo_connected():
        pytest.skip("MongoDB non raggiungibile per il test /cases/{id}/detect")
    # Caso positivo
    response = client.post("/cases/1/detect")
    assert response.status_code == 200
    data = response.json()
    assert data["case_id"] == 1
    assert "anomaly_count" in data
    assert "summary_by_method" in data
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)

    # Caso negativo deterministico
    response_404 = client.post("/cases/999999/detect")
    assert response_404.status_code == 404
