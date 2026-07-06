"""Tests for invoice schemas."""

from app.schemas.invoice import (
    InvoiceData,
    InvoiceDebugResponse,
    InvoiceExtractResponse,
    InvoiceLineItem,
    InvoiceValidationResult,
    TaxBreakdown,
    ValidationIssue,
)


class TestInvoiceLineItem:
    def test_creation_minimal(self):
        item = InvoiceLineItem(line_no=1)
        assert item.line_no == 1
        assert item.description is None
        assert item.quantity is None

    def test_creation_full(self):
        item = InvoiceLineItem(
            line_no=1,
            description="Widget",
            item_code="W-001",
            quantity=10,
            unit="pcs",
            unit_price=100,
            tax_rate="10%",
            tax_amount=80,
            amount_excluding_tax=800,
            amount_including_tax=880,
        )
        assert item.description == "Widget"
        assert item.amount_including_tax == 880


class TestTaxBreakdown:
    def test_aliases(self):
        tb = TaxBreakdown(**{"8%": 100, "10%": 200})
        assert tb.eight_pct == 100
        assert tb.ten_pct == 200

    def test_default_none(self):
        tb = TaxBreakdown()
        assert tb.eight_pct is None
        assert tb.ten_pct is None

    def test_roundtrip_dict(self):
        tb = TaxBreakdown(eight_pct=50, ten_pct=150)
        d = tb.model_dump(by_alias=True, mode="json")
        assert d.get("8%") == 50
        assert d.get("10%") == 150


class TestValidationIssue:
    def test_creation(self):
        vi = ValidationIssue(code="missing_total", severity="warning", message="No total found")
        assert vi.code == "missing_total"


class TestInvoiceValidationResult:
    def test_valid_default(self):
        vr = InvoiceValidationResult(is_valid=True)
        assert vr.is_valid is True
        assert vr.warnings == []
        assert vr.errors == []


class TestInvoiceExtractResponse:
    def test_default_creation(self):
        resp = InvoiceExtractResponse(request_id="test-123", status="success")
        assert resp.request_id == "test-123"
        assert resp.status == "success"
        assert resp.document_type is None
        assert resp.invoice.line_items == []
        assert resp.line_items_status == "not_extracted"
        assert resp.validation.is_valid is True
        assert resp.needs_review is False

    def test_exclude_none(self):
        resp = InvoiceExtractResponse(request_id="r1", status="success")
        d = resp.model_dump(exclude_none=True)
        assert "document_type" not in d or d["document_type"] is None
        assert "confidence" not in d or d.get("confidence") is None


class TestInvoiceDebugResponse:
    def test_has_extra_fields(self):
        resp = InvoiceDebugResponse(request_id="r1", status="success")
        assert resp.layout is None
        assert resp.regex_candidates is None
        assert resp.table_candidates is None
        assert resp.validation_trace is None

    def test_inherits_invoice_fields(self):
        resp = InvoiceDebugResponse(
            request_id="r1",
            status="success",
            line_items_status="extracted",
        )
        assert resp.line_items_status == "extracted"
        assert resp.invoice.line_items == []
