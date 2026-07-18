from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthenticatedPrincipal, require_document_reviewer, require_operator
from app.main import app
from app.routers.v1.search import _get_search_service, _repository
from app.services.audit_log import AuditAction, _store as audit_store, get_audit_log_service
from app.services.document_store import StoredDocument
from app.services.review_service import get_document_store


def _principal(tenant_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        tenant_id=tenant_id,
        user_id=f"{tenant_id}-reviewer",
        roles=frozenset({"reviewer"}),
    )


def _document(document_id: str, tenant_id: str) -> StoredDocument:
    now = datetime.now(timezone.utc)
    return StoredDocument(
        id=document_id,
        tenant_id=tenant_id,
        document_type="qualified_invoice",
        structured_json={"issuer_name": f"{tenant_id} vendor"},
        confidence=0.9,
        needs_review=True,
        review_status="needs_review",
        created_at=now,
        updated_at=now,
    )


@pytest.fixture(autouse=True)
def _clear_state():
    store = get_document_store()
    store._documents.clear()
    audit_store.clear()
    _repository._chunks.clear()
    _repository._document_index.clear()
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    store._documents.clear()
    audit_store.clear()
    _repository._chunks.clear()
    _repository._document_index.clear()


def _use_tenant(tenant_id: str) -> None:
    principal = _principal(tenant_id)
    app.dependency_overrides[require_operator] = lambda: principal
    app.dependency_overrides[require_document_reviewer] = lambda: principal


def test_document_and_audit_routes_hide_other_tenant_records():
    store = get_document_store()
    store.store(_document("tenant-a-doc", "tenant-a"))
    tenant_b_document = _document("tenant-b-doc", "tenant-b")
    store.store(tenant_b_document)

    audit = get_audit_log_service()
    import asyncio

    asyncio.run(
        audit.log(
            document_id="tenant-a-doc",
            action=AuditAction.CREATE,
            actor="tenant-a-reviewer",
            tenant_id="tenant-a",
        )
    )
    asyncio.run(
        audit.log(
            document_id="tenant-b-doc",
            action=AuditAction.CREATE,
            actor="tenant-b-reviewer",
            tenant_id="tenant-b",
        )
    )

    _use_tenant("tenant-a")
    client = TestClient(app)

    assert client.get("/v1/documents").json()["total"] == 1
    assert client.get("/v1/documents/tenant-b-doc").status_code == 404
    assert client.post("/v1/documents/tenant-b-doc/approve").status_code == 404
    assert tenant_b_document.review_status == "needs_review"

    audit_entries = client.get("/v1/audit").json()["entries"]
    assert [entry["document_id"] for entry in audit_entries] == ["tenant-a-doc"]


@pytest.mark.asyncio
async def test_search_route_hides_other_tenant_chunks():
    search = _get_search_service()
    await search.index_document(
        "tenant-a-doc",
        {"issuer_name": "Tenant A Supplier"},
        tenant_id="tenant-a",
    )
    await search.index_document(
        "tenant-b-doc",
        {"issuer_name": "Tenant B Supplier"},
        tenant_id="tenant-b",
    )

    _use_tenant("tenant-a")
    response = TestClient(app).get("/v1/search", params={"q": "Supplier", "mode": "keyword"})

    assert response.status_code == 200
    assert {item["document_id"] for item in response.json()["results"]} == {"tenant-a-doc"}
