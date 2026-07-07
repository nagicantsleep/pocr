from __future__ import annotations

import pytest

from app.services.audit_log import AuditAction, AuditEntry, AuditLogService, _store


@pytest.fixture(autouse=True)
def clear_store():
    """Clear the in-memory store between tests."""
    _store.clear()
    yield
    _store.clear()


@pytest.fixture
def service():
    return AuditLogService()


# --- log ---


@pytest.mark.asyncio
async def test_log_creates_entry(service):
    entry = await service.log(
        document_id="doc-1",
        action=AuditAction.CREATE,
        actor="user-1",
        reason="initial creation",
    )
    assert isinstance(entry, AuditEntry)
    assert entry.document_id == "doc-1"
    assert entry.action == AuditAction.CREATE
    assert entry.actor == "user-1"
    assert entry.reason == "initial creation"
    assert entry.id  # non-empty uuid
    assert entry.created_at is not None


@pytest.mark.asyncio
async def test_log_with_changes(service):
    changes = {"vendor": {"old": "Acme", "new": "Acme Corp"}}
    entry = await service.log(
        document_id="doc-1",
        action=AuditAction.PATCH,
        actor="user-2",
        changes=changes,
    )
    assert entry.changes == changes


# --- list_entries ---


@pytest.mark.asyncio
async def test_list_returns_logged_entries(service):
    await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="user-1")
    await service.log(document_id="doc-1", action=AuditAction.APPROVE, actor="user-2")

    entries = await service.list_entries()
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_list_filter_by_document_id(service):
    await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="user-1")
    await service.log(document_id="doc-2", action=AuditAction.CREATE, actor="user-1")

    entries = await service.list_entries(document_id="doc-1")
    assert len(entries) == 1
    assert entries[0].document_id == "doc-1"


@pytest.mark.asyncio
async def test_list_filter_by_action(service):
    await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="user-1")
    await service.log(document_id="doc-1", action=AuditAction.APPROVE, actor="user-1")
    await service.log(document_id="doc-1", action=AuditAction.REJECT, actor="user-1")

    entries = await service.list_entries(action=AuditAction.APPROVE)
    assert len(entries) == 1
    assert entries[0].action == AuditAction.APPROVE


@pytest.mark.asyncio
async def test_list_filter_by_actor(service):
    await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="alice")
    await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="bob")

    entries = await service.list_entries(actor="alice")
    assert len(entries) == 1
    assert entries[0].actor == "alice"


@pytest.mark.asyncio
async def test_list_pagination_limit(service):
    for i in range(5):
        await service.log(document_id=f"doc-{i}", action=AuditAction.CREATE, actor="user")

    entries = await service.list_entries(limit=3)
    assert len(entries) == 3


@pytest.mark.asyncio
async def test_list_pagination_offset(service):
    for i in range(5):
        await service.log(document_id=f"doc-{i}", action=AuditAction.CREATE, actor="user")

    all_entries = await service.list_entries(limit=100)
    page = await service.list_entries(limit=2, offset=2)
    assert len(page) == 2
    assert page[0].id == all_entries[2].id


# --- get_entry ---


@pytest.mark.asyncio
async def test_get_entry_returns_entry(service):
    entry = await service.log(document_id="doc-1", action=AuditAction.CREATE, actor="user-1")
    found = await service.get_entry(entry.id)
    assert found is not None
    assert found.id == entry.id


@pytest.mark.asyncio
async def test_get_entry_bad_id_returns_none(service):
    found = await service.get_entry("nonexistent-id")
    assert found is None
