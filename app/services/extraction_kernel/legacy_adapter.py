"""Legacy adapter that bridges existing /invoice/* endpoints to the schema-driven kernel."""

from __future__ import annotations

import uuid
from typing import Any

from app.schemas.registry import SchemaDefinition, SchemaRegistry
from app.services.extraction_kernel import ExtractionKernel, ExtractionResult


class LegacyInvoiceAdapter:
    """Adapts legacy /invoice/* endpoints to use the schema-driven kernel."""

    def __init__(
        self, kernel: ExtractionKernel, schema_registry: SchemaRegistry
    ) -> None:
        self._kernel = kernel
        self._registry = schema_registry

    def extract(
        self, ocr_results: list[dict[str, Any]], request_id: str | None = None
    ) -> dict[str, Any]:
        """Extract invoice data using the schema-driven kernel.

        Returns a dict compatible with the legacy InvoiceExtractResponse format.
        """
        schema = self._registry.get("invoice-jp", "1.0.0")
        if schema is None:
            raise ValueError("invoice-jp v1.0.0 schema not found")

        result = self._kernel.extract(schema, ocr_results)
        return _to_legacy_response(result, request_id)

    def extract_receipt(
        self, ocr_results: list[dict[str, Any]], request_id: str | None = None
    ) -> dict[str, Any]:
        """Extract receipt-jp data."""
        schema = self._registry.get("receipt-jp", "1.0.0")
        if schema is None:
            raise ValueError("receipt-jp v1.0.0 schema not found")

        result = self._kernel.extract(schema, ocr_results)
        return _to_legacy_response(result, request_id)


def _to_legacy_response(
    result: ExtractionResult, request_id: str | None = None
) -> dict[str, Any]:
    """Convert ExtractionResult to a dict matching legacy response structure."""
    return {
        "request_id": request_id or str(uuid.uuid4()),
        "status": "completed",
        "document_type": result.document_type,
        "invoice": {field: fr.value for field, fr in result.fields.items()},
        "confidence": result.overall_confidence,
        "needs_review": result.needs_review,
        "validation": {
            "is_valid": len(result.validation_errors) == 0,
            "errors": result.validation_errors,
            "warnings": result.validation_warnings,
        },
    }
