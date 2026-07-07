"""Tests for /v1/search endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.v1.search import _repository, _get_search_service
from app.services.search.service import SearchService


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_index():
    """Reset the in-memory search index between tests."""
    _repository._chunks.clear()
    _repository._document_index.clear()
    yield
    _repository._chunks.clear()
    _repository._document_index.clear()


@pytest.mark.asyncio
async def test_search_endpoint_returns_200(client):
    # Index a document first
    svc = _get_search_service()
    await svc.index_document(
        "doc-1",
        {"issuer_name": "Test Vendor", "line_items": [{"description": "Widget"}]},
    )

    resp = client.get("/v1/search", params={"q": "Widget"})
    assert resp.status_code == 200
    body = resp.json()
    assert "results" in body
    assert body["query"] == "Widget"
    assert isinstance(body["results"], list)


@pytest.mark.asyncio
async def test_search_keyword_mode(client):
    svc = _get_search_service()
    await svc.index_document(
        "doc-1",
        {"issuer_name": "Acme", "line_items": [{"description": "Service fee"}]},
    )

    resp = client.get("/v1/search", params={"q": "Service", "mode": "keyword"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "keyword"
    assert len(body["results"]) > 0


def test_search_missing_query_returns_422(client):
    resp = client.get("/v1/search")
    assert resp.status_code == 422
