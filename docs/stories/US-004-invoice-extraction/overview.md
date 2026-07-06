# Overview

## Current Behavior

POCR provides generic OCR text extraction (`/ocr`, `/ocr/json`, `/ocr/batch`) and structured standardization (`/ocr/structured`, `/ocr/structured/jobs/{job_id}`). The structured output uses `StructuredOCRData` with generic fields (`vendorName`, `totalAmount`, `taxes`, `inputCostItems`). No invoice-specific extraction, field validation, or line-item parsing exists.

## Target Behavior

Add Japanese qualified invoice extraction as a new endpoint layer above PaddleOCR:

- `POST /invoice/extract` — multipart file upload, returns `InvoiceExtractResponse`
- `POST /invoice/extract/json` — base64 input, returns `InvoiceExtractResponse`
- `POST /invoice/debug` — returns OCR lines, layout blocks, regex candidates, table candidates, validation trace

Core fields extracted: registration number (`T` + 13 digits), transaction date (Western/Reiwa), invoice number, total amount, 8%/10% tax breakdown, issuer name, recipient name. Line items extracted for clear table regions. Field-level confidence and validation warnings/errors. `needs_review` flag computed from confidence thresholds and validation results.

Existing `/ocr/*` and `/ocr/structured*` endpoints remain unchanged.

## Affected Users

- API consumers integrating Japanese invoice ERP workflows
- Operations teams reviewing flagged invoices

## Affected Product Docs

- `docs/product/ocr-api.md` (add invoice endpoints)
- `README.md` (document invoice API usage)

## Non-Goals

- Replace PaddleOCR or weaken existing structured OCR behavior
- Vendor matching and duplicate detection (Sprint 8, future)
- Storage, audit logs, review workflow (Sprint 9, future)
- LLM/VLM fallback (Sprint 10, future)
- Evaluation dataset and accuracy reporting (Sprint 11, future)
