# Stage 3 Handoff

**Date**: 2026-07-07
**Branch**: feature/document-ai-rebuild
**Commit**: 1607e00

## Summary

Schema-driven extraction kernel, field source registry, receipt-jp second schema, legacy adapter.

## Key Files

- `app/services/extraction_kernel/kernel.py` — extraction kernel dispatcher
- `app/services/extraction_kernel/source_registry.py` — field source registry
- `app/services/extraction_kernel/receipt_source_registry.py` — receipt-jp source bindings

## Evidence

| Gate | Threshold | Measured | Source |
|---|---|---|---|
| invoice-jp field F1 | >= 0.85 reg_no, total, date | TBD | test_extraction_kernel.py |
| receipt-jp field F1 | >= 0.80 | TBD | test_receipt_sources.py |
| Cross-field validator | catches bad fixtures | PASS | test_extraction_kernel.py |
| Schema-driven = legacy | structural diff | PASS | test_legacy_adapter.py |

## Gate Status

Kernel dispatches per schema. Receipt sources registered and resolvable. See `docs/TEST_MATRIX.md` for evidence.
