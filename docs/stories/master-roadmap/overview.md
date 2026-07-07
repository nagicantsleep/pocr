# Document AI Roadmap — Master Plan

## Purpose

This story is the **single source of truth** for evolving `pocr` from "PaddleOCR REST API" into a **general-purpose Document AI platform** on par with tier-1 providers (Google Document AI, Azure Document Intelligence, AWS Textract + Comprehend + Bedrock).

The roadmap is organized in two layers:

1. **Master roadmap** — the complete capability gap analysis and target architecture, **without** committing to a specific anchor use case (`docs/stories/master-roadmap/`).
2. **Anchor-anchored roadmap** — a vertical-slice execution plan for the **Japanese receipt / qualified-invoice** use case that proves out the master capabilities end-to-end (`docs/stories/jp-receipt-slice/`).

The anchor-driven roadmap is a strict subset of the master roadmap. Each capability proven in the slice is then generalized to all processors in subsequent slices (passport, contract, application, etc.).

## Source of Truth

Read in this order:

1. `README.md` — current product status.
2. `docs/HARNESS.md` — human-agent operating model.
3. `docs/FEATURE_INTAKE.md` — request classification.
4. `docs/stories/master-roadmap/overview.md` — full capability gap matrix.
5. `docs/stories/jp-receipt-slice/overview.md` — current execution slice.
6. `docs/ARCHITECTURE.md` — non-negotiable architectural rules.
7. `docs/decisions/0008-invoice-extraction-layer.md` — anchor use case origin.
8. `docs/TEST_MATRIX.md` — proof ledger.
9. `docs/stories/backlog.md` — pending micro-work.

## Strategic Posture — Vertical Slices, Not Horizontal Fill

We DO NOT chase the full 25-item gap list one by one. Coverage gaps are *symptoms* of missing core capabilities. We close capabilities, and coverage follows.

### Anti-pattern (rejected)

```
gap 1 → fix → gap 2 → fix → gap 3 → fix → ... → ship after 6 months
```

Rejected reasons:

- Each gap fix is local; uncovered gaps appear afterward.
- No user-visible artifact for 6+ months.
- Cash burn with no validation.

### Chosen pattern (vertical slice)

```
anchor use case → end-to-end pipeline → demo → generalize
```

For the Japanese receipt / qualified-invoice anchor:

1. Pick the minimum set of capabilities that lets a single receipt go from upload → validated JSON → human-reviewed → searchable.
2. Build them deeply enough to be reusable (schema registry, not hardcoded; storage adapter, not local FS; etc.).
3. Ship the slice and prove accuracy/throughput.
4. Reuse the same building blocks for the next anchor (passport, contract, application).

This is the only way to reach tier-1 capability within a sane budget.

## Master Capability Matrix

Tier ordering: each tier depends on the tier above being stable.

### Tier 0 — Foundation (mostly done, needs hardening)

| Capability | Current state | Target | Notes |
|---|---|---|---|
| OCR engine wrapper (PaddleOCR 3.5) | ✅ | ✅ | GPU/CPU fallback proven |
| Async job store (filesystem, Redis) | ✅ | ✅ | |
| Durable structured pipeline (Postgres + Kafka + DLQ + retry) | ✅ | ✅ | Already shipped |
| LLM standardization providers (heuristic, OpenRouter, OpenAI) | ✅ | ✅ | JSON-schema enforced |
| API key auth + Prometheus metrics | ✅ | ✅ | |
| Schema registry (YAML → JSON schema) | ❌ | ✅ | **Required** before tier 2 |
| Storage adapter (Local/S3/GCS/Azure Blob) | ⚠️ image_url placeholder only | ✅ | **Required** before tier 3 |
| Document type field + simple classifier | ❌ | ✅ | **Required** before tier 2 |
| Audit log API (list/filter/export) | ⚠️ partial | ✅ | **Required** for tier 4 |
| Webhook for job completion | ❌ | ✅ | Optional but cheap |

### Tier 1 — Pre-processing & multi-format

