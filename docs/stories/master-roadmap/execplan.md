# Exec Plan — Master Roadmap

This is the **delivery plan**, ordered by tier. Each tier has a one-line proof artifact and a one-line stop condition. Detail belongs to anchor-anchored stories.

## Tier 0 — Foundation (1 sprint)

Goal: clean substrate that all later tiers can build on without rework.

| Task | Owner | Output |
|---|---|---|
| Schema registry skeleton (`app/schemas/registry/`) | executor | `SchemaRegistry`, YAML loader, JSON schema export |
| Storage adapter skeleton (`app/storage/`) | executor | `StorageAdapter` Protocol + Local impl |
| Document type field added to `StructuredOCRData` | executor | Schema migration, backward compatible |
| Audit log listing endpoint | executor | `GET /v1/invoices?review_status=needs_review` |
| Webhook event publish on job completion | executor | Kafka topic `document.review_completed` |
| Idempotency key for `/v1/jobs` | executor | Redis-backed dedupe |
| Decision record: schema versioning policy | writer | `docs/decisions/0009-schema-versioning.md` |

**Proof**: All four foundation pieces ship behind a feature flag. Existing tests still pass.

**Stop condition**: No feature flag remains on by default without a test.

## Tier 1 — Pre-processing & multi-format (2 sprints)

| Sprint | Task | Output |
|---|---|---|
| 1.1 | PDF / TIFF ingestion | `/v1/{processor}/extract` accepts `application/pdf`, multi-page returned as `Document` with `pages[]` |
| 1.1 | Page rendering | `pdf2image` adapter, configurable DPI |
| 1.2 | OpenCV pre-processing pipeline | `deskew`, `denoise`, `binarize`, `dewarp` chain, metrics logged per step |
| 1.2 | Quality gate | Reject images scoring below threshold; surface `quality_score` in response |
| 1.2 | Language auto-detect | Script + dictionary; user override via `X-Lang` header |

**Proof**: Same accuracy target reached on intentionally skewed/noisy PDFs that previously failed.

**Stop condition**: Quality gate rejects ≤ 5% of golden set. Anything more → threshold tuning.

## Tier 2 — Schema-driven form parser (3 sprints)

| Sprint | Task | Output |
|---|---|---|
| 2.1 | Schema-driven extractor kernel | Replaces hardcoded `invoice_extractor.py` with config-driven loop |
| 2.1 | Field source declarations in YAML | regex / spatial / LLM / table per field |
| 2.2 | Validation rules expressed in schema | `min`, `max`, `regex`, `enum`, `cross_field` |
| 2.2 | Confidence formulas in schema | per-field formulas, calibrated against labeled set |
| 2.3 | Prebuilt: receipt-jp | Second processor on same engine |
| 2.3 | Multi-language entity recognition | PERSON / ORG / ADDRESS / MONEY / DATE / PHONE / EMAIL |

**Proof**: Same engine extracts receipt-jp ≥ 80% field accuracy on validation set.

**Stop condition**: Adding a new processor takes ≤ 1 day, no code changes outside the schema directory.

## Tier 3 — Visual structure & special tokens (2 sprints)

| Sprint | Task | Output |
|---|---|---|
| 3.1 | Visual table detection | Detect tables by horizontal/vertical rule lines (OpenCV) + ML fallback |
| 3.1 | Composite header / multi-line cell | Multi-pass merge |
| 3.2 | Rowspan / colspan detection | Cell merge graph |
| 3.2 | Checkbox / radio / signature / stamp | Per-region special tokens, JP 印鑑 included |

**Proof**: Receipt-jp accuracy improves ≥ 5% after visual table detection vs text-only.

**Stop condition**: No regression on invoice-jp accuracy.

## Tier 4 — Knowledge layer (2 sprints)

| Sprint | Task | Output |
|---|---|---|
| 4.1 | Layout-aware chunking | Heading → table → paragraph hierarchy preserved |
| 4.1 | Embedding pipeline | pgvector; configurable model |
| 4.2 | Full-text search | Postgres FTS; `tsvector` on extracted text |
| 4.2 | `/v1/search` semantic + FTS | Hybrid ranking |
| 4.2 | `/v1/qa` grounded answer | Returns answer + `source_cells[]` with bbox |

**Proof**: 1,000 receipts ingested; `/v1/search` returns relevant hits in < 500 ms p95.

**Stop condition**: Citation accuracy ≥ 90% on QA golden set.

## Tier 5 — Workbench (3 sprints)

| Sprint | Task | Output |
|---|---|---|
| 5.1 | Review console UI | Review queue, diff, approve/reject, label diff |
| 5.1 | Ground-truth dataset manager | Upload labeled set, version, split |
| 5.2 | Confidence calibration dashboard | Per-field reliability, threshold tuning |
| 5.2 | Drift detection | Alert when field confidence distribution shifts |
| 5.3 | LLM provider A/B harness | Shadow-mode compare outputs |

**Proof**: Operators review 50 needs_review invoices in < 30 minutes via UI.

**Stop condition**: UI ships behind feature flag; no regression in API throughput.

## Tier 6 — Enterprise scale (open-ended)

| Task | Output |
|---|---|
| Multi-tenancy + RBAC | Tenant-scoped resources, role-based access |
| Quota / billing | Per-tenant rate, cost tracking |
| Multi-region + DR | Active/passive, RPO 5 min |
| SDKs (JS, Go, Java, .NET) | Stable clients, versioned with API |
| Compliance (GDPR, audit retention) | Right-to-erasure, audit log queryable |

**Proof**: Two tenants isolated, no cross-tenant leak in any test.

## Parallelism Map

Tiers can overlap where dependencies allow:

```
Tier 0  ████████████░░░░░░░░░░
Tier 1       ████████████░░░░░░
Tier 2            ████████████░░
Tier 3                ██████████
Tier 4                    ██████
Tier 5                        ██
```

Pre-processing (tier 1) can start as soon as the storage adapter (tier 0) lands. Schema registry (tier 0) is a hard prerequisite for tier 2. UI (tier 5) can start once tier 2 API is locked.

## Risk Register

| Risk | Mitigation |
|---|---|
| Schema abstraction costs more than it saves | Compare lines saved vs added in tier 2.1 before 2.2 |
| PDF rendering performance | Benchmark; consider asynchronous batch rendering |
| pgvector scaling | OpenSearch / Qdrant swap path proven by abstracting vector store |
| LLM cost overrun | Per-tenant budget, rate limiter, prompt caching |
| UI scope creep | One-page MVP first; iterate on real usage data |

## Hand-off Rule

Every tier completion writes a `docs/decisions/00NN-*.md` capturing:

- What we built.
- What we rejected and why.
- What we now know that we did not know before.
- Any newly discovered work added to backlog.