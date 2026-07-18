"""Route-level integration proof for the JP invoice upload workflow.

The upload test replaces only PaddleOCR with deterministic output. It still
exercises upload, async extraction, polling, review, search, and audit through
public HTTP routes.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.v1.search import _get_search_service, _repository
from app.services.audit_log import _store as _audit_store
from app.services.document_store import StoredDocument
from app.services.search.embeddings import EmbeddingService
from app.services.search.service import SearchService
from app.services.review_service import get_document_store

_FIXTURE_PNG = os.path.join(
    os.path.dirname(__file__),
    os.pardir,
    "fixtures",
    "invoice-jp",
    "clean",
    "sample_001.png",
)

SAMPLE_JP_FIELDS = {
    "issuer_name": "テスト株式会社",
    "issuer_registration_number": "T1234567890123",
    "total_amount": 115500,
    "transaction_date": "2026-01-15",
    "line_items": [
        {"description": "コンサルティング費用", "amount": 110000},
        {"description": "交通費", "amount": 5500},
    ],
}


def _fake_ocr_result() -> dict:
    """Return deterministic OCR output in the production adapter's shape."""
    return {
        "results": [
            {
                "text": "テスト株式会社",
                "confidence": 0.95,
                "bbox": {"top_left": [10, 10], "bottom_right": [200, 40]},
            },
            {
                "text": "登録番号 T1234567890123",
                "confidence": 0.98,
                "bbox": {"top_left": [10, 50], "bottom_right": [240, 80]},
            },
            {
                "text": "発行日 2026年1月15日",
                "confidence": 0.96,
                "bbox": {"top_left": [10, 90], "bottom_right": [220, 120]},
            },
            {
                "text": "ご請求金額 ¥115,500",
                "confidence": 0.97,
                "bbox": {"top_left": [10, 130], "bottom_right": [240, 160]},
            },
            {
                "text": "コンサルティング費用 1 ¥110,000 ¥110,000",
                "confidence": 0.90,
                "bbox": {"top_left": [10, 170], "bottom_right": [420, 200]},
            },
        ]
    }


def _make_doc(doc_id: str = "e2e-jp-001", **overrides) -> StoredDocument:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=doc_id,
        document_type="qualified_invoice",
        structured_json=SAMPLE_JP_FIELDS,
        confidence=0.85,
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
def search_svc():
    return SearchService(_repository, EmbeddingService(api_key=None))


# ---------------------------------------------------------------------------
# Route-level integration: upload -> extract -> approve -> search -> audit
# ---------------------------------------------------------------------------


