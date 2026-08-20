"""Integration test per le rotte REST API FastAPI (api/main.py)."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.append(str(Path(__file__).resolve().parent.parent))

from api.main import app

client = TestClient(app)


def test_api_health_endpoint():
    """Verifica l'endpoint GET /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data


def test_api_get_cases_endpoint():
    """Verifica l'endpoint GET /cases."""
    response = client.get("/cases")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        first_case = data[0]
        assert "case_id" in first_case
        assert "department" in first_case


def test_api_get_series_endpoint():
    """Verifica l'endpoint GET /cases/1/series."""
    response = client.get("/cases/1/series?window_seconds=60")
    if response.status_code == 200:
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert "timestamp" in data[0]
    else:
        # Se il caso 1 non è caricato su mongo, restituisce 404
        assert response.status_code == 404


def test_api_detect_endpoint():
    """Verifica l'endpoint POST /cases/1/detect."""
    response = client.post("/cases/1/detect")
    if response.status_code == 200:
        data = response.json()
        assert data["case_id"] == 1
        assert "anomaly_count" in data
        assert "summary_by_method" in data
        assert "anomalies" in data
    else:
        assert response.status_code == 404
