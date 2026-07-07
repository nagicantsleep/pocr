# Anchor Slice — Japanese Receipt / Qualified Invoice

## Why This Anchor

Japanese qualified invoice (`適格請求書`, JP-specific post-2023 consumption tax reform) is the **highest-value** anchor use case for `pocr` because:

1. It already has the most implemented surface in the repo: `invoice_extractor.py`, `invoice_rules.py`, `invoice_validator.py`, `invoice_confidence.py`, `vendor_matcher.py`, `duplicate_detector.py`, `table_reconstructor.py`, `column_inference.py`, `layout_analyzer.py`, JP regex, era dates.
2. The format is **legally defined** — fields are mandatory (registration number `T` + 13 digits, transaction date, 8%/10% tax breakdown, total) — so we have a stable ground truth.
3. The market segment is real (Japanese SMB + accounting software integrators) and underserved by Western Document AI providers (Google DocAI's invoice processor has weak JP-specific validation).
4. Every capability proven here generalizes: schema registry → other document types, pre-processing → all OCR, RAG → all extracted archives.

The slice proves the **master roadmap** end-to-end on one document type before generalizing.

## Scope

In scope (this slice):

- Multi-format input (image + PDF) for JP receipt / qualified invoice.
- Pre-processing chain (deskew / denoise / binarize / quality gate).
- Schema-driven extractor with `invoice-jp` as the first registered processor.
- Visual table detection for line items.
- Confidence calibration against a labeled JP set.
- Review API extensions: list, filter, approve, reject, label diff.
- Webhook on job completion.
- pgvector-backed semantic search over archived invoices.
- Minimal review console UI (1 page).

Out of scope (deferred to next anchors):

- Receipt variants outside JP.
- Passport, contract, application form processors (deferred until schema registry proven).
- Online training pipeline (offline-only in this slice).
- Multi-region / DR / multi-tenancy.

## Target Users

- **Japanese SMB** uploading qualified invoices for tax filing.
- **Accounting software** integrating via `/v1/invoice-jp/extract` to ingest vendor invoices.
- **Internal operators** reviewing flagged invoices via console.

## Success Criteria (User-visible)

A Japanese SMB user can:

1. Upload a PDF containing 5 qualified invoices (mixed orientation, some skewed).
2. Receive structured JSON per invoice (registration number, date, vendor, total, 8%/10% tax split, line items).
3. Each line item has per-cell confidence; total confidence is calibrated.
4. Items with confidence below threshold are flagged `needs_review` and surfaced in a single-page review queue.
5. Operator reviews, approves, and the result is indexed for later semantic search: "show me all 2024 invoices from vendor X with total > 100,000 JPY".

## Affected Product Docs

- `docs/product/ocr-api.md` — add `/v1/invoice-jp/*` and `/v1/search` endpoints.
- `README.md` — document anchor slice usage.
- `docs/GLOSSARY.md` — add: schema registry, processor, document type, semantic search.

## Architectural Anchors (from master roadmap)

This slice exercises the following master-roadmap capabilities:

- Tier 0: Schema registry, storage adapter, document type field, webhook, audit log API.
- Tier 1: PDF ingestion, pre-processing, quality gate, language auto-detect.
- Tier 2: Schema-driven extractor for `invoice-jp` (replaces current hardcoded `invoice_extractor.py`).
- Tier 3: Visual table detection.
- Tier 4: pgvector semantic search, full-text search.
- Tier 5: One-page review console UI.

Every capability proven in this slice is reusable for the next anchor.

## Non-Goals

- Replace PaddleOCR or weaken existing `/ocr/*` and `/ocr/structured*` endpoints.
- Backward compatibility for the hardcoded `invoice_extractor.py` — it migrates to the schema-driven kernel. Old endpoints stay alive for one minor version.
- Real-time collaborative review.
- LLM training or fine-tuning.

## Affected Code Surfaces (anticipated)

```
app/schemas/registry/                   — new (schema registry)
app/storage/                            — new (storage adapter)
app/services/preprocessing/             — new (deskew, denoise, etc.)
app/services/pdf_render/                — new (pdf2image adapter)
app/services/extraction_kernel/         — new (schema-driven loop)
app/services/table_visual/              — new (visual table detection)
app/services/search/                    — new (semantic + FTS)
app/routers/v1/                         — new (versioned routes)
app/web/                                — new (one-page review console)
```

Files **migrated**, not deleted:

- `app/services/invoice_rules.py`        → schema field source rules
- `app/services/invoice_extractor.py`    → `extraction_kernel` driver for `invoice-jp`
- `app/services/invoice_validator.py`    → schema validation rules
- `app/services/invoice_confidence.py`   → schema confidence formulas
- `app/services/table_reconstructor.py`  → splits into `table_text` + `table_visual`

## Stop Conditions

- Schema abstraction costs > 2x the lines it saves → revert and keep hardcoded.
- Field accuracy on labeled JP set < 70% → stop scaling, fix quality.
- User feedback contradicts anchor selection → switch to next anchor (passport), keep building blocks.

## Related Stories

- `docs/stories/master-roadmap/` — capability matrix this slice proves out.
- `docs/stories/US-004-invoice-extraction/` — predecessor; provides the legacy hardcoded layer that this slice migrates.
- `docs/decisions/0008-invoice-extraction-layer.md` — origin decision.

## Change Log

- 2026-07-07: Anchor slice story created.