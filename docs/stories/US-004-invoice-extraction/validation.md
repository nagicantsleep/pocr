# Validation

## Proof Strategy

Before each PR:

```
python -m compileall app tests
pytest
```

Before marking the invoice API ready:

```
pytest tests/test_invoice_schema.py
pytest tests/test_invoice_api.py
pytest tests/test_layout_analyzer.py
pytest tests/test_invoice_rules.py
pytest tests/test_invoice_validator.py
pytest tests/test_table_reconstructor.py
python -m compileall app tests
```

Before production/ERP readiness:

```
pytest
docker compose -f docker-compose.cpu.yml build
docker compose -f docker-compose.cpu.yml up
```

## Test Plan

| Layer | Cases |
| --- | --- |
| Unit | Schema serialization, money/date/tax parsers, regex extraction, validator rules, confidence scoring, column inference |
| Integration | Layout analyzer with OCR fixtures, table reconstructor with fixtures, extractor end-to-end with golden fixtures |
| E2E | `/invoice/extract` with image upload, `/invoice/extract/json` with base64, `/invoice/debug` with trace output |
| Platform | CPU Docker image serves invoice endpoints, existing `/ocr/*` endpoints unchanged |
| Performance | N/A for MVP |
| Logs/Audit | Validation trace in debug response, metrics emission (Sprint 7) |

## Fixtures

OCR JSON fixtures in `tests/fixtures/ocr_outputs/`:

- `simple_invoice.json`
- `no_table_invoice.json`
- `multiline_description.json`
- `no_header_table.json`
- `discount_row.json`
- `mixed_tax_8_10.json`
- `tax_included_amount.json`
- `tax_excluded_amount.json`
- `low_confidence_ocr.json`
- `non_invoice.json`

All parser tests run from OCR JSON fixtures without GPU.

## Fixtures Strategy

Golden fixtures cover:

- Simple invoice with clear table
- Invoice with no table (header/footer only)
- Multiline description rows
- No-header table (regex fallback)
- Discount/negative rows
- Mixed 8% and 10% tax
- Tax-included vs tax-excluded amounts
- Low-confidence OCR output
- Non-invoice document (negative test)

## Commands

```text
python -m compileall app tests
pytest
pytest tests/test_invoice_schema.py
pytest tests/test_invoice_api.py
pytest tests/test_layout_analyzer.py
pytest tests/test_invoice_rules.py
pytest tests/test_invoice_validator.py
pytest tests/test_table_reconstructor.py
docker compose -f docker-compose.cpu.yml build
docker compose -f docker-compose.cpu.yml up
```

## Manual/API Smoke

- `/ocr` still returns text for existing fixtures
- `/ocr/structured` still queues durable jobs
- `/invoice/extract` returns `InvoiceExtractResponse`
- `/invoice/extract/json` returns `InvoiceExtractResponse`
- `/invoice/debug` returns OCR, layout, regex candidates, table candidates, validation trace

## Quality Gates

- Existing `/ocr` and `/ocr/structured` behavior unchanged
- Parser tests run from OCR JSON fixtures without GPU
- Golden fixtures cover required invoice and line-item cases
- Coverage target: 80% unless repo adopts stricter threshold
- CPU Docker image starts and serves invoice endpoints before production-ready claim

## Definition of Done — MVP

- `POST /invoice/extract` accepts image, returns `InvoiceExtractResponse`
- `POST /invoice/extract/json` accepts base64, returns `InvoiceExtractResponse`
- `POST /invoice/debug` exposes OCR, layout, candidates, table debug, validation trace
- Core Japanese invoice fields extracted from fixtures: registration number, transaction date, invoice number, total amount, 8%/10% tax breakdown, issuer name, recipient name
- Validation returns errors/warnings with stable codes
- Field-level confidence exists
- `needs_review` computed from validation and confidence
- Line items extracted for clear tables
- `line_items_status` distinguishes `extracted`, `partial`, `not_extracted`
- Unclear line items not guessed
- OCR JSON fixtures and golden parser tests exist
- README documents invoice API usage
- Existing `/ocr/*` and `/ocr/structured*` endpoints remain unchanged
- `docs/TEST_MATRIX.md` records proof

## Acceptance Evidence

Add results after verification.
