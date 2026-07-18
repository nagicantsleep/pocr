# Temporary JP Benchmark Boundary

**Status:** accepted temporary development benchmark; not a production gate.

This three-source set closes only dataset-selection and development-regression
gates. Every run must save the source revision, command, result JSON, and the
`development_only` scope. It does not change the product thresholds in
`docs/stories/jp-receipt-slice/validation.md`.

The machine-readable source of truth is
`docs/stories/jp-enterprise-hardening/temporary-benchmark-manifest.json`.

## Closed Temporary Gates

| Temporary gate | Source | Closed scope | Required run evidence |
| --- | --- | --- | --- |
| Field-extraction regression corpus selected | `Aulvem/japanese-invoice-receipt-extraction-eval` | Text-only synthetic checks for issuer, registration number, date, tax, total, and line items across 20 invoices plus 10 receipts | Pinned revision, all 30 records fetched, field-level development report |
| Real-image OCR date/total corpus selected | `llm-jp/jawildtext` `receipt_kie` | Public real-receipt image regression for date and total only | `scripts/prepare-jawildtext-receipt-corpus.py` manifest plus public-route report |
| Table/layout regression corpus selected | `stockmark/OmniDocBench-JASyn` | Synthetic image layout, table, and reading-order regression across 518 annotated pages | Pinned annotation file, image inventory, region/table/reading-order report |

The selection gates are closed on 2026-07-18 because the dataset cards,
revisions, licenses, formats, and annotation boundaries were checked and
captured in the manifest. Metric gates close only after their listed report
exists.

## Required Boundaries

- Aulvem is text-only and synthetic under `CC-BY-NC-4.0`; use it for
  development regression, never real-image OCR or a commercial/production
  acceptance claim.
- JaWildText is public real image data under `Apache-2.0`, but `store_name`
  is not the product's adjudicated legal issuer. Score only date and total.
- OmniDocBench-JASyn is synthetic. Its 518-page annotation supports temporary
  table/layout/reading-order regression, not qualified-invoice field accuracy.
- These sources do not close legal-issuer, confidence calibration, 1,000
  ingest, 10,000-document latency, semantic/keyword/hybrid MRR, or production
  release gates.

## Reproducible Acquisition

Use immutable revisions, not a branch name. Keep downloaded corpora outside
Git-tracked fixtures and retain the generated manifests/reports as task
evidence.

```powershell
python scripts/prepare-jawildtext-receipt-corpus.py `
  --output data/jawildtext/receipt-kie --count 1000 `
  --revision 627ca7ea7c224ffe1accff8737991fc2240784fa
```

For Aulvem and OmniDocBench-JASyn, download the manifest's declared immutable
artifact URLs, then verify the stated SHA-256 and record count before running
an adapter-specific development report. JaWildText's preparer records a SHA-256
for each downloaded image and rejects any image URL outside the requested
revision. Do not set
`production_gate_eligible=true` for any artifact derived from this manifest.

## Open Production Gates

The production gate requires a commercially permitted, adjudicated JP
qualified-invoice/receipt corpus that covers legal issuer and table regions,
plus observed reference-machine reports for ingest, latency, and relevance.
Until then, `docs/stories/jp-receipt-slice/validation.md` remains authoritative
and the slice stays `in_progress`.
