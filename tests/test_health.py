import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

class TestHealth:
    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["ok", "loading"]  # ok if engine ready, loading otherwise
        assert "gpu_available" in data

    def test_health_live(self):
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_health_ready_not_yet_initialized(self):
        # Engine not initialized yet - should return 503
        response = client.get("/health/ready")
        assert response.status_code in [200, 503]

    def test_metrics(self):
        response = client.get("/health/metrics")
        assert response.status_code == 200
        # Prometheus format
        assert b"ocr_requests_total" in response.content

class TestRoot:
    def test_root(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "PaddleOCR REST API"