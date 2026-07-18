"""Tests for v1 JP invoice extraction router."""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import OperatorTokenIdentity, Settings

client = TestClient(app)


def _make_png_bytes() -> bytes:
    """Create a valid PNG that passes the quality gate (has edges and contrast)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (200, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    # Draw black rectangles to simulate text — gives sharpness and contrast
    for y in range(20, 180, 20):
        draw.rectangle([10, y, 180, y + 10], fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fake_ocr_result() -> dict:
    """Return a plausible OCR result dict (same shape as run_ocr output)."""
    return {
        "results": [
            {
                "text": "株式会社テスト",
                "confidence": 0.95,
                "bbox": {"top_left": [10, 10], "bottom_right": [200, 40]},
                "type": "text",
            },
            {
                "text": "T1234567890123",
                "confidence": 0.90,
                "bbox": {"top_left": [10, 50], "bottom_right": [200, 80]},
                "type": "text",
            },
            {
                "text": "合計 10,000円",
                "confidence": 0.88,
                "bbox": {"top_left": [10, 90], "bottom_right": [200, 120]},
                "type": "text",
            },
        ],
        "meta": {"engine": "paddleocr", "lang": "ja", "inference_time_ms": 50},
        "summary": {"total_lines": 3, "total_characters": 30, "avg_confidence": 0.91},
    }


@pytest.fixture(autouse=True)
def _mock_run_ocr():
    """Mock run_ocr so tests don't need paddleocr installed."""
    with patch("app.routers.v1.invoice_jp.run_ocr", return_value=_fake_ocr_result()):
        yield


def _extract_sync() -> dict:
    """Helper: run a sync extraction and return the response JSON."""
    resp = client.post(
        "/v1/invoice-jp/extract",
        files={"file": ("test.png", _make_png_bytes(), "image/png")},
    )
    assert resp.status_code == 200, f"extract failed: {resp.text}"
    return resp.json()


class TestExtractSync:
    def test_extract_with_valid_png(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert isinstance(data["request_id"], str)
        assert len(data["request_id"]) > 0
        assert data["document_type"] == "qualified_invoice"
        assert "needs_review" in data
        assert "confidence" in data
        assert "fields" in data
        assert "document_id" in data

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
        async def claim_or_get_operation(_key, resource_id, _fp, **_kwargs):
            return True, resource_id, False, "pending"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ), patch(
            "app.routers.v1.invoice_jp._idempotency_service.mark_operation_completed",
            return_value=True,
        ):
            response = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "some-key-sync"},
            )
        assert response.status_code == 200

    def test_extract_with_x_lang_header(self):
        response = client.post(
            "/v1/invoice-jp/extract",
            files={"file": ("test.png", _make_png_bytes(), "image/png")},
            headers={"X-Lang": "ja"},
        )
        assert response.status_code == 200

    def test_extract_idempotency_returns_cached(self):
        key = "idem-cache-test-sync"
        claims = {}

        async def claim_or_get_operation(idempotency_key, resource_id, _fp, **_kwargs):
            if idempotency_key in claims:
                return False, claims[idempotency_key], False, "completed"
            claims[idempotency_key] = resource_id
            return True, resource_id, False, "pending"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ), patch(
            "app.routers.v1.invoice_jp._idempotency_service.mark_operation_completed",
            return_value=True,
        ):
            resp1 = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": key},
            )
            resp2 = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": key},
            )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["document_id"] == resp1.json()["document_id"]
        assert resp2.json() == resp1.json()

    def test_extract_idempotency_rejects_missing_completed_resource(self):
        async def claim_or_get_operation(_key, _resource_id, _fp, **_kwargs):
            return False, "missing-document", False, "completed"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ):
            response = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "stale-sync-key"},
            )

        assert response.status_code == 409

    def test_extract_idempotency_conflicts_when_lang_changes(self):
        claims = {}

        async def claim_or_get_operation(key, resource_id, fingerprint, **_kwargs):
            if key in claims:
                return False, claims[key][0], claims[key][1] != fingerprint, "completed"
            claims[key] = (resource_id, fingerprint)
            return True, resource_id, False, "pending"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ), patch(
            "app.routers.v1.invoice_jp._idempotency_service.mark_operation_completed",
            return_value=True,
        ):
            first = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "lang-conflict", "X-Lang": "ja"},
            )
            second = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "lang-conflict", "X-Lang": "en"},
            )

        assert first.status_code == 200
        assert second.status_code == 409

    def test_extract_rejects_oversized_upload_before_processing(self):
        settings = MagicMock(max_image_size_bytes=10, MAX_IMAGE_SIZE_MB=0)
        with patch(
            "app.routers.v1.invoice_jp.get_settings",
            return_value=settings,
        ), patch("app.routers.v1.invoice_jp.run_ocr") as run_ocr:
            response = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("large.png", b"x" * 11, "image/png")},
            )
        assert response.status_code == 413
        run_ocr.assert_not_called()

    def test_extract_storage_failure_rolls_back_document(self):
        from app.services.review_service import get_document_store

        documents_before = set(get_document_store()._documents)
        storage = AsyncMock()
        storage.put.side_effect = OSError("disk full")
        storage.delete.return_value = True
        audit_service = MagicMock(log=AsyncMock())
        dispatcher = MagicMock(dispatch=AsyncMock())
        search_service = MagicMock(index_document=AsyncMock())
        with patch(
            "app.routers.v1.invoice_jp.get_storage_adapter",
            return_value=storage,
        ), patch(
            "app.routers.v1.invoice_jp.get_audit_log_service",
            return_value=audit_service,
        ), patch(
            "app.routers.v1.invoice_jp.get_webhook_dispatcher",
            return_value=dispatcher,
        ), patch(
            "app.routers.v1.invoice_jp._get_search_service",
            return_value=search_service,
        ):
            response = client.post(
                "/v1/invoice-jp/extract",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
            )

        assert response.status_code == 503
        assert set(get_document_store()._documents) == documents_before
        audit_service.log.assert_not_awaited()
        dispatcher.dispatch.assert_not_awaited()
        search_service.index_document.assert_not_awaited()


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
        # Sync returns immediately; document_id lands via job poll, not response body.

    def test_extract_async_with_idempotency_key(self):
        async def claim_or_get_operation(_key, resource_id, _fp):
            return True, resource_id, False, "pending"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ):
            response = client.post(
                "/v1/invoice-jp/extract:async",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "my-key-async"},
            )
        assert response.status_code == 200
        assert "job_id" in response.json()

    def test_extract_async_idempotency_returns_same_job(self):
        key = "idem-cache-test-async"
        claims = {}

        async def claim_or_get_operation(idempotency_key, resource_id, _fp):
            if idempotency_key in claims:
                return False, claims[idempotency_key], False, "completed"
            claims[idempotency_key] = resource_id
            return True, resource_id, False, "pending"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ):
            first = client.post(
                "/v1/invoice-jp/extract:async",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": key},
            )
            second = client.post(
                "/v1/invoice-jp/extract:async",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": key},
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["job_id"] == first.json()["job_id"]
        assert second.json() == first.json()

    def test_extract_async_idempotency_rejects_missing_resource(self):
        async def claim_or_get_operation(_key, _resource_id, _fp):
            return False, "missing-job", False, "completed"

        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.claim_or_get_operation",
            side_effect=claim_or_get_operation,
        ):
            response = client.post(
                "/v1/invoice-jp/extract:async",
                files={"file": ("test.png", _make_png_bytes(), "image/png")},
                headers={"Idempotency-Key": "stale-async-key"},
            )

        assert response.status_code == 409

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

    def test_extract_async_rejects_oversized_upload_before_job_creation(self):
        settings = MagicMock(max_image_size_bytes=10, MAX_IMAGE_SIZE_MB=0)
        with patch(
            "app.routers.v1.invoice_jp.get_settings",
            return_value=settings,
        ), patch("app.routers.v1.invoice_jp.get_job_store") as get_job_store:
            response = client.post(
                "/v1/invoice-jp/extract:async",
                files={"file": ("large.png", b"x" * 11, "image/png")},
            )
        assert response.status_code == 413
        get_job_store.assert_not_called()


