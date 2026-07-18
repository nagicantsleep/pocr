from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.audit_log import AuditAction, AuditLogService, _store as _audit_store
from app.services.document_store import DocumentStore, StoredDocument
from app.services.review_service import ReviewService
from app.services.webhook_dispatch import WebhookDispatcher


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
def clear_audit_store():
    _audit_store.clear()
    yield
    _audit_store.clear()


@pytest.fixture
def doc_store():
    return DocumentStore()


@pytest.fixture
def audit_log():
    return AuditLogService()


@pytest.fixture
def webhook_dispatcher():
    return WebhookDispatcher()


@pytest.fixture
def service(doc_store, audit_log, webhook_dispatcher):
    return ReviewService(doc_store, audit_log, webhook_dispatcher)


# --- approve ---


@pytest.mark.asyncio
async def test_approve_changes_status(service, doc_store):
    doc_store.store(_make_doc())
    result = await service.approve("doc-1", actor="alice", reason="looks correct")
    assert result.review_status == "approved"
    assert result.reviewed_by == "alice"
    assert result.review_reason == "looks correct"


@pytest.mark.asyncio
async def test_approve_logs_audit(service, doc_store, audit_log):
    doc_store.store(_make_doc())
    await service.approve("doc-1", actor="alice")
    entries, _ = await audit_log.list_entries(document_id="doc-1", action=AuditAction.APPROVE)
    assert len(entries) == 1
    assert entries[0].actor == "alice"


@pytest.mark.asyncio
async def test_approve_dispatches_webhook(service, doc_store, webhook_dispatcher):
    webhook_dispatcher.subscribe(url="https://example.com/hook", events=["document.review_completed"])
    doc_store.store(_make_doc())

    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        await service.approve("doc-1", actor="alice")

    subs = webhook_dispatcher.list_subscriptions()
    assert len(subs) == 1
    assert "document.review_completed" in subs[0].events


@pytest.mark.asyncio
async def test_approve_nonexistent_raises(service):
    with pytest.raises(ValueError, match="Document not found"):
        await service.approve("nonexistent", actor="alice")


# --- reject ---


@pytest.mark.asyncio
async def test_reject_changes_status(service, doc_store):
    doc_store.store(_make_doc())
    result = await service.reject("doc-1", actor="bob", reason="bad quality")
    assert result.review_status == "rejected"
    assert result.reviewed_by == "bob"
    assert result.review_reason == "bad quality"


@pytest.mark.asyncio
async def test_reject_logs_audit(service, doc_store, audit_log):
    doc_store.store(_make_doc())
    await service.reject("doc-1", actor="bob")
    entries, _ = await audit_log.list_entries(document_id="doc-1", action=AuditAction.REJECT)
    assert len(entries) == 1
    assert entries[0].actor == "bob"


@pytest.mark.asyncio
async def test_reject_dispatches_webhook(service, doc_store, webhook_dispatcher):
    webhook_dispatcher.subscribe(url="https://example.com/hook", events=["document.review_completed"])
    doc_store.store(_make_doc())

    mock_response = MagicMock()
    mock_response.status_code = 200
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        await service.reject("doc-1", actor="bob")

    subs = webhook_dispatcher.list_subscriptions()
    assert len(subs) == 1


@pytest.mark.asyncio
async def test_reject_nonexistent_raises(service):
    with pytest.raises(ValueError, match="Document not found"):
        await service.reject("nonexistent", actor="bob")


# --- patch_fields ---


@pytest.mark.asyncio
async def test_patch_fields_changes_data(service, doc_store):
    doc_store.store(_make_doc())
    result = await service.patch_fields("doc-1", {"vendor": "New Corp"}, actor="charlie")
    assert result.document.structured_json["vendor"] == "New Corp"
    assert result.document.reviewed_by == "charlie"
    assert result.warnings == []


@pytest.mark.asyncio
async def test_patch_fields_logs_audit_with_changes(service, doc_store, audit_log):
    doc_store.store(_make_doc())
    changes = {"vendor": "New Corp"}
    await service.patch_fields("doc-1", changes, actor="charlie")
    entries, _ = await audit_log.list_entries(document_id="doc-1", action=AuditAction.PATCH)
    assert len(entries) == 1
    assert entries[0].changes == changes


