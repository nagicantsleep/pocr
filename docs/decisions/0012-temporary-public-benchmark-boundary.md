# 0012 — Temporary Public JP Benchmark Boundary

**Date:** 2026-07-18
**Status:** Accepted

## Context

The JP receipt slice has open evidence gates for field extraction, real-image
OCR, and table/layout behavior. The currently available public datasets do not
collectively satisfy the product's production-proof requirements.

## Decision

Use the three datasets pinned in
`docs/stories/jp-enterprise-hardening/temporary-benchmark-manifest.json` only
for temporary development benchmarks:

- Aulvem for text-only synthetic field-extraction regression.
- JaWildText `receipt_kie` for real-image date/total regression.
- OmniDocBench-JASyn for synthetic table/layout/reading-order regression.

Every report derived from these datasets is `development_only`. It must record
the immutable source revision and may not be used to mark a production gate
passed.

## Consequences

- Dataset-selection gates are closed without pretending that incomplete source
  semantics prove product accuracy.
- Existing legal-issuer, confidence, real qualified-invoice, 1,000/10,000,
  MRR, and production-release gates remain open.
- A future production corpus requires explicit license, provenance, field
  adjudication, and reference-machine approval before its manifest can become
  production-gate eligible.