class TestGetDocument:
    def test_get_returns_404_for_unknown_id(self):
        response = client.get("/v1/invoice-jp/nonexistent-id")
        assert response.status_code == 404

    def test_get_returns_stored_document(self):
        data = _extract_sync()
        document_id = data["document_id"]
        response = client.get(f"/v1/invoice-jp/{document_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["document_id"] == document_id
        assert body["document_type"] == "qualified_invoice"
        assert "fields" in body
        assert "confidence" in body
        assert "needs_review" in body
        assert "created_at" in body
        assert "updated_at" in body


class TestApproveReject:
    def test_approve_unknown_document_returns_404_without_spoofable_actor(self):
        response = client.post("/v1/invoice-jp/doc-123/approve")
        assert response.status_code == 404

    def test_approve_with_actor_returns_200(self):
        data = _extract_sync()
        document_id = data["document_id"]
        response = client.post(
            f"/v1/invoice-jp/{document_id}/approve",
            headers={"X-Actor": "spoofed@example.com"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "approved"
        assert body["actor"] == "anonymous"
        assert body["document_id"] == document_id

    def test_reject_unknown_document_returns_404_without_spoofable_actor(self):
        response = client.post("/v1/invoice-jp/doc-123/reject")
        assert response.status_code == 404

    def test_reject_with_actor_returns_200(self):
        data = _extract_sync()
        document_id = data["document_id"]
        response = client.post(
            f"/v1/invoice-jp/{document_id}/reject",
            headers={"X-Actor": "user@example.com", "X-Reason": "bad quality"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "rejected"
        assert body["reason"] == "bad quality"

    def test_approve_unknown_doc_returns_404(self):
        response = client.post(
            "/v1/invoice-jp/does-not-exist/approve",
            headers={"X-Actor": "user@example.com"},
        )
        assert response.status_code == 404


class TestPatchFields:
    def test_patch_unknown_document_returns_404_without_spoofable_actor(self):
        response = client.patch("/v1/invoice-jp/doc-123/fields", json={})
        assert response.status_code == 404

    def test_patch_with_actor_returns_200(self):
        data = _extract_sync()
        document_id = data["document_id"]
        response = client.patch(
            f"/v1/invoice-jp/{document_id}/fields",
            json={},
            headers={"X-Actor": "spoofed@example.com"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "patched"
        assert body["actor"] == "anonymous"

    def test_patch_unknown_doc_returns_404(self):
        response = client.patch(
            "/v1/invoice-jp/does-not-exist/fields",
            json={},
            headers={"X-Actor": "user@example.com"},
        )
        assert response.status_code == 404


class TestOperatorAuthOnReadRoutes:
    """Issue 6: Read routes must require operator auth when configured."""

    def test_review_list_requires_auth_when_configured(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.OPERATOR_BEARER_TOKEN = "test-token"
            from fastapi.testclient import TestClient as TC
            c = TC(app)
            resp = c.get("/v1/documents")
            assert resp.status_code == 401

    def test_review_list_allows_with_valid_token(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.OPERATOR_BEARER_TOKEN = "test-token"
            from fastapi.testclient import TestClient as TC
            c = TC(app)
            resp = c.get("/v1/documents", headers={"Authorization": "Bearer test-token"})
            assert resp.status_code == 200

    def test_audit_requires_auth_when_configured(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.OPERATOR_BEARER_TOKEN = "test-token"
            from fastapi.testclient import TestClient as TC
            c = TC(app)
            resp = c.get("/v1/audit")
            assert resp.status_code == 401

    def test_search_requires_auth_when_configured(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.OPERATOR_BEARER_TOKEN = "test-token"
            from fastapi.testclient import TestClient as TC
            c = TC(app)
            resp = c.get("/v1/search?q=test")
            assert resp.status_code == 401


class TestJobPrivacyAndCancellation:
    def test_job_routes_require_token_and_hide_upload_content(self):
        from app.services.job_store import get_job_store

        job_store = get_job_store()
        job = job_store.create_job(
            images=["c2Vuc2l0aXZlLXJlY2VpcHQ="],
            tenant_id="tenant-a",
        )
        job_id = job["job_id"]
        settings = Settings(
            OPERATOR_TOKEN_MAP={
                "test-token": OperatorTokenIdentity(
                    tenant_id="tenant-a",
                    user_id="operator-a",
                    roles=("operator",),
                )
            }
        )
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value = settings
            unauthenticated = client.get(f"/v1/jobs/{job_id}")
            authenticated = client.get(
                f"/v1/jobs/{job_id}",
                headers={"Authorization": "Bearer test-token"},
            )
            cancel_unauthenticated = client.post(f"/v1/jobs/{job_id}/cancel")

        assert unauthenticated.status_code == 401
        assert cancel_unauthenticated.status_code == 401
        assert authenticated.status_code == 200
        assert "images" not in authenticated.json()
        assert "c2Vuc2l0aXZlLXJlY2VpcHQ=" not in authenticated.text

    def test_legacy_job_cancel_also_requires_operator_token(self):
        from app.services.job_store import get_job_store

        job_store = get_job_store()
        job = job_store.create_job(images=["c2Vuc2l0aXZlLXJlY2VpcHQ="])
        job_id = job["job_id"]
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.OPERATOR_BEARER_TOKEN = "test-token"
            mock_settings.return_value.API_KEY = None
            unauthenticated = client.delete(f"/ocr/jobs/{job_id}")
            authenticated = client.delete(
                f"/ocr/jobs/{job_id}",
                headers={"Authorization": "Bearer test-token"},
            )

        assert unauthenticated.status_code == 401
        assert authenticated.status_code == 200
        assert authenticated.json()["status"] == "cancelled"

    def test_cancelled_job_cannot_transition_to_completed(self):
        from app.services.job_store import JobStatus, get_job_store

        job_store = get_job_store()
        job = job_store.create_job(images=["c2Vuc2l0aXZlLXJlY2VpcHQ="])
        job_id = job["job_id"]
        assert job_store.update_job(job_id, status=JobStatus.RUNNING)
        assert job_store.cancel_job(job_id)
        assert not job_store.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            expected_statuses=(JobStatus.RUNNING,),
        )
        assert job_store.get_job(job_id)["status"] == JobStatus.CANCELLED

    def test_v1_cancel_releases_the_job_idempotency_lease(self):
        from app.services.job_store import get_job_store

        job_store = get_job_store()
        job = job_store.create_job(
            images=["c2Vuc2l0aXZlLXJlY2VpcHQ="],
            tenant_id="development",
            idempotency_key="development:cancel-key",
            request_fingerprint="fingerprint",
        )
        with patch(
            "app.routers.v1.invoice_jp._idempotency_service.release_pending_operation",
            new_callable=AsyncMock,
            return_value=True,
        ) as release:
            response = client.post(f"/v1/jobs/{job['job_id']}/cancel")

        assert response.status_code == 200
        release.assert_awaited_once_with(
            "development:cancel-key",
            job["job_id"],
            "fingerprint",
        )
