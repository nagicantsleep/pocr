# Exec Plan — Anchor Slice (Japanese Receipt / Qualified Invoice)

This slice ships in **6 stages** over ~10-12 weeks. Each stage ends with a demoable artifact. Stages 2-6 can overlap where dependencies allow.

```
Stage 1  ████░░░░░░░░░░░░░░░░  Foundation substrate
Stage 2       ████░░░░░░░░░░░░░░  Pre-processing & multi-format
Stage 3            ████░░░░░░░░░░░  Schema-driven extractor
Stage 4                 ████░░░░░░░  Visual table
Stage 5                      ████░░  Search & review API
Stage 6                          ██  Review console UI
```

## Stage 1 — Foundation substrate (1.5 weeks)

Goal: substrate that all later stages build on without rework.

| Task | Owner role | Output |
|---|---|---|
| Schema registry skeleton | executor | `app/schemas/registry/`; loads YAML → JSON schema → Pydantic |
| Storage adapter | executor | `app/storage/`; Local impl, S3 stub |
| Document type classifier (keyword heuristic) | executor | First-pass classification, hooks into existing flow |
| Audit log listing API | executor | `GET /v1/invoices?review_status=needs_review` |
| Webhook on job completion | executor | Kafka → webhook dispatch table |
| Idempotency key for jobs | executor | Redis-backed dedupe |
| Decision record | writer | `0009-schema-versioning.md` |

**Demo**: invoke `/v1/invoice-jp/extract` (skeleton, returning empty extracted JSON) twice with the same idempotency key, get the same `job_id`. Document stored in storage adapter. Audit listing returns the job.

**Gate**: All unit + integration tests green; existing tests untouched.

## Stage 2 — Pre-processing & multi-format (2 weeks)

| Task | Owner role | Output |
|---|---|---|
| PDF ingestion + per-page render | executor | Accepts `application/pdf`; yields one Document per page |
| Image pre-processing chain | executor | deskew / denoise / binarize / dewarp |
| Quality gate | executor | `quality_score` in response; rejects below threshold |
| Language auto-detect | executor | Script + dictionary; X-Lang override honored |

**Demo**: upload a 5-page PDF with mixed orientation and a deliberately skewed single-page PNG; both come back with the same field accuracy as a clean fixture.

**Gate**: Same field accuracy on skewed/noisy fixtures as on clean ones; p95 latency budget met.

## Stage 3 — Schema-driven extractor (2.5 weeks)

| Task | Owner role | Output |
|---|---|---|
| Migration of `invoice_rules.py` → schema field sources | executor | Rules become per-field source declarations |
| Migration of `invoice_validator.py` → schema validators | executor | Validation expressed in YAML, not Python |
| Migration of `invoice_confidence.py` → schema formulas | executor | Confidence per field configurable |
| Extraction kernel driver | executor | Generic loop, processor-agnostic |
| Adapter for `/invoice/*` legacy endpoints | executor | One-version deprecation bridge |
| Receipt-jp processor (second schema) | executor | Same engine, different schema |

**Demo**: add a new processor by writing a YAML schema only, no Python changes.

**Gate**: receipt-jp ≥ 0.80 field F1 on validation set; adding a new processor ≤ 1 day.

## Stage 4 — Visual table detection (1.5 weeks)

| Task | Owner role | Output |
|---|---|---|
| Rule-line detection (OpenCV) | executor | Bounded cell regions |
| Borderless fallback (existing text-row logic) | executor | Reuse `table_reconstructor.py` |
| Composite / multi-line header | executor | Header merge pass |
| Rowspan / colspan detection | executor | Cell merge graph |
| Integration with extraction kernel | executor | Tables flow through schema-driven pipeline |

**Demo**: a JP invoice with borderless line items table, accuracy ≥ +5% over text-only baseline.

**Gate**: ≥ 0.90 region detection; ≥ +5% cell accuracy vs text-only; no regression on invoice-jp.

## Stage 5 — Search & review API (1.5 weeks)

| Task | Owner role | Output |
|---|---|---|
| Layout-aware chunking | executor | Heading → table → paragraph tree preserved |
| Embedding pipeline (pgvector) | executor | `document_chunks` table, embedding column |
| Postgres FTS column | executor | `tsvector` over extracted text |
| `/v1/search` hybrid ranking | executor | α·cosine + β·ts_rank |
| Review API extensions | executor | List / filter / approve / reject / patch |
| Webhook dispatch | executor | Subscribe + retry |

**Demo**: ingest 1,000 receipts; `/v1/search?q=2024 vendor X total > 100000` returns relevant hits in < 500 ms p95.

**Gate**: MRR ≥ 0.7 on labeled query set; p95 ≤ 500 ms on 10k documents.

## Stage 6 — One-page review console UI (1 week)

| Task | Owner role | Output |
|---|---|---|
| Single-page HTML/JS app | designer + executor | No build system |
| Image preview + extracted JSON diff | designer | Side-by-side view |
| Confidence heatmap | designer | Per-cell color |
| Approve / reject / patch buttons with audit reason | executor | Wired to review API |
| Keyboard shortcuts (A/R/J/K) | designer | Power-user flow |

**Demo**: operator reviews 50 needs_review invoices in < 30 minutes.

**Gate**: All review actions persist to DB with audit; no API regression.

## Parallel Execution Map

| Worker | Stages (parallel where possible) |
|---|---|
| Executor A | Stage 1 (skeleton), Stage 3 (kernel) |
| Executor B | Stage 2 (pre-processing) |
| Executor C | Stage 4 (visual table) |
| Executor D | Stage 5 (search) |
| Designer + Executor E | Stage 6 (UI) |

Stage 3 depends on Stage 1. Stages 4 and 5 depend on Stage 3 schema kernel. Stage 6 depends on Stage 5 review API.

## Reference Test Set

Curated from public JP invoice samples + synthetic generation:

- `tests/fixtures/invoice-jp/clean/` — 50 clean fixtures.
- `tests/fixtures/invoice-jp/skewed/` — 20 skewed.
- `tests/fixtures/invoice-jp/noisy/` — 20 noisy.
- `tests/fixtures/invoice-jp/multi-page/` — 10 multi-page PDFs.
- `tests/fixtures/invoice-jp/edge/` — boundary cases (zero tax, refund, multiple tax rates).

Each fixture has:

- `image.pdf` or `image.png`
- `expected.json` — ground truth
- `meta.json` — quality, expected latency bucket

## Hand-off Protocol

At the end of each stage:

1. Decision record `docs/decisions/00NN-<stage>.md` capturing what we built, rejected, and learned.
2. `docs/TEST_MATRIX.md` rows updated with proof.
3. Demo artifact committed to `docs/stories/jp-receipt-slice/demos/<stage>.md`.
4. Backlog updated: any newly discovered work.

## Risk Register

| Risk | Mitigation |
|---|---|
| Schema abstraction over-engineered | After Stage 3 spike, compare line counts; abort if > 2x |
| PDF render slows multi-page | Async batch; pre-render to storage |
| Visual table slow on borderline cases | Always-on text fallback; ML detection only when rule lines absent |
| Embedding cost | Cache embeddings; configurable model; rate limit |
| UI scope creep | Lock to one page, 4 buttons, no per-page filters |

## Done Definition (slice)

The anchor slice is done when:

1. All six stage gates pass.
2. `tests/e2e/test_invoice_jp_e2e.py` exercises: upload PDF → poll job → review console approve → semantic search returns the same invoice.
3. `docs/stories/jp-receipt-slice/demos/final.md` records the e2e walkthrough.
4. `docs/decisions/0010-anchor-slice-complete.md` records the outcome.