@pytest.mark.asyncio
async def test_patch_fields_nonexistent_raises(service):
    with pytest.raises(ValueError, match="Document not found"):
        await service.patch_fields("nonexistent", {}, actor="charlie")


# --- list_documents ---


@pytest.mark.asyncio
async def test_list_documents_returns_filtered(service, doc_store):
    doc_store.store(_make_doc("doc-1", review_status="pending"))
    doc_store.store(_make_doc("doc-2", review_status="approved"))
    doc_store.store(_make_doc("doc-3", review_status="pending"))

    result = await service.list_documents(review_status="pending")
    assert len(result["documents"]) == 2
    assert result["total"] == 2


@pytest.mark.asyncio
async def test_list_documents_pagination(service, doc_store):
    for i in range(5):
        doc_store.store(_make_doc(f"doc-{i}"))

    result = await service.list_documents(limit=2, offset=1)
    assert result["limit"] == 2
    assert result["offset"] == 1
    assert len(result["documents"]) == 2


@pytest.mark.asyncio
async def test_list_documents_total_matches_filter(service, doc_store):
    """Regression: count() must honor document_type filter so total == len(slice)."""
    doc_store.store(_make_doc("doc-1", document_type="qualified_invoice", review_status="pending"))
    doc_store.store(_make_doc("doc-2", document_type="qualified_invoice", review_status="approved"))
    doc_store.store(_make_doc("doc-3", document_type="receipt", review_status="pending"))

    result = await service.list_documents(
        review_status="pending", document_type="qualified_invoice",
    )
    assert len(result["documents"]) == 1
    assert result["total"] == 1, "total must reflect both filters, not just review_status"


@pytest.mark.asyncio
async def test_patch_fields_blocked_on_approved(service, doc_store):
    """Regression: PATCH on approved/rejected docs requires force=True."""
    approved = StoredDocument(
        id="doc-approved",
        document_type="x",
        structured_json={"a": 1},
        confidence=1.0,
        needs_review=False,
        review_status="approved",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doc_store.store(approved)
    with pytest.raises(PermissionError, match="without X-Force"):
        await service.patch_fields("doc-approved", {"a": 2}, actor="x")


@pytest.mark.asyncio
async def test_patch_fields_force_overrides_status_guard(service, doc_store):
    approved = StoredDocument(
        id="doc-approved",
        document_type="x",
        structured_json={"a": 1},
        confidence=1.0,
        needs_review=False,
        review_status="approved",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doc_store.store(approved)
    result = await service.patch_fields("doc-approved", {"a": 2}, actor="x", force=True)
    assert result.document.structured_json["a"] == 2


# --- patch_fields search re-index ---


@pytest.mark.asyncio
async def test_patch_fields_reindexes_search(service, doc_store):
    """patch_fields should remove old search chunks and re-index."""
    doc = _make_doc()
    doc_store.store(doc)

    mock_search = AsyncMock()
    mock_search.remove_document = AsyncMock()
    mock_search.index_document = AsyncMock(return_value=3)

    with patch("app.routers.v1.search._get_search_service", return_value=mock_search):
        result = await service.patch_fields(
            doc.id, {"vendor": "New Vendor"}, actor="user@test",
        )

    assert result.document.structured_json.get("vendor") == "New Vendor"
    assert result.warnings == []
    mock_search.remove_document.assert_awaited_once_with(doc.id)
    mock_search.index_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_fields_continues_if_search_fails(service, doc_store):
    """patch_fields should succeed even if search re-index fails."""
    doc = _make_doc()
    doc_store.store(doc)

    mock_search = AsyncMock()
    mock_search.remove_document = AsyncMock(side_effect=Exception("search down"))

    with patch("app.routers.v1.search._get_search_service", return_value=mock_search):
        result = await service.patch_fields(
            doc.id, {"vendor": "New Vendor"}, actor="user@test",
        )

    assert result.document.structured_json.get("vendor") == "New Vendor"
    assert len(result.warnings) == 1
    assert "Search re-index failed" in result.warnings[0]
