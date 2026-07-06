"""Tests for invoice batch extraction endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app

client = TestClient(app)

MOCK_OCR_RESULT = {
    "results": [
        {
            "text": "Invoice #12345",
            "confidence": 0.95,
            "bbox": {"top_left": [10, 10], "bottom_right": [200, 30]},
            "bbox_normalized": {"top_left": [0.05, 0.05], "bottom_right": [0.95, 0.15]},
            "type": "text",
            "polygon": [[10, 10], [200, 10], [200, 30], [10, 30]],
        }
    ],
    "meta": {
        "engine": "paddleocr",
        "engine_version": "3.5.0",
        "model": "PP-OCRv4-japan",
        "lang": "japan",
        "inference_time_ms": 500,
        "image_width": 200,
        "image_height": 100,
        "was_resized": False,
    },
    "summary": {"total_lines": 1, "total_characters": 15, "avg_confidence": 0.95},
}


class TestInvoiceBatch:
    def test_batch_multiple_files(self, sample_image_bytes):
        """Test batch endpoint with multiple valid files."""
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/batch",
                files=[
                    ("files", ("inv1.jpg", sample_image_bytes, "image/jpeg")),
                    ("files", ("inv2.jpg", sample_image_bytes, "image/jpeg")),
                ],
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "request_id" in data
            assert len(data["results"]) == 2
            for item in data["results"]:
                assert item["status"] == "success"
                assert item["invoice"] is not None

    def test_batch_single_file(self, sample_image_bytes):
        """Test batch endpoint with a single file."""
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/batch",
                files=[("files", ("inv1.jpg", sample_image_bytes, "image/jpeg"))],
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert len(data["results"]) == 1
            assert data["results"][0]["status"] == "success"

    def test_batch_empty_list(self):
        """Test batch with no files returns validation error."""
        response = client.post("/invoice/batch", files=[])
        # FastAPI returns 422 when required File(...) receives an empty list
        assert response.status_code == 422

    def test_batch_invalid_file(self, sample_image_bytes):
        """Test batch with one invalid file among valid ones."""
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/batch",
                files=[
                    ("files", ("good.jpg", sample_image_bytes, "image/jpeg")),
                    ("files", ("bad.jpg", b"", "image/jpeg")),
                ],
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "partial"
            assert len(data["results"]) == 2
            assert data["results"][0]["status"] == "success"
            assert data["results"][1]["status"] == "error"

    def test_batch_mode_parameter(self, sample_image_bytes):
        """Test that mode parameter is accepted."""
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/batch",
                files=[("files", ("inv1.jpg", sample_image_bytes, "image/jpeg"))],
                data={"mode": "relaxed"},
            )
            assert response.status_code == 200

    def test_batch_extraction_disabled(self, sample_image_bytes):
        """Test batch returns 503 when extraction is disabled."""
        with patch("app.routers.invoice.get_settings") as mock_settings:
            mock_settings.return_value.INVOICE_ENABLE_EXTRACTION = False
            mock_settings.return_value.API_KEY = None
            mock_settings.return_value.MAX_BATCH_SIZE = 20
            mock_settings.return_value.max_image_size_bytes = 20 * 1024 * 1024
            response = client.post(
                "/invoice/batch",
                files=[("files", ("inv1.jpg", sample_image_bytes, "image/jpeg"))],
            )
            assert response.status_code == 503
            data = response.json()
            assert data["error"] == "extraction_disabled"

    def test_batch_ocr_error(self, sample_image_bytes):
        """Test batch handles OCR error gracefully per-file."""
        error_result = {"error": "model_load_failed", "message": "Model not available"}
        with patch("app.routers.invoice.process_single_image", return_value=error_result):
            response = client.post(
                "/invoice/batch",
                files=[("files", ("inv1.jpg", sample_image_bytes, "image/jpeg"))],
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "error"
            assert data["results"][0]["status"] == "error"

    def test_batch_all_files_empty(self):
        """Test batch with all empty files returns error status."""
        response = client.post(
            "/invoice/batch",
            files=[
                ("files", ("a.jpg", b"", "image/jpeg")),
                ("files", ("b.jpg", b"", "image/jpeg")),
            ],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert len(data["results"]) == 2
        assert all(r["status"] == "error" for r in data["results"])


class TestExtractionDisabled:
    def test_extract_disabled_returns_503(self, sample_image_bytes):
        """Test /invoice/extract returns 503 when extraction is disabled."""
        with patch("app.routers.invoice.get_settings") as mock_settings:
            mock_settings.return_value.INVOICE_ENABLE_EXTRACTION = False
            mock_settings.return_value.API_KEY = None
            response = client.post(
                "/invoice/extract",
                files={"file": ("invoice.jpg", sample_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 503
            data = response.json()
            assert data["error"] == "extraction_disabled"
            assert "request_id" in data

    def test_extract_json_disabled_returns_503(self, sample_image_bytes):
        """Test /invoice/extract/json returns 503 when extraction is disabled."""
        import base64
        b64 = base64.b64encode(sample_image_bytes).decode()
        with patch("app.routers.invoice.get_settings") as mock_settings:
            mock_settings.return_value.INVOICE_ENABLE_EXTRACTION = False
            mock_settings.return_value.API_KEY = None
            response = client.post(
                "/invoice/extract/json",
                data={"image": b64},
            )
            assert response.status_code == 503
            assert response.json()["error"] == "extraction_disabled"

    def test_debug_disabled_returns_503(self, sample_image_bytes):
        """Test /invoice/debug returns 503 when extraction is disabled."""
        with patch("app.routers.invoice.get_settings") as mock_settings:
            mock_settings.return_value.INVOICE_ENABLE_EXTRACTION = False
            mock_settings.return_value.API_KEY = None
            response = client.post(
                "/invoice/debug",
                files={"file": ("invoice.jpg", sample_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 503
            assert response.json()["error"] == "extraction_disabled"
