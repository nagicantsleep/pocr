import pytest
import io
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app

client = TestClient(app)

def _mock_run_ocr(*args, **kwargs):
    """Mock OCR returning dummy results."""
    return {
        "results": [
            {
                "text": "Hello World",
                "confidence": 0.95,
                "bbox": {"top_left": [10, 10], "bottom_right": [100, 30]},
                "bbox_normalized": {"top_left": [0.1, 0.1], "bottom_right": [1.0, 0.3]},
                "type": "text",
                "polygon": [[10, 10], [100, 10], [100, 30], [10, 30]],
            }
        ],
        "meta": {
            "engine": "paddleocr",
            "model": "PP-OCRv4-en",
            "lang": "en",
            "inference_time_ms": 500,
            "image_width": 200,
            "image_height": 100,
            "was_resized": False,
        },
        "summary": {"total_lines": 1, "total_characters": 11, "avg_confidence": 0.95},
    }

class TestOCREndpoint:
    def test_ocr_success_with_file(self, sample_text_image_bytes):
        with patch('app.routers.ocr.run_ocr', _mock_run_ocr):
            response = client.post(
                "/ocr",
                files={"file": ("test.jpg", sample_text_image_bytes, "image/jpeg")},
                data={"lang": "en", "min_confidence": "0.0"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "request_id" in data
            assert len(data["results"]) == 1

    def test_ocr_success_with_base64_json(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()
        with patch('app.routers.ocr.run_ocr', _mock_run_ocr):
            response = client.post(
                "/ocr/json",  # Use /ocr/json endpoint for base64 JSON
                json={"image": b64, "lang": "en"},
            )
            assert response.status_code == 200

    def test_ocr_missing_file(self):
        response = client.post("/ocr", files={})
        assert response.status_code in [400, 422]  # FastAPI validation may return 422

    def test_ocr_empty_image(self):
        with patch('app.routers.ocr.validate_and_preprocess', side_effect=ValueError("image_empty")):
            response = client.post(
                "/ocr",
                files={"file": ("empty.jpg", b"", "image/jpeg")},
            )
            assert response.status_code == 400

    def test_ocr_unsupported_format(self):
        with patch('app.routers.ocr.validate_and_preprocess', side_effect=ValueError("unsupported_format")):
            response = client.post(
                "/ocr",
                files={"file": ("doc.xyz", b"\x00\x01\x02", "application/octet-stream")},
            )
            assert response.status_code == 415

    def test_ocr_file_too_large(self):
        with patch('app.routers.ocr.validate_and_preprocess', side_effect=ValueError("file_too_large")):
            large_bytes = b"\xff" * (25 * 1024 * 1024)  # 25MB
            response = client.post(
                "/ocr",
                files={"file": ("large.jpg", large_bytes, "image/jpeg")},
            )
            assert response.status_code == 413

    def test_ocr_blank_image(self, blank_image_bytes):
        # Mock validate_and_preprocess to return the blank image bytes
        # and mock run_ocr to return empty results
        with patch('app.routers.ocr.validate_and_preprocess', return_value=(blank_image_bytes, False)), \
             patch('app.routers.ocr.run_ocr', return_value={
                 "results": [],
                 "meta": {"engine": "paddleocr", "model": "test", "lang": "en",
                          "inference_time_ms": 10, "was_resized": False},
                 "summary": {"total_lines": 0, "total_characters": 0, "avg_confidence": 0.0}
             }):
            response = client.post(
                "/ocr",
                files={"file": ("blank.jpg", blank_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["results"] == []