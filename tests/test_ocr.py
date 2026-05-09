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

    def test_structured_ocr_success_with_json(self, sample_text_image_bytes):
        import base64
        b64 = base64.b64encode(sample_text_image_bytes).decode()
        structured_result = {
            "results": [
                {
                    "text": "電材・工具一式（新宿オフィス改修）",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 0], "bottom_right": [100, 20]},
                    "bbox_normalized": {"top_left": [0.0, 0.0], "bottom_right": [0.5, 0.2]},
                    "type": "text",
                    "polygon": [[0, 0], [100, 0], [100, 20], [0, 20]],
                },
                {
                    "text": "請求書番号: KS-2026-0315-0842",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 21], "bottom_right": [120, 40]},
                    "bbox_normalized": {"top_left": [0.0, 0.21], "bottom_right": [0.6, 0.4]},
                    "type": "text",
                    "polygon": [[0, 21], [120, 21], [120, 40], [0, 40]],
                },
                {
                    "text": "請求日: 2026-03-15",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 41], "bottom_right": [110, 60]},
                    "bbox_normalized": {"top_left": [0.0, 0.41], "bottom_right": [0.55, 0.6]},
                    "type": "text",
                    "polygon": [[0, 41], [110, 41], [110, 60], [0, 60]],
                },
                {
                    "text": "支払期日: 2026-04-14",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 61], "bottom_right": [110, 80]},
                    "bbox_normalized": {"top_left": [0.0, 0.61], "bottom_right": [0.55, 0.8]},
                    "type": "text",
                    "polygon": [[0, 61], [110, 61], [110, 80], [0, 80]],
                },
                {
                    "text": "V-34821 株式会社 山陽電材",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 81], "bottom_right": [140, 100]},
                    "bbox_normalized": {"top_left": [0.0, 0.81], "bottom_right": [0.7, 1.0]},
                    "type": "text",
                    "polygon": [[0, 81], [140, 81], [140, 100], [0, 100]],
                },
                {
                    "text": "請求条件: 月末締め翌月末払い",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 101], "bottom_right": [140, 120]},
                    "bbox_normalized": {"top_left": [0.0, 1.01], "bottom_right": [0.7, 1.2]},
                    "type": "text",
                    "polygon": [[0, 101], [140, 101], [140, 120], [0, 120]],
                },
                {
                    "text": "2026-03-15 VCTケーブル 巻 数量: 2 単価: 45000 10% 金額: 90000",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 121], "bottom_right": [200, 140]},
                    "bbox_normalized": {"top_left": [0.0, 1.21], "bottom_right": [1.0, 1.4]},
                    "type": "text",
                    "polygon": [[0, 121], [200, 121], [200, 140], [0, 140]],
                },
                {
                    "text": "MISC-001 現場消耗品 式 数量: 1 単価: 15000 10% 金額: 15000",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 141], "bottom_right": [200, 160]},
                    "bbox_normalized": {"top_left": [0.0, 1.41], "bottom_right": [1.0, 1.6]},
                    "type": "text",
                    "polygon": [[0, 141], [200, 141], [200, 160], [0, 160]],
                },
                {
                    "text": "消費税 10% 10500",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 161], "bottom_right": [100, 180]},
                    "bbox_normalized": {"top_left": [0.0, 1.61], "bottom_right": [0.5, 1.8]},
                    "type": "text",
                    "polygon": [[0, 161], [100, 161], [100, 180], [0, 180]],
                },
                {
                    "text": "請求金額: 115500",
                    "confidence": 0.99,
                    "bbox": {"top_left": [0, 181], "bottom_right": [100, 200]},
                    "bbox_normalized": {"top_left": [0.0, 1.81], "bottom_right": [0.5, 2.0]},
                    "type": "text",
                    "polygon": [[0, 181], [100, 181], [100, 200], [0, 200]],
                },
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
            "summary": {"total_lines": 10, "total_characters": 120, "avg_confidence": 0.99},
        }
        with patch('app.routers.ocr.run_ocr', return_value=structured_result):
            response = client.post(
                "/ocr/structured/json",
                json={"image": b64, "lang": "japan", "image_url": "invoices/2026/03/test.pdf"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["title"] == "電材・工具一式（新宿オフィス改修）"
            assert data["data"]["originalNumber"] == "KS-2026-0315-0842"
            assert data["data"]["vendorName"] == "V-34821 株式会社 山陽電材"
            assert data["data"]["inputCostType"] == "1. invoice"
            assert data["data"]["paymentMethod"] == "3. Purchase (Invoice - One-time)"
            assert data["data"]["totalAmount"] == 115500
            assert len(data["data"]["inputCostItems"]) >= 2
            assert data["rawResults"]

    def test_structured_ocr_blank_image(self, blank_image_bytes):
        class FakeStructuredJobRepository:
            def create_job(self, raw_ocr_json, provider):
                assert raw_ocr_json["results"] == []
                return {
                    "job_id": "structured_test",
                    "provider": provider,
                    "status": "queued",
                    "created_at": "2026-05-09T00:00:00+00:00",
                }

        class FakeStructuredJobPublisher:
            def publish(self, message, topic=None):
                assert message == {"job_id": "structured_test", "provider": "heuristic"}

        with patch('app.routers.ocr.validate_and_preprocess', return_value=(blank_image_bytes, False)), \
             patch('app.routers.ocr.run_ocr', return_value={
                 "results": [],
                 "meta": {"engine": "paddleocr", "engine_version": "3.5.0", "model": "test", "lang": "en",
                          "inference_time_ms": 10, "image_width": 100, "image_height": 100, "was_resized": False},
                 "summary": {"total_lines": 0, "total_characters": 0, "avg_confidence": 0.0}
             }), \
             patch('app.routers.ocr.get_structured_job_repository', return_value=FakeStructuredJobRepository()), \
             patch('app.routers.ocr.get_structured_job_publisher', return_value=FakeStructuredJobPublisher()):
            response = client.post(
                "/ocr/structured",
                files={"file": ("blank.jpg", blank_image_bytes, "image/jpeg")},
            )
            assert response.status_code == 202
            data = response.json()
            assert data["job_id"] == "structured_test"
            assert data["status"] == "queued"
            assert data["status_url"] == "/ocr/structured/jobs/structured_test"

    def test_structured_job_status_success(self):
        job = {
            "job_id": "structured_test",
            "provider": "openrouter",
            "status": "success",
            "created_at": "2026-05-09T00:00:00+00:00",
            "started_at": "2026-05-09T00:00:01+00:00",
            "completed_at": "2026-05-09T00:00:02+00:00",
            "structured_json": {
                "title": "Invoice",
                "originalNumber": None,
                "inputCostType": "1. invoice",
                "issueDate": None,
                "paymentDate": None,
                "vendorName": None,
                "paymentMethod": None,
                "description": None,
                "totalAmount": None,
                "taxes": [],
                "inputCostItems": [],
            },
            "error": None,
        }

        class FakeStructuredJobRepository:
            def get_job(self, job_id):
                assert job_id == "structured_test"
                return job

        with patch('app.routers.ocr.get_structured_job_repository', return_value=FakeStructuredJobRepository()):
            response = client.get("/ocr/structured/jobs/structured_test")

        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "structured_test"
        assert data["status"] == "success"
        assert data["structured_json"]["title"] == "Invoice"
