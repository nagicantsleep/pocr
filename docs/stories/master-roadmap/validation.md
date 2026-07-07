# Validation — Master Roadmap

Each tier has a **proof artifact** and a **gate metric**. No tier is "done" without both.

## Tier 0 — Foundation

| Gate | Metric | Threshold |
|---|---|---|
| Schema registry loads YAML → JSON schema → Pydantic | unit test | 100% of fixtures round-trip |
| Storage adapter put/get/delete + presigned URL | integration test | Local + S3 mock |
| Document type field present in `StructuredOCRData` | unit test | backward-compat for all current call sites |
| Audit log listing endpoint | API test | 10 invoices seeded, paginated, filterable |
| Webhook on job completion | integration test | consumer receives event within 5 s of `mark_success` |
| Idempotency for `/v1/jobs` | API test | duplicate key returns same `job_id` and result |

Existing test suite (`pytest tests/`) must remain green.

## Tier 1 — Pre-processing & multi-format

| Gate | Metric | Threshold |
|---|---|---|
| PDF multi-page ingestion | e2e test | 5-page PDF → 5-page Document; field accuracy = single-page accuracy |
| Deskew + denoise on noisy fixture | accuracy diff | ≥ +5% field accuracy vs no-preprocessing baseline |
| Quality gate | threshold sweep | reject rate ≤ 5% on golden set; false-reject rate = 0 |
| Language auto-detect on 5 languages | accuracy | ≥ 95% on fixture set |

Latency: p95 increase ≤ 200 ms per page on pre-processing chain.

## Tier 2 — Schema-driven form parser

| Gate | Metric | Threshold |
|---|---|---|
| Adding a new processor (no code change outside schema dir) | manual exercise | ≤ 1 day, with a unit test passing |
| receipt-jp field accuracy on validation set | F1 per field | ≥ 0.80 |
| Schema validation catches malformed extractions | unit test | 100% of bad fixtures rejected |
| Confidence calibration | reliability diagram | ECE ≤ 0.05 on validation set |
| Multi-language entity recognition | per-language F1 | ≥ 0.85 on labeled set for PERSON, ORG, MONEY, DATE |

Latency: synchronous `/v1/{processor}/extract` p95 ≤ 3 s for a single-page A4 invoice.

## Tier 3 — Visual structure & special tokens

| Gate | Metric | Threshold |
|---|---|---|
| Visual table detection on receipt-jp | accuracy | ≥ 0.90 region detection, ≥ +5% cell accuracy vs text-only |
| Rowspan / colspan detection | unit test | 100% of fixture tables correctly merged |
| Checkbox / signature detection | accuracy | ≥ 0.90 per region on labeled set |
| JP 印鑑 (seal) detection | accuracy | ≥ 0.80 region detection on Japanese fixtures |

No regression on invoice-jp accuracy.

## Tier 4 — Knowledge layer

| Gate | Metric | Threshold |
|---|---|---|
| Ingestion throughput | benchmark | 1,000 receipts indexed in ≤ 30 min on reference machine |
| `/v1/search` semantic + FTS | relevance | MRR ≥ 0.7 on 50-query labeled set |
| `/v1/search` latency | benchmark | p95 ≤ 500 ms on 10k documents |
| `/v1/qa` citation accuracy | manual eval | ≥ 90% answers cite correct `source_cells` |

## Tier 5 — Workbench

| Gate | Metric | Threshold |
|---|---|---|
| Review console loads 50 needs_review invoices | manual exercise | ≤ 30 minutes including approval |
| Ground-truth dataset manager versioning | unit test | uploads, version bump, old versions retrievable |
| Confidence calibration dashboard | manual exercise | shows per-field reliability, threshold tuning saves a config |
| Drift detection | unit test | simulated shift raises alert within one window |
| LLM provider A/B harness | integration test | both providers run side-by-side on same input, results diffable |

UI ships behind feature flag; no regression in API throughput p95.

## Tier 6 — Enterprise scale

| Gate | Metric | Threshold |
|---|---|---|
| Two tenants isolated | integration test | tenant A cannot read tenant B resources via API or DB |
| Quota enforcement | integration test | tenant exceeding quota returns 429 with `Retry-After` |
| DR restore time | DR drill | RTO ≤ 1 hour, RPO ≤ 5 minutes |
| SDK contract test | CI | `client-js`, `client-go`, `client-java`, `client-dotnet` pass contract suite against `/v1` |

## Cross-tier Validation

A `pytest tests/e2e/` suite runs after every tier and:

1. Loads golden fixtures for all processors shipped so far.
2. Calls `/v1/{processor}/extract` synchronously and async.
3. Compares extracted JSON to ground truth (within tolerance per field).
4. Asserts each response carries `schema_id`, `schema_version`, `document_type`, `quality_score`, and confidence.

Failure of any assertion blocks the tier from being marked complete.

## Reference Test Set

- Invoice fixtures: `tests/fixtures/invoice-jp/` — 50 real Japanese qualified invoices, labeled by hand.
- Receipt fixtures: `tests/fixtures/receipt-jp/` — 30 receipts covering 8%/10% tax, mixed formats.
- Edge fixtures: `tests/fixtures/edge/` — skew, blur, low DPI, vertical text, multi-page.

The set is **versioned** alongside the schema: every schema bump can be re-evaluated against the same fixtures.

## Done Definition (per tier)

A tier is done only when:

1. All gates above pass with the listed thresholds.
2. The `tests/e2e/` cross-tier suite is green.
3. A decision record (`docs/decisions/00NN-*.md`) is written.
4. `docs/TEST_MATRIX.md` is updated with proof rows.
5. A demo recording (or transcript) is added to `docs/stories/<tier>/demo.md`.