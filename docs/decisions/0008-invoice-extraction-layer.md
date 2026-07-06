# 0008 Invoice Extraction as a Separate Layer Above PaddleOCR

Date: 2026-06-25

## Status

Accepted

## Context

Japanese qualified invoice fields (registration number, tax breakdown, line items, issuer/recipient) need specialized extraction beyond what generic structured OCR provides. The existing `StructuredOCRData` schema has generic fields (`vendorName`, `totalAmount`, `taxes`, `inputCostItems`) that do not map cleanly to Japanese invoice requirements such as per-rate tax breakdowns, registration number validation, or line-item table reconstruction.

Key constraints:

- Must not break existing `/ocr` or `/ocr/structured` endpoints
- No existing invoice fixtures or golden parser tests
- Invoices contain sensitive financial and tax data
- ERP integration requires deterministic, validated output

## Decision

Add invoice extraction as a separate layer with its own router, schemas, and service modules above the existing PaddleOCR evidence layer. Keep invoice schemas separate from `StructuredOCRData`. Synchronous MVP first; durable invoice jobs added later when batch or production workloads require them.

Architecture:

- New router: `app/routers/invoice.py`
- New schemas: `app/schemas/invoice.py`
- New services: `layout_analyzer`, `invoice_rules`, `invoice_extractor`, `table_reconstructor`, `column_inference`, `invoice_validator`, `invoice_confidence`
- Reuse: existing OCR normalization, API-key auth, error envelope, metrics style, PostgreSQL/Kafka worker pattern

## Alternatives Considered

1. Extend `StructuredOCRData` with invoice-specific fields — rejected because it couples unrelated concerns and forces invoice semantics into generic OCR output.
2. LLM-first extraction — rejected because deterministic rule-based MVP is needed first for validation baseline and to avoid hallucinated fields in financial data.
3. Separate microservice — rejected because the existing monolith already handles OCR and the invoice layer is a natural extension within the same process.

## Consequences

Positive:

- Clean separation of concerns between generic OCR and invoice-specific extraction
- Invoice schemas can evolve independently without affecting existing structured OCR consumers
- Reuse of existing infrastructure (auth, error handling, OCR pipeline, worker pattern)
- Deterministic rule-based extraction suitable for ERP integration and auto-approval

Tradeoffs:

- New public API contract to maintain (`/invoice/*` endpoints and response schemas)
- Separate schema maintenance from `StructuredOCRData`
- Initial implementation requires substantial new service code (layout analyzer, table reconstructor, validators)

## Follow-Up

- Decision on storage/audit direction for production persistence (Sprint 8-9 boundary)
- Decision on LLM/VLM fallback provider selection (Sprint 10, future)
- Evaluation dataset thresholds review after real invoice data is available
