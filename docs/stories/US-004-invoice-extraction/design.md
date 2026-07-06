# Design

## Domain Model

Invoice extraction is a separate layer above the existing OCR evidence layer. PaddleOCR provides raw text boxes; the invoice layer sorts, merges, classifies, extracts fields, validates, and scores confidence.

Key entities:

- `InvoiceData` — all extracted invoice fields
- `InvoiceLineItem` — single line item with amounts, tax rate, confidence
- `TaxBreakdown` — per-rate subtotal and tax amounts
- `FieldEvidence` — source text, bbox, confidence, candidate rank per field
- `ValidationIssue` — code, severity, message per validation check
- `InvoiceValidationResult` — is_valid, warnings, errors
- `InvoiceExtractResponse` — top-level response envelope

## Application Flow

```
image/base64
  -> existing PaddleOCR evidence extraction (reuse process_single_image)
  -> layout_analyzer: sort, merge, classify blocks, detect table candidates
  -> invoice_rules: Japanese regex candidate extraction
  -> invoice_extractor: orchestrate header/footer, totals, tax, line items
  -> table_reconstructor + column_inference: line-item table pipeline
  -> invoice_validator: tax math, required fields, format checks
  -> invoice_confidence: field and line-item confidence scores
  -> InvoiceExtractResponse with needs_review flag
```

## Interface Contract

MVP endpoints (Sprint 1):

- `POST /invoice/extract` — `multipart/form-data`, `X-Lang: japan`, `X-Review-Threshold: 0.85`
- `POST /invoice/extract/json` — JSON body with base64 image
- `POST /invoice/debug` — same input, extended response with layout/candidates/validation trace

All endpoints use existing `verify_api_key` dependency. Error responses use existing `ErrorResponse` shape.

## Architecture

New files:

```
app/routers/invoice.py          — FastAPI router, auth, request handling
app/schemas/invoice.py          — Pydantic contracts (separate from StructuredOCRData)
app/services/layout_analyzer.py — OCR line sort, merge, block classification, table candidates
app/services/invoice_rules.py   — Japanese regex and candidate extraction
app/services/invoice_extractor.py — orchestrates layout, header/footer, totals, line items
app/services/table_reconstructor.py — table region detection, row grouping, cell assignment
app/services/column_inference.py   — column header detection and inference
app/services/invoice_validator.py  — tax math, required fields, format validation
app/services/invoice_confidence.py — field and line-item confidence scoring
app/utils/japanese_text.py      — Japanese text normalization
app/utils/money.py              — JPY amount parsing
app/utils/dates.py              — Japanese date parsing (Western + Reiwa)
app/utils/tax.py                — tax rounding utilities
```

Layer rule: routers own FastAPI types; services receive typed DTOs; no service reads env vars directly.

## Separation from StructuredOCRData

Invoice schemas are kept separate from the existing `StructuredOCRData` to avoid coupling. Mapping will be added only if a downstream consumer explicitly requires it.

## Key Decision

Synchronous MVP first, durable invoice jobs later (see `docs/decisions/0008-invoice-extraction-layer.md`).

## Alternatives Considered

1. Extend `StructuredOCRData` with invoice fields — rejected, couples unrelated concerns.
2. LLM-first extraction — rejected, deterministic rule-based MVP needed first for validation baseline.
