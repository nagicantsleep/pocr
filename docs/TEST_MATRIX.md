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
| **jp-receipt-slice S1** | Schema registry loads `invoice-jp/v1.0.0.yaml`; YAML → JSON Schema → Pydantic round-trip | yes | no | no | no | implemented | `tests/test_invoice_schema.py` covers Pydantic model creation |
| **jp-receipt-slice S1** | Storage adapter put/get/delete/presigned with Local + S3-compatible storage | yes | yes | no | yes | implemented | Adapters are covered by `tests/test_storage_adapter.py` and `tests/test_s3_storage_adapter.py`. Live async JP extraction stored `raw` and `extracted.json`; cancellation/restart removed journaled artifacts. `scripts/validate-jp-failure-recovery-live.ps1` proves a stopped MinIO returns `503` without a durable job/idempotency record, then records actual MinIO source `PUT` and `DELETE` after forced queue rollback. |
| **jp-receipt-slice S1** | Classifier picks `qualified_invoice` on JP keyword fixture | yes | no | no | no | implemented | `tests/test_classifier.py` with `T1234567890123` + `適格請求書` |
| **jp-receipt-slice S1** | Audit log listing with pagination + filtering | yes | no | no | no | implemented | `tests/test_audit_log.py`; `total` returns pre-paginate count (fixed) |
| **jp-receipt-slice S1** | Webhook dispatch with exponential backoff retry (≤ 5 attempts) | yes | yes | yes | yes | implemented | A tenant-scoped durable subscription delivered to real HTTPS `httpbin.org`; `scripts/validate-jp-webhook-recovery-live.ps1` observed external HTTP `500`, a durable pending delivery, then HTTP `200` recovery under a new lease (`claims=2->3`). Unit coverage retains the ≤5-attempt bound and fencing proof rejects stale owners. |
| **jp-receipt-slice S1** | Idempotency lease binds bytes, content type, language, and schema version | yes | yes | no | yes | implemented | PostgreSQL-backed sync and async canonical replay commit atomically. `scripts/validate-jp-failure-recovery-live.ps1` proves same-key concurrency converges on one document, expiry is reclaimed, and durable replay works while Redis is stopped and after it restarts. |
| **jp-receipt-slice S2** | PDF multi-page ingestion (5-page PDF → 5 pages) | yes | yes | no | no | implemented | On 2026-07-17 the public `/v1/invoice-jp/extract` accepted a generated five-page PDF and returned `page_count=5`; PostgreSQL contained five documents and five committed extraction events. |
| **jp-receipt-slice S2** | Clean invoice field F1 | no | no | no | no | in_progress | Run `scripts/evaluate_invoice_extraction.py` on `tests/fixtures/invoice-jp/clean/`; threshold is ≥0.90 registration/total/date and ≥0.85 issuer/line items; result artifact missing |
| **jp-receipt-slice S2** | Skewed/noisy invoice F1 regression | no | no | no | no | in_progress | Run the evaluator on `tests/fixtures/invoice-jp/skewed/` and `noisy/`; no drop >0.05 from clean; result artifact missing |
| **jp-receipt-slice S2** | Quality-gate false reject rate | no | no | no | no | in_progress | Run clean-fixture route evaluation; threshold is ≤5%; result artifact missing |
| **jp-receipt-slice S2** | Five-page PDF route ingestion | yes | yes | no | no | implemented | The local live route proof returned five pages, persisted five documents/outbox rows, and stored the source PDF in MinIO. |
| **jp-receipt-slice S2** | Artifact-storage rollback and first-page latency | yes | partial | no | partial | in_progress | Router test covers single-page storage failure. On 2026-07-17, a running 20-page PDF job was cancelled, its worker was killed, and restart cleanup removed the MinIO source and all journaled derived artifacts; storage timeout and p95 first-page latency ≤2s remain unproven. |
| **jp-receipt-slice S2** | Preprocessing chain (deskew + denoise + binarize) | yes | no | no | no | implemented | `tests/test_preprocessing.py` synthetic images |
| **jp-receipt-slice S2** | Quality gate (sharpness/contrast/brightness/noise scoring) | yes | no | no | no | implemented | `tests/test_quality_gate.py` |
| **jp-receipt-slice S2** | Language auto-detect (Hiragana/Katakana/CJK/Latin script) | yes | no | no | no | implemented | `tests/test_lang_detect.py` |
| **jp-receipt-slice S3** | Schema-driven extraction kernel field dispatch via SourceRegistry | yes | no | no | no | implemented | `tests/test_extraction_kernel.py` |
| **jp-receipt-slice S3** | Schema-driven validator dispatch (registry-based, extensible) | yes | no | no | no | implemented | `tests/test_extraction_kernel.py` REG001 via `_VALIDATOR_HANDLERS` |
| **jp-receipt-slice S3** | Cross-field validator (subtotal + tax = total, tolerance 5 JPY) | yes | no | no | no | implemented | `tests/test_extraction_kernel.py` cross-field eq |
| **jp-receipt-slice S3** | Schema confidence scorer | yes | no | no | no | implemented | `tests/test_schema_confidence.py` |
| **jp-receipt-slice S3** | Legacy adapter bridges `/invoice/*` to kernel | yes | no | no | no | implemented | `tests/test_legacy_adapter.py` |
| **jp-receipt-slice S3** | Receipt-jp schema v1.0.0 loads and extracts | yes | no | no | no | implemented | Schema at `app/schemas/registry/receipt-jp/v1.0.0.yaml` |
| **jp-receipt-slice S3** | Invoice-jp field F1 | partial | no | no | no | in_progress | Run evaluator on `tests/fixtures/invoice-jp/clean/`; threshold is ≥0.85 registration/total/date and ≥0.80 issuer/line items; result artifact missing |
| **jp-receipt-slice S3** | Receipt-jp field F1 | partial | yes | yes | no | in_progress | `scripts/prepare-jawildtext-receipt-corpus.py` pins public Apache-2.0 `llm-jp/jawildtext` receipt KIE data. The rebuilt local API's real two-receipt smoke run reached total/date F1 `1.0` after matching the OCR-split `合言十` label to its right-aligned currency value; legal issuer F1 remains `0.0` because source `store_name` is not adjudicated as legal issuer. The ≥0.80 receipt-field gate remains open. |
| **jp-receipt-slice S3** | Temporary field-extraction regression corpus selection | yes | no | no | no | implemented | `docs/stories/jp-enterprise-hardening/temporary-benchmark-manifest.json` pins 30 synthetic text records from `Aulvem/japanese-invoice-receipt-extraction-eval` for development-only issuer/registration/date/tax/total/line-item regression. This is not real-image, legal-issuer, commercial, or production evidence. |
| **jp-receipt-slice S3** | Temporary real-image date/total regression corpus selection | partial | yes | yes | no | implemented | The same manifest pins Apache-2.0 `llm-jp/jawildtext` `receipt_kie` (1,151 public real receipt images) for date/total-only development regression. The observed two-image public-route run is scoped to those fields; full receipt F1, issuer, ECE, throughput, and production remain open. |
| **jp-receipt-slice S3** | Legacy-to-kernel structural equality | no | no | no | no | in_progress | Add and run a structural diff over versioned fixtures; exact equality required; artifact missing |
| **jp-receipt-slice S3** | Processor-add exercise | no | no | no | no | in_progress | Record a schema/source addition exercise; threshold is ≤1 day with no code outside allowed extension points; artifact missing |
| **jp-receipt-slice S3** | Confidence calibration | partial | yes | yes | no | in_progress | The rebuilt real two-receipt smoke run measured ECE `0.4309`, above the ≤0.05 threshold. Date and total now compare after lossless presentation normalization, but issuer confidence is still overconfident against the non-equivalent legal-issuer target; this is failure evidence, not acceptance evidence. |
| **jp-receipt-slice S4** | Visual table detector (OpenCV rule-line + borderless fallback) | yes | no | no | no | implemented | `tests/test_table_visual.py` synthetic images |
| **jp-receipt-slice S4** | Rowspan/colspan detection on multi-merge grids | yes | no | no | no | implemented | `tests/test_table_visual.py` colspan/rowspan ≥ 2 |
| **jp-receipt-slice S4** | Table region accuracy | no | no | no | no | in_progress | Evaluate `tests/fixtures/invoice-jp/edge/table-heavy/`; threshold ≥0.90; artifact missing |
| **jp-receipt-slice S4** | Temporary table/layout regression corpus selection | yes | no | no | no | implemented | `docs/stories/jp-enterprise-hardening/temporary-benchmark-manifest.json` pins the 518-page synthetic `stockmark/OmniDocBench-JASyn` annotation for table/layout/reading-order regression only. Region-accuracy and qualified-invoice thresholds remain open until an observed report exists. |
| **jp-receipt-slice S4** | Borderless cell assignment improvement | no | no | no | no | in_progress | Compare visual against text-only fixtures; threshold ≥+5%; artifact missing |
| **jp-receipt-slice S4** | Invoice-jp regression after visual detection | no | no | no | no | in_progress | Re-run clean fixture evaluation; no drop ≥0.02; artifact missing |
| **jp-receipt-slice S4** | Visual detector p95 latency | no | no | no | no | in_progress | Benchmark per page; threshold ≤300ms added; artifact missing |
| **jp-receipt-slice S5** | Search: layout-aware chunking + embedding + keyword/semantic/hybrid | yes | yes | partial | no | in_progress | Search chunks, the consumer receipt, and matching webhook intents are committed atomically under the receipt lease. Durable keyword search now queries tenant chunks directly rather than reconstructing the prior 200-document window; the rebuilt local API returned non-degraded keyword results. Labeled-query MRR, semantic/hybrid 10k behavior, and latency remain unverified. |
| **jp-receipt-slice S5** | Review API: list / approve / reject / patch with audit + webhook | yes | yes | yes | yes | implemented | Durable approve, audit, outbox, webhook delivery, and a concurrent `200`/`409` approve guard were exercised live. `scripts/validate-jp-console-live.ps1` proves browser patch/reject/approve, `R/J/K/P`, and a 50-document approval workflow; `scripts/validate-jp-outbox-retry-dlq-live.ps1` proves three retries then DLQ exhaustion against Kafka. |
| **jp-receipt-slice S5** | Ingest 1,000 receipts end-to-end | partial | yes | no | no | in_progress | The pinned real receipt corpus has 1,151 images and the preparer can create an exact 1,000-document manifest. No 1,000-document download/ingest has run on a selected reference machine; threshold ≤30 min remains unverified. |
| **jp-receipt-slice S5** | Semantic search MRR | no | no | no | no | in_progress | Evaluate a 50-query labeled set; threshold MRR ≥0.7; dataset and artifact missing |
| **jp-receipt-slice S5** | Keyword search MRR | no | no | no | no | in_progress | Evaluate the same labeled set; threshold MRR ≥0.7; dataset and artifact missing |
| **jp-receipt-slice S5** | Hybrid ranking quality | no | no | no | no | in_progress | Compare against semantic and keyword runs; hybrid must be ≥ either mode; artifact missing |
| **jp-receipt-slice S5** | Search p95 latency at 10k documents | partial | yes | no | no | in_progress | The keyword read path no longer has a 200-document reconstruction cap. It still needs a licensed 10k JP corpus, a selected reference machine, and a live ≤500ms p95 artifact. |
| **jp-receipt-slice S6** | Console UI: HTML/JS, confidence heatmap, A/R/J/K shortcuts | yes | yes | yes | yes | implemented | `scripts/validate-jp-console-live.ps1` uses Playwright against the durable stack and proves `R/J/K/P`, patch/reject/approve persistence, and modal reason validation. |
| **jp-receipt-slice S6** | Operator workflow across 50 needs-review invoices | yes | yes | yes | yes | implemented | `scripts/validate-jp-console-live.ps1` approved 50 tenant-scoped documents in `00:00:18.8896547`, below the ≤30-minute threshold, then deleted its scoped proof data. |
| **jp-receipt-slice S6** | Review actions persist to DB | yes | yes | yes | yes | implemented | On 2026-07-17, Playwright `A`/`Ctrl+Enter` approval persisted version `2`, actor, and reason. API/worker restart retained data; two concurrent approves yielded `200` and `409` with one approve audit. |
| **jp-receipt-slice S6** | Keyboard shortcuts | yes | yes | yes | yes | implemented | Playwright observed `R`, `J`, `K`, and `P`; patch/reject/approve actions persisted with their required reasons. |
| **jp-receipt-slice S6** | API p95 latency regression | no | no | no | no | in_progress | Benchmark before/after review-console flow; no regression allowed; artifact missing |
| **jp-receipt-slice** | **Route-level upload → extract → approve → search → audit** | no | **yes** | no | no | **in_progress** | `tests/e2e/test_invoice_jp_e2e.py` uploads through public routes with deterministic OCR; it is not browser E2E, real PaddleOCR, PDF, or persistence proof |
| `docs/stories/jp-enterprise-hardening/overview.md` | Tenant-principal authorization, durable JP document/review/audit/search records, object storage, PostgreSQL outbox, Kafka workers, tenant-bound idempotency, and evidence-aware review | yes | yes | yes | yes | in_progress | Live proof covers async worker/restart recovery, tenant denial, MinIO artifacts, cancellation cleanup, durable search, external webhook `500→200` recovery, Kafka duplicate suppression, retry/DLQ, browser patch/reject/approve with `R/J/K/P`, 50-document workflow, stale fencing, idempotency contention/expiry/Redis outage, PostgreSQL rollback zero-outbox, and MinIO outage/queue-rollback cleanup. The temporary three-source benchmark manifest now closes dataset-selection gates for field, date/total, and table/layout regression only. Legal issuer, ECE, invoice/table thresholds, 1k, 10k, relevance, and reference-machine gates remain open. |

## Evidence Rules

- Unit proof covers pure domain and application rules.
- Integration proof covers backend enforcement, data integrity, provider
  behavior, jobs, or service contracts.
- E2E proof covers user-visible browser flows.
- Platform proof covers only shell, deployment, mobile, desktop, or runtime
  behavior that cannot be proven in lower layers.
- A story can be implemented without every proof column if the story packet
  explains why.
