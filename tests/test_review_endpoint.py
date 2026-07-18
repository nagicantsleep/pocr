from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.audit_log import _store as _audit_store
from app.services.document_store import StoredDocument
from app.services.review_service import get_document_store


def _make_doc(doc_id: str = "doc-1", **overrides) -> StoredDocument:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=doc_id,
        document_type="qualified_invoice",
        structured_json={"vendor": "Acme", "total": 1000},
        confidence=0.92,
        needs_review=True,
        review_status="pending",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return StoredDocument(**defaults)


@pytest.fixture(autouse=True)
def clear_stores():
    store = get_document_store()
    store._documents.clear()
    _audit_store.clear()
    yield
    store._documents.clear()
    _audit_store.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seed_documents():
    store = get_document_store()
    store.store(_make_doc("doc-1", review_status="pending"))
    store.store(_make_doc("doc-2", review_status="approved"))
    store.store(_make_doc("doc-3", review_status="needs_review"))


# --- GET /v1/documents ---


def test_list_documents(client, seed_documents):
    resp = client.get("/v1/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "documents" in data
    assert data["total"] == 3
    assert len(data["documents"]) == 3


def test_list_documents_filter_by_status(client, seed_documents):
    resp = client.get("/v1/documents", params={"review_status": "needs_review"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["documents"][0]["review_status"] == "needs_review"


# --- GET /v1/documents/{document_id} ---


def test_get_document(client, seed_documents):
    resp = client.get("/v1/documents/doc-1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "doc-1"


def test_get_document_not_found(client):
    resp = client.get("/v1/documents/nonexistent")
    assert resp.status_code == 404


# --- POST /v1/documents/{id}/approve ---


def test_approve_document(client, seed_documents):
    resp = client.post(
        "/v1/documents/doc-1/approve",
        headers={"X-Actor": "spoofed@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "approved"
    assert data["reviewed_by"] == "anonymous"


def test_approve_document_uses_authenticated_principal(client, seed_documents):
    resp = client.post("/v1/documents/doc-1/approve")
    assert resp.status_code == 200
    assert resp.json()["reviewed_by"] == "anonymous"


# --- POST /v1/documents/{id}/reject ---


def test_reject_document(client, seed_documents):
    resp = client.post(
        "/v1/documents/doc-1/reject",
        headers={"X-Actor": "spoofed@example.com", "X-Reason": "bad quality"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["review_status"] == "rejected"
    assert data["reviewed_by"] == "anonymous"
    assert data["review_reason"] == "bad quality"


# --- PATCH /v1/documents/{id}/fields ---


def test_patch_document_fields(client, seed_documents):
    resp = client.patch(
        "/v1/documents/doc-1/fields",
        json={"vendor": "New Corp"},
        headers={"X-Actor": "spoofed@example.com"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["structured_json"]["vendor"] == "New Corp"
    assert data["reviewed_by"] == "anonymous"


def test_patch_document_fields_uses_authenticated_principal(client, seed_documents):
    resp = client.patch(
        "/v1/documents/doc-1/fields",
        json={"vendor": "New Corp"},
    )
    assert resp.status_code == 200
    assert resp.json()["reviewed_by"] == "anonymous"
