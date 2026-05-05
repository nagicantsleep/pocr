import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app

client = TestClient(app)

def _mock_run_ocr(*args, **kwargs):
    return {
        "results": [{"text": "Test", "confidence": 0.9,
                     "bbox": {"top_left": [0,0], "bottom_right": [100,50]},
                     "bbox_normalized": {"top_left": [0,0], "bottom_right": [1,0.5]},
                     "type": "text", "polygon": []}],
        "meta": {"engine": "paddleocr", "model": "PP-OCRv4", "lang": "en",
                 "inference_time_ms": 100, "image_width": 200, "image_height": 100, "was_resized": False},
        "summary": {"total_lines": 1, "total_characters": 4, "avg_confidence": 0.9},
    }

class TestBatchOCR:
    def test_batch_success(self, sample_text_image_bytes):
        with patch('app.routers.ocr.run_ocr', _mock_run_ocr):
            files = [
                ("files", ("a.jpg", sample_text_image_bytes, "image/jpeg")),
                ("files", ("b.jpg", sample_text_image_bytes, "image/jpeg")),
            ]
            response = client.post("/ocr/batch", files=files, data={"lang": "en"})
            assert response.status_code == 200
            data = response.json()
            assert data["request_id"]
            assert len(data["results"]) == 2

    def test_batch_json(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()
        with patch('app.routers.ocr.run_ocr', _mock_run_ocr):
            response = client.post("/ocr/batch/json", json={
                "images": [b64, b64],
                "lang": "en",
            })
            assert response.status_code == 200

    def test_batch_too_large(self, sample_text_image_bytes):
        # Create 25 file parts (exceeds MAX_BATCH_SIZE=20)
        files = [
            ("files", (f"img{i}.jpg", sample_text_image_bytes, "image/jpeg"))
            for i in range(25)
        ]
        response = client.post("/ocr/batch", files=files)
        assert response.status_code == 400
        assert "batch_too_large" in response.json()["detail"] or "exceeds maximum" in response.json()["detail"]