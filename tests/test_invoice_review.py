"""Tests for invoice review API endpoints (GET, PATCH fields, approve, reject)."""

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

MOCK_INVOICE_ROW = {
    "id": "inv_test123",
    "source_file_hash": None,
    "source_file_path": "invoice.pdf",
    "issuer_name": "Acme Corp",
    "issuer_registration_number": "T1234567890123",
    "invoice_number": "INV-001",
    "transaction_date": "2025-06-01",
    "total_amount": 110000,
    "raw_ocr_json": None,
    "extracted_json": {
        "issuer_name": "Acme Corp",
        "issuer_registration_number": "T1234567890123",
        "invoice_number": "INV-001",
        "transaction_date": "2025-06-01",
        "total_amount": 110000,
    },
    "validation_json": {"is_valid": True},
    "review_status": "needs_review",
    "created_at": "2025-06-01T10:00:00Z",
    "updated_at": "2025-06-01T10:00:00Z",
}


def _mock_repo():
    repo = MagicMock()
    repo.get_invoice.return_value = MOCK_INVOICE_ROW
    repo.update_invoice.return_value = True
    repo.save_invoice.return_value = "inv_new123"
    return repo


def _mock_repo_with_update(**updates):
    """Mock repo where second get_invoice returns updated row."""
    repo = MagicMock()
    original = deepcopy(MOCK_INVOICE_ROW)
    updated = deepcopy(MOCK_INVOICE_ROW)
    updated.update(updates)
    if "issuer_name" in updates:
        updated["extracted_json"] = deepcopy(updated["extracted_json"])
        updated["extracted_json"]["issuer_name"] = updates["issuer_name"]
    repo.get_invoice.side_effect = [original, updated]
    repo.update_invoice.return_value = True
    return repo


class TestGetInvoice:
    @patch("app.routers.invoice._get_repository")
    def test_get_returns_invoice(self, mock_get_repo):
        mock_get_repo.return_value = _mock_repo()
        resp = client.get("/invoice/inv_test123", headers={"X-Api-Key": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "inv_test123"
        assert data["invoice"]["issuer_name"] == "Acme Corp"
        assert data["invoice"]["total_amount"] == 110000

    @patch("app.routers.invoice._get_repository")
    def test_get_missing_returns_404(self, mock_get_repo):
        repo = _mock_repo()
        repo.get_invoice.return_value = None
        mock_get_repo.return_value = repo
        resp = client.get("/invoice/inv_nope", headers={"X-Api-Key": ""})
        assert resp.status_code == 404


class TestUpdateFields:
    @patch("app.routers.invoice._get_repository")
    def test_patch_updates_fields(self, mock_get_repo):
        mock_get_repo.return_value = _mock_repo_with_update(issuer_name="New Corp")
        resp = client.patch(
            "/invoice/inv_test123/fields",
            json={"issuer_name": "New Corp", "reason": "Name correction"},
            headers={"X-Api-Key": ""},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["invoice"]["issuer_name"] == "New Corp"

    @patch("app.routers.invoice._get_repository")
    def test_patch_missing_invoice_returns_404(self, mock_get_repo):
        repo = _mock_repo()
        repo.get_invoice.return_value = None
        mock_get_repo.return_value = repo
        resp = client.patch(
            "/invoice/inv_nope/fields",
            json={"issuer_name": "X"},
            headers={"X-Api-Key": ""},
        )
        assert resp.status_code == 404


class TestApprove:
    @patch("app.routers.invoice._get_repository")
    def test_approve_sets_reviewed(self, mock_get_repo):
        repo = _mock_repo_with_update(review_status="reviewed")
        mock_get_repo.return_value = repo
        resp = client.post("/invoice/inv_test123/approve", headers={"X-Api-Key": ""})
        assert resp.status_code == 200
        call_args = repo.update_invoice.call_args
        assert call_args[0][1]["review_status"] == "reviewed"


class TestReject:
    @patch("app.routers.invoice._get_repository")
    def test_reject_sets_rejected(self, mock_get_repo):
        repo = _mock_repo_with_update(review_status="rejected")
        mock_get_repo.return_value = repo
        resp = client.post(
            "/invoice/inv_test123/reject",
            params={"reason": "Wrong amount"},
            headers={"X-Api-Key": ""},
        )
        assert resp.status_code == 200
        call_args = repo.update_invoice.call_args
        assert call_args[0][1]["review_status"] == "rejected"

    @patch("app.routers.invoice._get_repository")
    def test_reject_missing_returns_404(self, mock_get_repo):
        repo = _mock_repo()
        repo.get_invoice.return_value = None
        mock_get_repo.return_value = repo
        resp = client.post("/invoice/inv_nope/reject", headers={"X-Api-Key": ""})
        assert resp.status_code == 404


class TestUnauthorized:
    def test_requires_api_key_when_configured(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.API_KEY = "test-secret"
            resp = client.get("/invoice/inv_test123")
            assert resp.status_code == 401

    def test_rejects_wrong_api_key(self):
        with patch("app.auth.get_settings") as mock_settings:
            mock_settings.return_value.API_KEY = "test-secret"
            resp = client.get(
                "/invoice/inv_test123",
                headers={"X-Api-Key": "wrong-key"},
            )
            assert resp.status_code == 401
