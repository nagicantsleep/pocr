import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app

client = TestClient(app)

class TestAsyncJobs:
    def test_create_job(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()
        response = client.post("/ocr/jobs", json={
            "images": [b64],
            "lang": "en",
        })
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert "status_url" in data

    def test_create_job_too_large(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()
        images = [b64] * 25  # exceeds MAX_BATCH_SIZE=20
        response = client.post("/ocr/jobs", json={"images": images})
        assert response.status_code == 400

    def test_get_job_not_found(self):
        response = client.get("/ocr/jobs/nonexistent_job_id")
        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "not found" in detail.lower() or "job_not_found" in detail

    def test_cancel_job(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()

        # Test cancelling a RUNNING job by directly manipulating job store
        # First create a job
        create_resp = client.post("/ocr/jobs", json={"images": [b64]})
        job_id = create_resp.json()["job_id"]

        # Manually set job status to RUNNING (simulating a job in progress)
        from app.services.job_store import get_job_store
        job_store = get_job_store()
        job_store.update_job(job_id, status="running")

        # Cancel it while running
        cancel_resp = client.delete(f"/ocr/jobs/{job_id}")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    def test_cancel_nonexistent_job(self):
        response = client.delete("/ocr/jobs/nonexistent_job_id")
        assert response.status_code == 404