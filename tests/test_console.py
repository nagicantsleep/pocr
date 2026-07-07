"""Integration tests for the review console UI and v1 route smoke tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.audit_log import _store as _audit_store
from app.services.review_service import get_document_store


@pytest.fixture(autouse=True)
def _clear_stores():
    """Reset in-memory stores between tests."""
    store = get_document_store()
    store._documents.clear()
    _audit_store.clear()
    yield
    store._documents.clear()
    _audit_store.clear()


@pytest.fixture
def client():
    return TestClient(app)


# --- Console static asset tests ---


def test_console_page_loads(client):
    """GET /console/review returns HTML."""
    resp = client.get("/console/review")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "review" in resp.text.lower()


def test_console_css_loads(client):
    """GET /console/review.css returns CSS."""
    resp = client.get("/console/review.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


def test_console_js_loads(client):
    """GET /console/review.js returns JavaScript."""
    resp = client.get("/console/review.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]


def test_console_html_has_keyboard_script(client):
    """Console HTML includes keyboard shortcut handling."""
    resp = client.get("/console/review")
    assert resp.status_code == 200
    html = resp.text
    assert "keydown" in html or "addEventListener" in html


# --- V1 route smoke tests ---


def test_all_v1_routes_accessible(client):
    """Verify all v1 endpoints return valid responses."""
    # GET /v1/documents → 200 (empty list)
    resp = client.get("/v1/documents")
    assert resp.status_code == 200
    assert "documents" in resp.json()

    # GET /v1/audit → 200 (empty list)
    resp = client.get("/v1/audit")
    assert resp.status_code == 200
    assert "entries" in resp.json()

    # GET /v1/webhooks → 200 (empty list)
    resp = client.get("/v1/webhooks")
    assert resp.status_code == 200
    assert "subscriptions" in resp.json()

    # GET /v1/search without q → 422 (required param missing)
    resp = client.get("/v1/search")
    assert resp.status_code == 422

    # GET /console/review → 200
    resp = client.get("/console/review")
    assert resp.status_code == 200
