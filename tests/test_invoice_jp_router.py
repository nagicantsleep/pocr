"""Tests for v1 JP invoice extraction router."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_png_bytes() -> bytes:
    """Create minimal valid PNG bytes."""
    from PIL import Image

    img = Image.new("RGB", (10, 10), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestExtractSync:
    def test_extract_with_valid_png(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["request_id"] == "stub-001"
        assert data["document_type"] == "qualified_invoice"
        assert data["needs_review"] is False

    def test_extract_bad_content_type(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 400
        assert "Unsupported content type" in response.json()["detail"]

    def test_extract_empty_file(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert response.status_code == 400
        assert "Empty file" in response.json()["detail"]

    def test_extract_with_idempotency_key_header(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
            headers={"Idempotency-Key": "some-key"},
        )
        assert response.status_code == 200

    def test_extract_with_x_lang_header(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
            headers={"X-Lang": "ja"},
        )
        assert response.status_code == 200


class TestExtractAsync:
    def test_extract_async_with_valid_file(self):
        response = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert "job_id" in data
        assert len(data["job_id"]) > 0

    def test_extract_async_with_idempotency_key(self):
        response = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
            headers={"Idempotency-Key": "my-key"},
        )
        assert response.status_code == 200
        assert "job_id" in response.json()

    def test_extract_async_bad_content_type(self):
        response = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("test.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 400

    def test_extract_async_empty_file(self):
        response = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("empty.png", b"", "image/png")},
        )
        assert response.status_code == 400


class TestGetDocument:
    def test_get_returns_404_stub(self):
        response = client.get("/v1/invoice-jp/some-doc-id")
        assert response.status_code == 404
        assert "Stage 1 skeleton" in response.json()["detail"]


class TestApproveReject:
    def test_approve_without_actor_returns_400(self):
        response = client.post("/v1/invoice-jp/doc-123/approve")
        assert response.status_code == 400
        assert "X-Actor" in response.json()["detail"]

    def test_approve_with_actor_returns_200(self):
        response = client.post(
            "/v1/invoice-jp/doc-123/approve",
            headers={"X-Actor": "user@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["actor"] == "user@example.com"
        assert data["document_id"] == "doc-123"

    def test_reject_without_actor_returns_400(self):
        response = client.post("/v1/invoice-jp/doc-123/reject")
        assert response.status_code == 400

    def test_reject_with_actor_returns_200(self):
        response = client.post(
            "/v1/invoice-jp/doc-123/reject",
            headers={"X-Actor": "user@example.com", "X-Reason": "bad quality"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["reason"] == "bad quality"


class TestPatchFields:
    def test_patch_without_actor_returns_400(self):
        response = client.patch("/v1/invoice-jp/doc-123/fields")
        assert response.status_code == 400

    def test_patch_with_actor_returns_200(self):
        response = client.patch(
            "/v1/invoice-jp/doc-123/fields",
            headers={"X-Actor": "user@example.com"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "patched"
        assert data["actor"] == "user@example.com"