| Capability | Target |
|---|---|
| PDF / multi-page TIFF ingestion + per-page rendering | `pdf2image` or `pymupdf` |
| Image pre-processing: deskew, denoise, binarize, dewarping | OpenCV pipeline |
| Image quality scoring (Laplacian variance, contrast) | Reject low-quality before OCR |
| Language auto-detection | Script + dictionary detector |
| Vertical text support (JP/CN) | PaddleOCR 3.x supports; pipeline must not flatten |
| Right-to-left handling (AR/HE) | Layout analyzer must respect direction |

### Tier 2 — Schema-driven form parser (generalized)

| Capability | Target |
|---|---|
| Schema registry: YAML → JSON schema → Pydantic | `app/schemas/registry/` |
| Custom extractor pipeline driven by schema, not by hardcoded `InvoiceData` | Replaces current invoice_rules.py |
| Prebuilt processors: invoice (JP), receipt, contract, ID, application form | Same engine, different schema |
| Field-level confidence calibrated across providers | Reuse invoice_confidence.py as service |
| Validation rules expressed in schema | Move hardcoded validators to schema-level |
| Multi-language entity recognition (person, org, address, money, date, phone, email) | Replace JP-only regex |

### Tier 3 — Visual structure & special tokens

| Capability | Target |
|---|---|
| Visual table detection (rule lines, borderless via ML) | Add to `table_reconstructor.py` |
| Composite / multi-line header handling | Already partly there; generalize |
| Rowspan / colspan | Detect merge cells |
| Checkbox / radio / signature / stamp detection | JP 印鑑, US signature, EU checkbox |
| Form-field to value relationship (heuristic + ML) | |
| Multi-page table continuation | Track `page_no` per region |

### Tier 4 — Knowledge layer (RAG + search)

| Capability | Target |
|---|---|
| Chunking strategy: heading → table → paragraph | Layout-aware |
| Vector embeddings per chunk | pgvector / Qdrant / Vertex AI |
| Full-text search | Postgres FTS or OpenSearch |
| Semantic search API + chatbot endpoint | `/search`, `/qa` |
| Citation + source-grounded Q&A | `source_cells`, page, bbox |

### Tier 5 — Workbench (training + UI)

| Capability | Target |
|---|---|
| Review console (Vue/React SPA) for human review | Single-page review queue, diff, approve/reject |
| Label Studio or equivalent for ground-truth labeling | |
| Model registry + A/B testing for LLM providers | |
| Confidence calibration + drift detection | |
| Training pipeline for custom processors | Online + offline paths |

### Tier 6 — Enterprise scale

| Capability | Target |
|---|---|
| Multi-tenancy + RBAC + quota / billing | |
| Multi-region + DR | |
| SLA / SLO + compliance (GDPR right-to-erasure, audit) | |
| SDKs (JS, Go, Java, .NET) | |

## Anti-Goals (never do)

- Replace PaddleOCR with proprietary OCR. PaddleOCR is the engine of choice.
- Couple schema to a single document type. Schemas are data, not code.
- Build UI before API is stable. API contract must be locked before frontend.
- Train custom ML models until the schema + label pipeline is proven.
- Ship a "kitchen sink" endpoint. Every new capability must have its own contract and its own test fixture.

## Stop Conditions

The roadmap is paused/redirected when any of the following holds:

- Anchor slice ships but accuracy < 70% on validation set → fall back, fix quality before scaling.
- Schema registry abstraction costs >2x the lines it saves → revert to hardcoded processors per anchor.
- User feedback contradicts anchor selection → switch anchor (keep building blocks).

## Related Stories

- `docs/stories/jp-receipt-slice/` — execution slice (active)
- `docs/stories/master-roadmap/execplan.md` — tier-by-tier delivery plan
- `docs/stories/master-roadmap/design.md` — target architecture
- `docs/stories/master-roadmap/validation.md` — acceptance criteria per tier

## Change Log

- 2026-07-07: Initial roadmap created alongside anchor slice.
