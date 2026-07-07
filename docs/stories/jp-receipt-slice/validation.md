# Validation — Anchor Slice (Japanese Receipt / Qualified Invoice)

## Gate Structure

Each stage has a **gate** that must pass before the next stage begins. Gates are testable, versioned, and tied to the master roadmap tier the stage exercises.

---

## Stage 1 — Foundation substrate

| Gate | Metric | Threshold |
|---|---|---|
| Schema registry loads `invoice-jp/v1.0.0.yaml` | unit test | round-trips YAML → JSON schema → Pydantic |
| Storage adapter put/get/delete + presigned URL | integration test | Local + S3 mock pass |
| Document type classifier picks `qualified_invoice` on JP fixture | unit test | 100% of clean fixtures |
| Audit log listing endpoint | API test | pagination + filtering correct on 10 seeded rows |
| Webhook fires within 5 s of job completion | integration test | consumer receives `document.review_completed` |
| Idempotency key returns same `job_id` | API test | duplicate POST returns identical body |
| Existing test suite green | `pytest` | 100% |

**Stop condition**: any existing test fails.

---

## Stage 2 — Pre-processing & multi-format

| Gate | Metric | Threshold |
|---|---|---|
| PDF multi-page ingestion | e2e test | 5-page PDF → 5-page Document |
| Deskew + denoise on `tests/fixtures/invoice-jp/skewed/` | field F1 | ≥ clean baseline |
| Quality gate on `tests/fixtures/invoice-jp/noisy/` | reject rate | ≤ 5% false reject |
| Quality gate on golden set | reject rate | 0% false reject |
| Language auto-detect on 5 fixtures | accuracy | ≥ 95% |
| End-to-end p95 latency | benchmark | ≤ 2.5 s single page, CPU |

**Stop condition**: skewed/noisy accuracy < clean baseline.

---

## Stage 3 — Schema-driven extractor

| Gate | Metric | Threshold |
|---|---|---|
| `invoice-jp` field F1 on `tests/fixtures/invoice-jp/clean/` | per-field F1 | ≥ 0.85 registration_number, total_amount, transaction_date; ≥ 0.80 issuer_name, line_items |
| `receipt-jp` field F1 on receipt fixtures | per-field F1 | ≥ 0.80 |
| Schema-driven path produces same output as legacy hardcoded path | diff test | structural equality |
| Adding a new processor with no code change outside schema dir | manual exercise | ≤ 1 day |
| Cross-field validator (subtotal + tax = total) | unit test | catches all bad fixtures |
| Confidence calibration | reliability diagram | ECE ≤ 0.05 |

**Stop condition**: schema abstraction costs > 2x the lines saved; revert to hardcoded processors and revisit.

---

## Stage 4 — Visual table detection

| Gate | Metric | Threshold |
|---|---|---|
| Table region detection on `tests/fixtures/invoice-jp/edge/table-heavy/` | accuracy | ≥ 0.90 region detection |
| Cell assignment accuracy vs text-only | improvement | ≥ +5% on borderless fixtures |
| Rowspan / colspan on multi-merge fixtures | unit test | 100% correctly merged |
| invoice-jp accuracy regression | e2e | no drop ≥ 0.02 on clean fixtures |
| Visual detection p95 latency per page | benchmark | ≤ 300 ms added |

**Stop condition**: invoice-jp accuracy drops on any fixture subset.

---

## Stage 5 — Search & review API

| Gate | Metric | Threshold |
|---|---|---|
| Ingest 1,000 receipts end-to-end | throughput | ≤ 30 min on reference machine |
| `/v1/search?q=...&mode=semantic` | relevance | MRR ≥ 0.7 on 50-query labeled set |
| `/v1/search?q=...&mode=keyword` | relevance | MRR ≥ 0.7 on labeled set |
| `/v1/search` p95 latency on 10k docs | benchmark | ≤ 500 ms |
| Hybrid ranking vs single-mode | relevance | hybrid ≥ either single mode alone |
| Review API: list / approve / reject / patch with audit | integration test | every action persists + audit log entry |
| Webhook retries on consumer failure | integration test | exponential backoff, ≤ 5 attempts |

**Stop condition**: relevance below threshold or latency exceeds budget.

---

## Stage 6 — One-page review console UI

| Gate | Metric | Threshold |
|---|---|---|
| Load 50 needs_review invoices | manual exercise | ≤ 30 minutes including approval |
| Approve / reject / patch each persist to DB | integration test | 100% |
| Audit log captures actor + reason | unit test | every action has both fields |
| Keyboard shortcuts work | manual test | A/R/J/K navigate and act |
| API p95 latency unchanged | benchmark | no regression |

**Stop condition**: any review action fails to persist.

---

## End-to-End Test (slice-level)

`tests/e2e/test_invoice_jp_e2e.py`:

```python
def test_jp_invoice_e2e():
    # 1. Upload
    job = client.post("/v1/invoice-jp/extract:async",
                      files={"file": ("inv.pdf", pdf_bytes, "application/pdf")},
                      headers={"Idempotency-Key": "k-1"}).json()
    job_id = job["job_id"]

    # 2. Poll
    doc = poll_until_done(client, f"/v1/jobs/{job_id}")

    # 3. Assert extracted fields
    assert doc["structured_json"]["issuer_registration_number"] == "T1234567890123"
    assert doc["structured_json"]["total_amount"]["value"] >= 0
    assert doc["structured_json"]["line_items"]

    # 4. Review console approve
    client.post(f"/v1/invoice-jp/{doc['id']}/approve", headers={"X-Actor": "user-1"})

    # 5. Search
    hits = client.get("/v1/search",
                      params={"q": doc["structured_json"]["issuer_name"]}).json()
    assert any(h["document_id"] == doc["id"] for h in hits["results"])
```

This test is the **single proof artifact** that the slice is complete.

---

## Reference Test Set

- `tests/fixtures/invoice-jp/clean/` — 50 hand-labeled real JP qualified invoices.
- `tests/fixtures/invoice-jp/skewed/` — 20 synthetic skews.
- `tests/fixtures/invoice-jp/noisy/` — 20 noisy scans.
- `tests/fixtures/invoice-jp/multi-page/` — 10 PDFs.
- `tests/fixtures/invoice-jp/edge/` — refund, zero tax, mixed rates, vertical text.
- `tests/fixtures/receipt-jp/` — 30 receipts.

Fixtures are **versioned** alongside the schema. Bumping schema version allows re-evaluation against the same fixtures.

---

## Quality Floor (per stage)

If any of the following triggers, pause and fix before continuing:

- Existing test suite regression.
- New code with > 80% coverage drop vs project average.
- Latency exceeds budget by > 20%.
- Any p0 demo blocker.

## Done Definition (slice)

The anchor slice is done when:

1. All six stage gates pass with the listed thresholds.
2. `tests/e2e/test_invoice_jp_e2e.py` is green.
3. `docs/stories/jp-receipt-slice/demos/final.md` records the e2e walkthrough with timestamps.
4. `docs/decisions/0010-anchor-slice-complete.md` records outcomes and lessons.
5. `docs/TEST_MATRIX.md` has rows for every gate.
6. A **demo recording** (screen capture or transcript) is checked into the story folder.

## Anti-Patterns to Watch

- Stop at "API contract changes" without end-to-end test.
- Reach "search works" without relevance validation against labeled set.
- Claim "schema-driven" while still having hardcoded branches in the kernel.
- Mark console UI "done" without keyboard + audit verification.

Any of these triggers a hold until corrected.