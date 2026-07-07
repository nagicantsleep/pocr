from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.document_store import DocumentStore, StoredDocument


@pytest.fixture
def store():
    return DocumentStore()


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


# --- store + get ---


def test_store_and_get(store):
    doc = _make_doc()
    store.store(doc)
    found = store.get("doc-1")
    assert found is not None
    assert found.id == "doc-1"
    assert found.document_type == "qualified_invoice"


def test_get_nonexistent_returns_none(store):
    assert store.get("nonexistent") is None


# --- list with review_status filter ---


def test_list_filter_by_review_status(store):
    store.store(_make_doc("doc-1", review_status="pending"))
    store.store(_make_doc("doc-2", review_status="approved"))
    store.store(_make_doc("doc-3", review_status="pending"))

    result = store.list_documents(review_status="pending")
    assert len(result) == 2
    assert all(d.review_status == "pending" for d in result)


def test_list_filter_by_document_type(store):
    store.store(_make_doc("doc-1", document_type="qualified_invoice"))
    store.store(_make_doc("doc-2", document_type="receipt"))

    result = store.list_documents(document_type="receipt")
    assert len(result) == 1
    assert result[0].id == "doc-2"


# --- list with pagination ---


def test_list_pagination_limit(store):
    for i in range(5):
        store.store(_make_doc(f"doc-{i}"))

    result = store.list_documents(limit=3)
    assert len(result) == 3


def test_list_pagination_offset(store):
    for i in range(5):
        store.store(_make_doc(f"doc-{i}"))

    all_docs = store.list_documents(limit=100)
    page = store.list_documents(limit=2, offset=2)
    assert len(page) == 2
    assert page[0].id == all_docs[2].id


# --- update_status ---


def test_update_status_changes_status(store):
    store.store(_make_doc())
    updated = store.update_status("doc-1", "approved", "alice", "looks good")
    assert updated is not None
    assert updated.review_status == "approved"
    assert updated.reviewed_by == "alice"
    assert updated.review_reason == "looks good"


def test_update_status_nonexistent_returns_none(store):
    assert store.update_status("nonexistent", "approved", "alice") is None


# --- patch_fields ---


def test_patch_fields_updates_fields(store):
    store.store(_make_doc())
    updated = store.patch_fields("doc-1", {"vendor": "New Corp"}, "bob")
    assert updated is not None
    assert updated.structured_json["vendor"] == "New Corp"
    assert updated.reviewed_by == "bob"


def test_patch_fields_preserves_existing(store):
    store.store(_make_doc())
    store.patch_fields("doc-1", {"vendor": "New Corp"}, "bob")
    doc = store.get("doc-1")
    assert doc.structured_json["total"] == 1000


def test_patch_fields_nonexistent_returns_none(store):
    assert store.patch_fields("nonexistent", {}, "bob") is None


# --- count ---


def test_count_returns_total(store):
    for i in range(3):
        store.store(_make_doc(f"doc-{i}"))
    assert store.count() == 3


def test_count_with_filter(store):
    store.store(_make_doc("doc-1", review_status="pending"))
    store.store(_make_doc("doc-2", review_status="approved"))
    store.store(_make_doc("doc-3", review_status="pending"))
    assert store.count(review_status="pending") == 2
    assert store.count(review_status="approved") == 1
