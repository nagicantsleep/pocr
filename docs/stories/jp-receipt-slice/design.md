# Design — Anchor Slice (Japanese Receipt / Qualified Invoice)

## Layer Boundaries

This slice respects the master-roadmap layering:

```
┌──────────────────────────────────────────────────────────────────┐
│  Router Layer (app/routers/v1/)                                  │
│  ───────────────────────────                                     │
│  /v1/invoice-jp/extract      sync                                │
│  /v1/invoice-jp/extract:async durable                            │
│  /v1/jobs/{job_id}           poll + webhook                      │
│  /v1/invoice-jp/{id}         fetch + approve/reject              │
│  /v1/invoice-jp/{id}/fields  patch fields (with audit)           │
│  /v1/search                  semantic + FTS                      │
└────────────┬─────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Application Layer (app/services/extraction_kernel/)             │
│  ─────────────────────────────────────────────                   │
│  Pipeline: load schema → preprocess → OCR → layout → extract    │
│            → validate → confidence → emit Document               │
│  Reuses:    invoice_rules, invoice_validator, invoice_confidence │
└────────────┬─────────────────────────────────────────────────────┘
             │
             ▼
┌──────────────────────────────────────────────────────────────────┐
│  Infrastructure Layer                                            │
│  ─────────────────────                                            │
│  schema registry → pdf render → pre-processing → PaddleOCR →    │
│  layout analyzer → table visual → storage adapter → repo        │
└──────────────────────────────────────────────────────────────────┘
```

## Schema Registry Contract

The anchor slice ships **one registered schema**: `invoice-jp` v1.0.0.

`app/schemas/registry/invoice-jp/v1.0.0.yaml`:

```yaml
id: invoice-jp
version: 1.0.0
document_type: qualified_invoice
locale: ja-JP
currency: JPY
fields:
  - name: issuer_name
    type: string
    sources: [regex_vendor, layout_header, llm_fallback]
    required: true
  - name: issuer_registration_number
    type: string
    pattern: "^T\\d{13}$"
    sources: [regex_reg_no]
    required: true
    validators:
      - code: reg001
        severity: error
  - name: transaction_date
    type: date
    pattern: "YYYY-MM-DD"
    sources: [regex_wareki, regex_western]
    required: true
  - name: invoice_number
    type: string
    sources: [layout_label_no, regex_invoice_no]
    required: false
  - name: total_amount
    type: money
    sources: [layout_label_total, regex_amount_max]
    required: true
    cross_field:
      - eq: subtotal_8pct + subtotal_10pct + tax_8pct + tax_10pct
  - name: tax_breakdown
    type: object
    properties:
      rate_8pct:  { subtotal: money, tax: money }
      rate_10pct: { subtotal: money, tax: money }
  - name: line_items
    type: array
    item:
      description: string
      quantity: number
      unit: string
      unit_price: money
      tax_rate: enum[8pct, 10pct, non_taxable, exempt]
      amount_excluding_tax: money
tables:
  - id: line_items
    source: table_visual
    confidence: avg_cell
review_threshold: 0.85
prompt_template: |
  Extract Japanese invoice fields from the OCR text below.
  Return JSON only matching the schema. ...
```

The YAML is loaded by `SchemaRegistry`, validated, exported as JSON schema and as Pydantic model at runtime. The hardcoded `InvoiceData` Pydantic class is replaced by the schema-driven equivalent.

## Pipeline Flow (end-to-end)

```
multipart/form-data: file (image | pdf)
  -> router validates size, content-type
  -> storage.put(key=raw/{request_id}, data, content_type)
  -> job_repository.create(raw_ocr_json=null, status=received)
  -> if PDF: pdf_render.to_images() → page images
  -> preprocessing chain per page (deskew/denoise/binarize/quality)
  -> if quality < threshold: mark document.quality_score low, optionally reject
  -> language auto-detect (override per X-Lang header)
  -> PaddleOCR per page → raw OCR results
  -> layout_analyzer: sort, merge, classify blocks, detect table candidates
  -> extraction_kernel: schema-driven loop
       for each field in schema:
         for each source in field.sources:
           try extract → score → pick best
         apply field.validators
       for each table in schema:
         table_visual.detect → assign_cells → parse_line_items
       apply cross_field validators
       apply confidence formulas
  -> invoice_validator → tax math, format checks
  -> job_repository.mark_success(structured_json)
  -> storage.put(key=extracted/{job_id}, structured_json)
  -> embed each chunk → pgvector
  -> publish document.extraction_completed event → webhook
  -> return Document to caller
```

