"""Tests for app.services.extraction_kernel.legacy_adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.schemas.registry import SchemaRegistry
from app.services.extraction_kernel.kernel import ExtractionKernel, ExtractionResult, FieldResult
from app.services.extraction_kernel.legacy_adapter import LegacyInvoiceAdapter
from app.services.extraction_kernel.source_registry import SourceRegistry

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas" / "registry"


@pytest.fixture
def schema_registry() -> SchemaRegistry:
    reg = SchemaRegistry(REGISTRY_DIR)
    reg.load()
    return reg


@pytest.fixture
def mock_kernel() -> ExtractionKernel:
    return MagicMock(spec=ExtractionKernel)


@pytest.fixture
def adapter(mock_kernel: MagicMock, schema_registry: SchemaRegistry) -> LegacyInvoiceAdapter:
    return LegacyInvoiceAdapter(kernel=mock_kernel, schema_registry=schema_registry)


class TestLegacyInvoiceAdapterExtract:
    def test_extract_returns_expected_keys(self, adapter: LegacyInvoiceAdapter, mock_kernel: MagicMock):
        mock_kernel.extract.return_value = ExtractionResult(
            schema_id="invoice-jp",
            document_type="qualified_invoice",
            fields={
                "issuer_name": FieldResult(value="テスト株式会社", confidence=0.95, source_used="regex_vendor"),
                "total_amount": FieldResult(value=10000, confidence=0.90, source_used="layout_label_total"),
            },
            overall_confidence=0.92,
            needs_review=False,
            validation_errors=[],
            validation_warnings=[],
        )

        ocr_results = [{"text": "テスト株式会社 合計 ¥10,000"}]
        response = adapter.extract(ocr_results, request_id="test-123")

        assert response["request_id"] == "test-123"
        assert response["status"] == "completed"
        assert response["document_type"] == "qualified_invoice"
        assert "invoice" in response
        assert "confidence" in response
        assert "needs_review" in response
        assert "validation" in response
        assert response["validation"]["is_valid"] is True

    def test_extract_invoice_fields_values(self, adapter: LegacyInvoiceAdapter, mock_kernel: MagicMock):
        mock_kernel.extract.return_value = ExtractionResult(
            schema_id="invoice-jp",
            document_type="qualified_invoice",
            fields={
                "issuer_name": FieldResult(value="テスト株式会社", confidence=0.95, source_used="regex_vendor"),
                "total_amount": FieldResult(value=10000, confidence=0.90, source_used="layout_label_total"),
            },
            overall_confidence=0.92,
            needs_review=False,
            validation_errors=[],
            validation_warnings=[],
        )

        response = adapter.extract([{"text": "dummy"}], request_id="r1")
        assert response["invoice"]["issuer_name"] == "テスト株式会社"
        assert response["invoice"]["total_amount"] == 10000

    def test_extract_with_validation_errors(self, adapter: LegacyInvoiceAdapter, mock_kernel: MagicMock):
        mock_kernel.extract.return_value = ExtractionResult(
            schema_id="invoice-jp",
            document_type="qualified_invoice",
            fields={},
            overall_confidence=0.0,
            needs_review=True,
            validation_errors=[{"code": "missing", "field": "issuer_name", "severity": "error", "message": "Required"}],
            validation_warnings=[],
        )

        response = adapter.extract([{"text": "dummy"}])
        assert response["validation"]["is_valid"] is False
        assert len(response["validation"]["errors"]) == 1
        assert response["needs_review"] is True


class TestLegacyInvoiceAdapterExtractReceipt:
    def test_extract_receipt(self, adapter: LegacyInvoiceAdapter, mock_kernel: MagicMock):
        mock_kernel.extract.return_value = ExtractionResult(
            schema_id="receipt-jp",
            document_type="receipt",
            fields={
                "store_name": FieldResult(value="コンビニ", confidence=0.9, source_used="layout_header"),
                "total_amount": FieldResult(value=500, confidence=0.85, source_used="layout_label_total"),
            },
            overall_confidence=0.87,
            needs_review=False,
            validation_errors=[],
            validation_warnings=[],
        )

        response = adapter.extract_receipt([{"text": "コンビニ ¥500"}], request_id="r2")
        assert response["document_type"] == "receipt"
        assert response["invoice"]["store_name"] == "コンビニ"
        assert response["request_id"] == "r2"

    def test_missing_receipt_schema_raises(self, mock_kernel: MagicMock):
        empty_registry = SchemaRegistry(REGISTRY_DIR)
        empty_registry.load = lambda: None  # no schemas loaded
        adapter = LegacyInvoiceAdapter(kernel=mock_kernel, schema_registry=empty_registry)

        with pytest.raises(ValueError, match="receipt-jp"):
            adapter.extract_receipt([{"text": "dummy"}])


class TestLegacyInvoiceAdapterMissingSchema:
    def test_missing_invoice_schema_raises(self, mock_kernel: MagicMock):
        empty_registry = SchemaRegistry(REGISTRY_DIR)
        empty_registry.load = lambda: None
        adapter = LegacyInvoiceAdapter(kernel=mock_kernel, schema_registry=empty_registry)

        with pytest.raises(ValueError, match="invoice-jp"):
            adapter.extract([{"text": "dummy"}])


class TestLegacyResponseGeneration:
    def test_request_id_generated(self, adapter: LegacyInvoiceAdapter, mock_kernel: MagicMock):
        mock_kernel.extract.return_value = ExtractionResult(
            schema_id="invoice-jp",
            document_type="qualified_invoice",
            fields={},
            overall_confidence=0.0,
            needs_review=False,
            validation_errors=[],
            validation_warnings=[],
        )

        response = adapter.extract([{"text": "dummy"}])
        assert response["request_id"]  # auto-generated UUID
        assert len(response["request_id"]) > 0
