"""E2E tests for the review workflow: approve, reject, patch, list, search."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.v1.search import _repository, _get_search_service
from app.services.audit_log import _store as _audit_store
from app.services.document_store import StoredDocument
from app.services.search.embeddings import EmbeddingService
from app.services.search.repository import SearchRepository
from app.services.search.service import SearchService
from app.services.review_service import get_document_store


def _make_doc(doc_id: str = "e2e-001", **overrides) -> StoredDocument:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=doc_id,
        document_type="qualified_invoice",
        structured_json={
            "issuer_name": "テスト株式会社",
            "issuer_registration_number": "T1234567890123",
            "total_amount": 100000,
            "transaction_date": "2024-06-15",
        },
        confidence=0.82,
        needs_review=True,
        review_status="pending",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return StoredDocument(**defaults)


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset in-memory stores between tests."""
    store = get_document_store()
    store._documents.clear()
    _audit_store.clear()
    _repository._chunks.clear()
    _repository._document_index.clear()
    yield
    store._documents.clear()
    _audit_store.clear()
    _repository._chunks.clear()
    _repository._document_index.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def seeded_doc():
    store = get_document_store()
    doc = _make_doc("e2e-001", review_status="pending")
    store.store(doc)
    return doc


@pytest.fixture
def search_svc():
    return SearchService(_repository, EmbeddingService(api_key=None))


SAMPLE_JP_INVOICE = {
    "issuer_name": "テスト株式会社",
    "issuer_registration_number": "T1234567890123",
    "total_amount": 100000,
    "transaction_date": "2024-06-15",
    "line_items": [
        {"description": "コンサルティング費用", "amount": 80000},
        {"description": "交通費", "amount": 20000},
    ],
}


# --- Approve flow ---


@pytest.mark.asyncio
async def test_approve_persists_and_audits(client, seeded_doc):
    """Approve a document → status changes, audit log records action."""
    resp = client.post(
        "/v1/documents/e2e-001/approve",
        headers={"X-Actor": "alice@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "approved"
    assert resp.json()["reviewed_by"] == "alice@example.com"

    # Document reflects approved status
    doc_resp = client.get("/v1/documents/e2e-001")
    assert doc_resp.status_code == 200
    assert doc_resp.json()["review_status"] == "approved"

    # Audit log contains the approve action
    audit_resp = client.get("/v1/audit", params={"document_id": "e2e-001"})
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    assert any(e["action"] == "approve" for e in entries)


# --- Reject flow ---


@pytest.mark.asyncio
async def test_reject_persists_and_audits(client, seeded_doc):
    """Reject a document → status changes, audit log records action."""
    resp = client.post(
        "/v1/documents/e2e-001/reject",
        headers={"X-Actor": "bob@example.com", "X-Reason": "bad quality"},
    )
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "rejected"
    assert resp.json()["reviewed_by"] == "bob@example.com"
    assert resp.json()["review_reason"] == "bad quality"

    doc_resp = client.get("/v1/documents/e2e-001")
    assert doc_resp.status_code == 200
    assert doc_resp.json()["review_status"] == "rejected"

    audit_resp = client.get("/v1/audit", params={"document_id": "e2e-001"})
    entries = audit_resp.json()["entries"]
    assert any(e["action"] == "reject" for e in entries)


# --- Patch fields with audit ---


@pytest.mark.asyncio
async def test_patch_fields_with_audit(client, seeded_doc):
    """PATCH fields → fields changed, audit records action."""
    resp = client.patch(
        "/v1/documents/e2e-001/fields",
        json={"total_amount": 120000},
        headers={"X-Actor": "charlie@example.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["structured_json"]["total_amount"] == 120000
    assert resp.json()["reviewed_by"] == "charlie@example.com"

    doc_resp = client.get("/v1/documents/e2e-001")
    assert doc_resp.status_code == 200
    assert doc_resp.json()["structured_json"]["total_amount"] == 120000

    audit_resp = client.get("/v1/audit", params={"document_id": "e2e-001"})
    entries = audit_resp.json()["entries"]
    assert any(e["action"] == "patch" for e in entries)


# --- List filters by status ---


def test_list_filters_by_status(client):
    """List with review_status=approved → only approved documents."""
    store = get_document_store()
    store.store(_make_doc("list-001", review_status="pending"))
    store.store(_make_doc("list-002", review_status="approved"))
    store.store(_make_doc("list-003", review_status="approved"))
    store.store(_make_doc("list-004", review_status="rejected"))

    resp = client.get("/v1/documents", params={"review_status": "approved"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    for doc in data["documents"]:
        assert doc["review_status"] == "approved"


# --- Search after indexing ---


@pytest.mark.asyncio
async def test_search_after_indexing(client, search_svc):
    """Index a document via search service, search for its content → found."""
    await search_svc.index_document("search-001", SAMPLE_JP_INVOICE)

    resp = client.get("/v1/search", params={"q": "コンサルティング", "mode": "keyword"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] > 0
    assert any("search-001" in r["document_id"] for r in body["results"])
