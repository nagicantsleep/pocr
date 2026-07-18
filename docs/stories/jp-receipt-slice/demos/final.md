# JP Receipt/Invoice Anchor Slice Demo Procedure

**Date**: 2026-07-07
**Branch**: `feature/document-ai-rebuild`

## Evidence Status

This is a runnable procedure, not a recorded final demonstration. It contains
no observed timestamps, command output, screen recording, or transcript, and
must not be used as evidence that the slice is complete.

The documented flow uses in-process stores in the current implementation. It
does not prove persistence across restart, browser behavior, or production OCR
quality.

## Steps

### 1. Upload and Extract (Sync)

```bash
curl -X POST http://localhost:8000/v1/invoice-jp/extract \
  -F "file=@tests/fixtures/invoice-jp/clean/sample_001.png" \
  -H "X-Lang: ja"
```

**Expected**: Returns `document_id`, `fields` (registration_number, issuer_name, total_amount, etc.), `confidence`, `needs_review`.

### 2. Review: Approve

```bash
curl -X POST http://localhost:8000/v1/documents/{document_id}/approve \
  -H "X-Actor: operator@example.com" \
  -H "X-Reason: verified against source"
# Add -H "Authorization: Bearer <token>" when OPERATOR_BEARER_TOKEN is configured.
```

**Expected**: Document status → `approved`, audit log entry created with actor + reason.

### 3. Search

```bash
curl "http://localhost:8000/v1/search?q=適格請求書&mode=hybrid"
```

**Expected**: Extraction indexes the document before approval; search results
are not filtered by review status in this slice.

### 4. Audit Log

```bash
curl "http://localhost:8000/v1/audit?document_id={document_id}"
```

**Expected**: Shows `approve` action with actor and reason.

### 5. Review Console UI

Navigate to `http://localhost:8000/console/review` in a browser.

**Expected**:
- Document list shows documents needing review
- Keyboard shortcuts A/R/J/K/P navigate and act
- Confidence heatmap shows per-field color coding (green ≥ 0.85, yellow ≥ 0.70, red < 0.70)
- Approve/reject/patch actions persist with audit

## Automated Proof

```bash
cd "E:\Workspaces\pocr"
python -m pytest tests/e2e/test_invoice_jp_e2e.py -v
```

This route-level integration test uploads through the public API and replaces
only PaddleOCR with deterministic OCR output. It is not browser E2E, real OCR,
PDF, durability, or performance proof.

## Architecture Notes

- **Schema-driven**: Kernel reads YAML schema field definitions and dispatches to registered source functions — no hardcoded extraction branches
- **Validator registry**: Kernel uses `_VALIDATOR_HANDLERS` dict — new validator codes are added by registering a handler, not editing kernel code
- **Visual table detection**: OpenCV rule-line detection with borderless fallback, integrated via `table_def.source == "table_visual"` dispatch
- **Hybrid search**: `α·cosine(vec) + β·ts_rank(fts)` with in-memory repository, extensible to PostgreSQL
- **Review console**: Vanilla JS SPA, no build system, keyboard-first operator workflow