`document.review_completed` is reserved for approve and reject actions. A
storage failure aborts and cleans up extraction before audit, search, or
webhook publication.

## Pre-processing Chain

```
raw image (BGR)
  -> deskew angle detection (Hough lines)
  -> rotate
  -> grayscale
  -> bilateral filter (denoise, edge-preserving)
  -> adaptive threshold (binarize when needed)
  -> dewarping (if aspect ratio suggests curvature)
  -> quality score:
       - Laplacian variance (blur)
       - contrast histogram
       - edge density
  -> if quality < 0.40: flag in response, optionally fallback to grayscale
```

Quality threshold is configurable per processor.

## Visual Table Detection

Layered:

1. **Rule-line detection** (preferred): OpenCV `HoughLines` or morphological operations to detect horizontal/vertical lines; build a line-intersection grid; cells = bounded regions.
2. **Borderless fallback** (when rule lines absent): text-row proximity (existing `table_reconstructor.py`) + column inference (`column_inference.py`).
3. **Composite header** (multi-line): merge headers vertically.
4. **Cell merging**: detect rowspan/colspan by adjacent cells with same content class and aligned borders.

Output:

```json
{
  "table_id": "line_items",
  "page_no": 1,
  "bbox": {...},
  "rows": [
    {
      "cells": [
        {"col": "description", "text": "...", "bbox": {...}, "confidence": 0.92},
        {"col": "quantity",   "text": "2",  "bbox": {...}, "confidence": 0.88}
      ],
      "is_header": false,
      "is_discount": false
    }
  ],
  "confidence": 0.90
}
```

## Search Layer

Two indexes in Postgres:

- `documents_fts` — `tsvector` over extracted text (issuer, line items, description). Used by `/v1/search?mode=keyword`.
- `documents_vec` — pgvector column. Embedding model configurable (default `text-embedding-3-small` via OpenAI; can fall back to local sentence-transformers).

Hybrid ranking:

```
score = α * cosine(vec_query, vec_doc) + β * ts_rank_cd(fts_query, fts_doc)
```

α, β default to 0.7, 0.3, configurable.

`/v1/qa` is **not** in scope for this slice; only `/v1/search`.

## Review Console (one-page UI)

A single HTML page served by FastAPI at `/console/review`:

- Lists `needs_review` invoices.
- Side-by-side: original image preview + extracted JSON with confidence heatmap (cell-level confidence colored).
- Buttons: approve / reject / patch fields (with audit reason).
- Keyboard shortcuts: `A` approve, `R` reject, `J/K` navigate.

No build system. Plain HTML + small JS bundle. No SPA framework.

## Compatibility with Existing Endpoints

- `/ocr`, `/ocr/json`, `/ocr/batch`, `/ocr/jobs` — unchanged.
- `/ocr/structured`, `/ocr/structured/jobs/{job_id}` — unchanged; still backed by `StructuredOCRData`.
- `/invoice/extract`, `/invoice/extract/json`, `/invoice/debug`, `/invoice/batch`, `/invoice/{id}`, `/invoice/{id}/fields`, `/invoice/{id}/approve`, `/invoice/{id}/reject` — **deprecated** but still functional, mapping to the schema-driven kernel via an adapter.

Deprecation period: one minor version. After that, hardcoded `invoice_extractor.py` is removed.

## Performance Budget

| Stage | Target p95 (single A4 page, CPU) |
|---|---|
| PDF render (per page) | 200 ms |
| Pre-processing | 150 ms |
| PaddleOCR | 1.5 s |
| Layout + extraction | 200 ms |
| Validation + confidence | 50 ms |
| Embedding + index | 200 ms |
| **End-to-end** | **≤ 2.5 s** |

GPU drops OCR to ~250 ms; budget becomes ~1 s end-to-end.

## Risks

| Risk | Mitigation |
|---|---|
| Schema-driven abstraction over-engineered | Compare line count vs hardcoded in spike; abort if > 2x |
| Visual table detection slow | Offload to async job for batches > 5 pages |
| pgvector at 10k docs slow | Add `ivfflat` index; benchmark at 1k, 10k, 100k |
| One-page UI scope creep | Lock to 4 buttons; no per-page filters beyond review status |
| Old `/invoice/*` endpoint users break | Adapter layer + deprecation banner in response |
