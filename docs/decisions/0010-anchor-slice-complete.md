# 0010 — JP Receipt Anchor Slice Proof Status

**Date**: 2026-07-07
**Status**: Accepted — completion claim withdrawn
**Branch**: `feature/document-ai-rebuild`

## Context

The jp-receipt-slice is the first anchor slice for the Document AI platform. It exercises the full pipeline: multi-format ingestion → OCR → schema-driven extraction → visual table detection → search → review console → audit.

## Implemented Surfaces

| Stage | Deliverable | Tests |
|---|---|---|
| 1 Foundation | Schema registry, storage adapter, classifier, audit log, webhooks, idempotency | 83 |
| 2 Pre-processing | PDF renderer, preprocessing chain, quality gate, language detector | 33 |
| 3 Schema-driven extractor | ExtractionKernel with SourceRegistry dispatch, legacy adapter, receipt-jp schema | 86 |
| 4 Visual table detection | OpenCV rule-line detector, borderless fallback, rowspan/colspan | 42 |
| 5 Search & review API | Chunking, embeddings, hybrid search, review service, document store | 50 |
| 6 Review console UI | Vanilla JS SPA, keyboard shortcuts, confidence heatmap | 10 |

The prior completion record reported aggregate file and test counts without a
reproducible command, environment, or result artifact. Those counts are not
current proof.

## Key Decisions

1. **Schema-driven extraction over hardcoded processors** — Kernel dispatches via SourceRegistry, validators via handler registry. New processors require YAML schema + source function registration only.

2. **In-memory stores for Stage 1-6** — DocumentStore, AuditLog, SearchRepository, WebhookDispatcher are all in-memory singletons. PostgreSQL/pgvector integration deferred to production hardening.

3. **Visual table detection with text fallback** — `table_def.source` dispatches between visual (OpenCV) and text-based extraction. Visual detector is optional import with graceful degradation.

4. **Vanilla JS console UI** — No build system, no framework. Single HTML/CSS/JS page served by FastAPI static mount. Keyboard-first design for operator throughput.

5. **Validator handler registry** — Kernel `_VALIDATOR_HANDLERS` dict maps codes to functions. New validators registered by adding handler — no kernel code changes needed. Avoids hardcoded `if code == "reg001"` branches.

6. **X-Actor trust model** — Current slice trusts `X-Actor` header for actor identity. No authentication layer. Acceptable for internal operator deployment; must add auth before multi-tenant use.

## What We Rejected

- **PostgreSQL for anchor slice** — In-memory stores sufficient for proof-of-concept; PostgreSQL adds deployment complexity before the schema is stable.
- **React/Vue for console** — Vanilla JS keeps the UI deployable with zero build tooling.
- **pgvector for embeddings** — In-memory cosine similarity works for <10k documents; pgvector deferred.

## Lessons

1. **Stub tests create false confidence** — Tests asserting on `stub-001` literals pass trivially. Real wiring (kernel + OCR) must happen before claiming a gate is green.
2. **Validator triplication is a smell** — Regex in invoice_validator.py, kernel.py, and YAML schema created maintenance risk. The handler registry pattern eliminates this.
3. **Audit total must be pre-paginate** — A bug where `total = len(paginated_entries)` broke pagination contracts. Fixed to return total before slicing.
4. **PATCH audit needs reason** — Approve/reject captured X-Reason, but PATCH omitted it. Fixed by threading `reason` parameter through review_service.patch_fields.

## Risks Going Forward

- In-memory stores don't survive process restart — PostgreSQL migration needed before production.
- Async job cancellation uses guarded `running -> committing -> completed`
  transitions. Filesystem jobs use an inter-process lock and atomic replace;
  Redis idempotency uses atomic operation leases. A durable transactional job
  repository is still required before distributed workers or production-scale
  recovery.
- In-memory stores lack interface boundaries — DocumentStore, AuditLog, SearchRepository, WebhookDispatcher are concrete classes, not abstract interfaces. PostgreSQL migration will require defining repository interfaces first. Tag: TECH-DEBT.
- Visual table detector has no real-fixture validation — accuracy claims unverified on actual JP invoices.
- Search relevance has no labeled query set — MRR claims unverified.
- Webhook retry is now implemented but has no integration test against a real HTTP endpoint.

## Proof Status

The anchor slice is not complete under its own validation definition.

- Route-level coverage exists for upload, asynchronous extraction, polling,
  review, keyword search, and audit with deterministic OCR output.
- This is not browser E2E proof and does not establish behavior with a real
  PaddleOCR runtime, multi-page PDFs, durable document/audit/search state,
  webhook delivery, labeled-query relevance, latency budgets, or console
  keyboard workflow.
- `docs/TEST_MATRIX.md` records the remaining gate-level proof gaps. Do not
  mark the slice complete until those gates have observed evidence.
