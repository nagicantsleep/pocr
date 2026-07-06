# Test Matrix

This file maps product behavior to proof.

Product behavior is defined by the implemented stories below.

## Status Values

| Status | Meaning |
| --- | --- |
| planned | Accepted as intended behavior, not implemented |
| in_progress | Actively being built |
| implemented | Implemented and proof exists |
| changed | Contract changed after earlier implementation |
| retired | No longer part of the product contract |

## Matrix

| Story | Contract | Unit | Integration | E2E | Platform | Status | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `docs/stories/US-001-cpu-ocr-fixtures-return-text.md` | CPU OCR fixture images return non-empty text results | yes | yes | no | yes | implemented | `compileall app tests`; focused `normalize_ocr_results` check; CPU container `/ocr` smoke for `tests/fixtures/img*.png` returned 24-47 lines per image |
| `docs/stories/US-002-structured-standardizer/overview.md` | Structured OCR output follows `sample.json` with `inputCostItems` and validates before response | yes | yes | no | yes | implemented | `compileall app tests`; direct standardizer check; CPU container `/ocr` and `/ocr/structured` fixture smoke wrote `out/img*.json` and `out/img*.structured.json` |
| `docs/stories/US-003-durable-structured-jobs/overview.md` | `/ocr/structured` queues durable PostgreSQL/Kafka standardization jobs and `/ocr/structured/jobs/{job_id}` returns queued, running, success, or failed | yes | yes | no | yes | implemented | `compileall app tests scripts`; focused pytest in rebuilt CPU image: 14 passed; structured compose profile E2E job `structured_82e9708ce3f54c2ca2290558bc366ecf` returned `success`; PostgreSQL row has raw OCR and `structured_json.title=Mock OpenRouter Invoice`; Redis key `standardizer:openrouter:minute=1`; Kafka topics `ocr.standardize`, `ocr.standardize.retry`, `ocr.standardize.dlq` exist |
| `docs/stories/US-004-invoice-extraction/overview.md` | `/invoice/extract`, `/invoice/extract/json`, `/invoice/debug` return `InvoiceExtractResponse` with extracted Japanese invoice fields, validation, confidence, and `needs_review` | yes | yes | no | yes | planned | Schema/router tests (Sprint 1), layout analyzer tests (Sprint 2), invoice rules tests (Sprint 4), validator tests (Sprint 5), confidence tests (Sprint 5), table reconstructor tests (Sprint 6A-6C), line item parser tests (Sprint 6C), API endpoint tests (Sprint 1, 7) |
| `tests/fixtures/invoice_eval/` | Evaluation dataset: 50+ fixtures across 7 categories (simple, multiline, receipt, poor_quality, mixed_tax, non_invoice, edge) with golden expected values extracted by the pipeline | no | no | no | yes | implemented | `python -m compileall app tests scripts`; `python scripts/evaluate_invoice_extraction.py` reports per-field, per-category, and auto-approval accuracy |

## Evidence Rules

- Unit proof covers pure domain and application rules.
- Integration proof covers backend enforcement, data integrity, provider
  behavior, jobs, or service contracts.
- E2E proof covers user-visible browser flows.
- Platform proof covers only shell, deployment, mobile, desktop, or runtime
  behavior that cannot be proven in lower layers.
- A story can be implemented without every proof column if the story packet
  explains why.
