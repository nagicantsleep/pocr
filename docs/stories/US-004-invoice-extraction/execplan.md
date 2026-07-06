# Exec Plan

## Goal

Add Japanese qualified invoice extraction to POCR as a new endpoint layer above PaddleOCR, enabling ERP integration, auto-approval, and line-item extraction.

## Scope

In scope:

- Invoice extraction endpoints (`/invoice/extract`, `/invoice/extract/json`, `/invoice/debug`)
- Layout normalization, Japanese regex extraction, line-item table reconstruction
- Validation engine and confidence scoring
- Batch endpoints and API hardening

Out of scope (future sprints):

- Vendor matching and duplicate detection (Sprint 8)
- Storage, audit, review workflow (Sprint 9)
- Optional LLM/VLM fallback (Sprint 10)
- Evaluation dataset and accuracy reporting (Sprint 11)

## Risk Classification

Risk flags:

- New public API contract (new `/invoice/*` endpoints and response schemas)
- Sensitive business data (invoices contain financial and tax information)
- No existing invoice fixtures or golden parser tests
- Must not break existing `/ocr/*` or `/ocr/structured*` endpoints

Hard gates:

- Existing `/ocr` and `/ocr/structured` behavior must remain unchanged
- Parser tests must run from OCR JSON fixtures without GPU
- Invoice schemas must be separate from `StructuredOCRData`

## Work Phases

### Sprint 0: Harness Setup (this sprint)

Story folder, test matrix rows, decision record. No code.

### Sprint 1: Invoice Schema and Router

`app/schemas/invoice.py`, `app/routers/invoice.py`, router registration in `app/main.py`, API tests.

**Depends on:** PR 0 (this sprint)

### Sprint 2: Layout Normalization

`app/services/layout_analyzer.py`, `app/utils/japanese_text.py`, OCR output fixtures, layout tests.

**Depends on:** PR 1

### Sprint 3: Money, Date, Text, Tax Utilities

`app/utils/money.py`, `app/utils/dates.py`, `app/utils/tax.py`, unit tests.

**Depends on:** PR 1

### Sprint 4: Rule-Based Core Extractor

`app/services/invoice_rules.py`, `app/services/invoice_extractor.py`, extractor tests.

**Depends on:** PR 2, PR 3

### Sprint 5: Validation and Confidence

`app/services/invoice_validator.py`, `app/services/invoice_confidence.py`, validator/confidence tests.

**Depends on:** PR 4

### Sprint 6A: Table Detection and Column Inference

`app/services/table_reconstructor.py`, `app/services/column_inference.py`, table tests.

**Depends on:** PR 2

### Sprint 6B: Row and Cell Reconstruction

Extend `app/services/table_reconstructor.py`, row/cell tests.

**Depends on:** PR 6, PR 3

### Sprint 6C: Line Item Parsing and Validation

Extend `table_reconstructor.py`, `invoice_validator.py`, `invoice_confidence.py`, line-item tests.

**Depends on:** PR 6B

### Sprint 7: Batch and API Hardening

Batch endpoints, config, metrics, README updates.

**Depends on:** PR 5, PR 6C

### Sprint 8: Vendor Matching and Duplicate Detection (future)

### Sprint 9: Storage, Audit, and Review (future)

### Sprint 10: Optional LLM/VLM Fallback (future)

### Sprint 11: Evaluation Dataset (future)

## PR Dependencies

| PR | Content | Depends on |
| --- | --- | --- |
| PR 0 | Story folder, validation plan, test matrix rows | none |
| PR 1 | Invoice schemas, router stubs, main router registration, API tests | PR 0 |
| PR 2 | Layout analyzer and Japanese text normalization | PR 1 |
| PR 3 | Money/date/tax utilities | PR 1 |
| PR 4 | Rule extractor and evidence mapping | PR 2, PR 3 |
| PR 5 | Validation and confidence engines | PR 4 |
| PR 6 | Table detection and column inference | PR 2 |
| PR 7 | Row/cell reconstruction and line-item parser | PR 6, PR 3 |
| PR 8 | Batch, config, metrics, README | PR 5, PR 7 |
| PR 9 | Vendor matching and duplicate detection | PR 5 |
| PR 10 | Storage, audit, review endpoints | PR 8 |
| PR 11 | Optional LLM/VLM fallback | PR 5 |
| PR 12 | Evaluation dataset and reporting | PR 5, PR 7 |

## Stop Conditions

Pause for human confirmation if:

- Product behavior is ambiguous
- Data migration or deletion risk appears
- Validation requirements need to be weakened
- Architecture direction changes
- Storage/audit direction for production persistence needs a decision
