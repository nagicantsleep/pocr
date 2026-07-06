"""Tests for invoice extraction API endpoints."""

import base64
import io

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


class TestInvoiceExtractFile:
    def test_extract_with_file(self, sample_image_bytes):
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/extract",
                files={"file": ("invoice.jpg", sample_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "request_id" in data
            assert data["line_items_status"] == "not_extracted"
            assert data["validation"]["is_valid"] is True
            assert data["ocr"]["summary"]["total_lines"] == 1

    def test_requires_api_key(self, sample_image_bytes):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.API_KEY = "test-key"
            response = client.post(
                "/invoice/extract",
                files={"file": ("invoice.jpg", sample_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 401


class TestInvoiceExtractJSON:
    def test_extract_with_base64(self, sample_image_bytes):
        b64 = base64.b64encode(sample_image_bytes).decode()
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/extract/json",
                data={"image": b64},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            assert "request_id" in data
            assert data["ocr"]["summary"]["avg_confidence"] == 0.95


class TestInvoiceDebug:
    def test_debug_returns_extra_fields(self, sample_image_bytes):
        with patch("app.routers.invoice.process_single_image", return_value=MOCK_OCR_RESULT):
            response = client.post(
                "/invoice/debug",
                files={"file": ("invoice.jpg", sample_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
            # Debug-specific fields should be present (None)
            assert "layout" in data
            assert "regex_candidates" in data
            assert "table_candidates" in data
            assert "validation_trace" in data


class TestRegressionOCR:
    def test_existing_ocr_endpoint_still_works(self, sample_text_image_bytes):
        """Ensure /ocr endpoint is not broken by invoice router registration."""
        with patch("app.routers.ocr.run_ocr", return_value={
            "results": [{"text": "Hello", "confidence": 0.9, "bbox": {"top_left": [0, 0], "bottom_right": [50, 20]},
                          "bbox_normalized": {"top_left": [0, 0], "bottom_right": [0.5, 0.2]},
                          "type": "text", "polygon": [[0, 0], [50, 0], [50, 20], [0, 20]]}],
            "meta": {"engine": "paddleocr", "model": "test", "lang": "en", "inference_time_ms": 100,
                      "image_width": 100, "image_height": 50, "was_resized": False},
            "summary": {"total_lines": 1, "total_characters": 5, "avg_confidence": 0.9},
        }):
            response = client.post(
                "/ocr",
                files={"file": ("test.jpg", sample_text_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "success"