def test_jp_invoice_e2e(client, monkeypatch):
    """Upload a PNG and complete the public HTTP workflow without skips."""
    monkeypatch.setattr(
        "app.routers.v1.invoice_jp.run_ocr",
        lambda _content, lang: _fake_ocr_result(),
    )

    # 1. Upload image via POST /v1/invoice-jp/extract:async
    with open(_FIXTURE_PNG, "rb") as f:
        resp = client.post(
            "/v1/invoice-jp/extract:async",
            files={"file": ("sample_001.png", f, "image/png")},
        )

    assert resp.status_code == 200
    body = resp.json()
    job_id = body["job_id"]
    assert body["status"] == "received"
    assert job_id

    # 2. Poll job via /v1/jobs (contract endpoint) until done.
    poll_body = {}
    for _ in range(20):
        poll_resp = client.get(f"/v1/jobs/{job_id}")
        assert poll_resp.status_code == 200
        poll_body = poll_resp.json()
        if poll_body.get("status") in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert poll_body.get("status") == "completed", poll_body
    assert poll_body.get("results"), "Expected at least one result from extraction"
    document_id = poll_body["results"][0].get("document_id")
    assert document_id, "Job result must contain document_id"

    # 3. Verify extracted document is in DocumentStore
    doc_resp = client.get(f"/v1/invoice-jp/{document_id}")
    assert doc_resp.status_code == 200
    doc = doc_resp.json()
    assert doc["document_id"] == document_id
    assert "fields" in doc
    assert doc["fields"]["issuer_registration_number"]["value"] == "T1234567890123"
    assert doc["fields"]["total_amount"]["value"] == 115500

    # 4. Document is indexed for search by the extraction pipeline

    # 5. Approve via /v1/documents/{id}/approve
    approve_resp = client.post(
        f"/v1/documents/{document_id}/approve",
        headers={"X-Actor": "e2e-tester"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["review_status"] == "approved"

    # 6. Search — keyword mode to avoid embedding dependency
    search_resp = client.get(
        "/v1/search",
        params={"q": "テスト", "mode": "keyword"},
    )
    assert search_resp.status_code == 200
    hits = search_resp.json()
    assert hits["total"] > 0
    assert any(r["document_id"] == document_id for r in hits["results"])

    # 7. Audit log records the approve action
    audit_resp = client.get(
        "/v1/audit",
        params={"document_id": document_id},
    )
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    assert any(e["action"] == "approve" for e in entries)
    assert any(e["actor"] == "anonymous" for e in entries)


# ---------------------------------------------------------------------------
# Store-level variant: bypasses OCR to prove the flow works with known data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jp_invoice_e2e_via_store(client, search_svc):
    """Seed via DocumentStore -> approve -> search -> audit.

    This variant creates a document directly (simulating extraction output)
    so the search and review steps can be tested with known-good data.
    """
    # 1. Create a document via DocumentStore directly
    doc = _make_doc("e2e-jp-002")
    store = get_document_store()
    store.store(doc)

    # 2. Index for search
    await search_svc.index_document("e2e-jp-002", SAMPLE_JP_FIELDS)

    # 3. Approve via /v1/documents/{id}/approve
    approve_resp = client.post(
        "/v1/documents/e2e-jp-002/approve",
        headers={"X-Actor": "e2e-tester"},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["review_status"] == "approved"
    assert approve_resp.json()["reviewed_by"] == "anonymous"

    # 4. Document status persisted
    doc_resp = client.get("/v1/documents/e2e-jp-002")
    assert doc_resp.status_code == 200
    assert doc_resp.json()["review_status"] == "approved"

    # 5. Search — keyword search for issuer name
    search_resp = client.get(
        "/v1/search",
        params={"q": "テスト株式会社", "mode": "keyword"},
    )
    assert search_resp.status_code == 200
    hits = search_resp.json()
    assert hits["total"] > 0
    assert any(r["document_id"] == "e2e-jp-002" for r in hits["results"])

    # 6. Audit log contains the approve action
    audit_resp = client.get(
        "/v1/audit",
        params={"document_id": "e2e-jp-002"},
    )
    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    approve_entries = [e for e in entries if e["action"] == "approve"]
    assert len(approve_entries) == 1
    assert approve_entries[0]["actor"] == "anonymous"


# ---------------------------------------------------------------------------
# Kernel-level proof: exercises ExtractionKernel directly with synthetic OCR
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jp_invoice_kernel_extraction(client):
    """Kernel-level e2e: feeds synthetic OCR items directly to ExtractionKernel.

    Proves the schema-driven extraction pipeline produces correct structured_json
    independent of OCR engine availability. This is the real proof artifact.
    """
    from app.services.extraction_kernel.kernel import ExtractionKernel
    from app.services.extraction_kernel.source_registry import source_registry
    from app.services.extraction_kernel.receipt_source_registry import register_receipt_sources
    from app.schemas.registry.schema_registry import SchemaRegistry

    # Ensure receipt sources are registered on the module-level registry
    register_receipt_sources(source_registry)
    kernel = ExtractionKernel(source_registry)

    schema_registry = SchemaRegistry(schemas_dir="app/schemas/registry")
    schema_registry.load()
    schema = schema_registry.get("invoice-jp", "1.0.0")
    assert schema is not None

    # Simulated OCR output from a clean JP invoice
    ocr_items = [
        {"text": "テスト株式会社", "confidence": 0.95, "bbox": {"top_left": [100, 50], "bottom_right": [300, 80]}},
        {"text": "登録番号 T1234567890123", "confidence": 0.98, "bbox": {"top_left": [100, 90], "bottom_right": [350, 110]}},
        {"text": "発行日 2026年1月15日", "confidence": 0.96, "bbox": {"top_left": [100, 120], "bottom_right": [300, 140]}},
        {"text": "ご請求金額 ¥115,500", "confidence": 0.97, "bbox": {"top_left": [100, 150], "bottom_right": [350, 170]}},
        {"text": "小計 ¥100,000", "confidence": 0.94, "bbox": {"top_left": [100, 180], "bottom_right": [300, 200]}},
        {"text": "消費税 ¥15,500", "confidence": 0.93, "bbox": {"top_left": [100, 210], "bottom_right": [300, 230]}},
        {"text": "コンサルティング費用 1 ¥100,000 ¥100,000", "confidence": 0.90, "bbox": {"top_left": [100, 250], "bottom_right": [500, 270]}},
    ]

    result = kernel.extract(schema, ocr_items)

    # Registration number extraction is the strictest — if kernel works, this passes
    reg_no = result.fields.get("issuer_registration_number")
    assert reg_no is not None, "issuer_registration_number should be extracted"
    assert reg_no.value is not None, "registration number value should not be None"
    # The regex source should find T1234567890123
    assert "T1234567890123" in str(reg_no.value), f"Expected T1234567890123, got {reg_no.value}"

    # Schema loads and kernel processes without error
    assert result.schema_id == "invoice-jp"
    assert result.document_type == "qualified_invoice"

    # Total amount should be extracted
    total = result.fields.get("total_amount")
    assert total is not None, "total_amount should be extracted"
    assert total.value is not None, "total_amount value should not be None"
