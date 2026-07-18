# Validation

## Proof Strategy

This initiative is not complete until live infrastructure proves tenant
isolation, durable recovery, exactly-once business effects under at-least-once
delivery, evidence-aware review history, and safe public behavior. Unit tests
or mocked adapters alone cannot establish these claims.

## Test Plan

| Layer | Cases |
| --- | --- |
| Unit | Parse claims into `TenantPrincipal`; role checks; canonical request fingerprint; idempotency state transitions; state-machine guards; event envelope validation; evidence snapshot/version rules. |
| Integration | PostgreSQL tenant predicates and constraints; object-storage confirmation and cleanup; transactional outbox commit/rollback; Kafka publish/retry/DLQ; consumer deduplication; idempotency contention and expiry. |
| E2E | Two tenants submit, read, review, search, and poll documents; each tenant receives only its own resources and audit entries. Browser proof is required if the review console is changed. |
| Platform | Restart API, publisher, and worker during accepted work; recover pending outbox/job state without duplicate review, search, webhook, or audit side effects. |
| Performance | Measure tenant-scoped upload, status, review, and search paths against approved workload and latency targets; no target is accepted until the reference environment is selected. |
| Logs/Audit | Correlate one request through audit, document version, outbox event, Kafka delivery, worker attempt, and review decision without exposing source bytes or credentials. |

## Required Adversarial Cases

- Tenant A cannot infer, read, patch, cancel, approve, reject, search, or
  receive events for Tenant B resources, including by guessed IDs.
- A principal without the required role receives no resource data and creates
  no durable business side effect.
- The same idempotency key with a different principal, operation, or request
  fingerprint cannot replay or overwrite an existing resource.
- Publisher failure after database commit eventually publishes one event; a
  database rollback publishes none.
- A duplicate or delayed Kafka delivery cannot duplicate document state,
  review audit, search index, webhook, or terminal transition.
- Storage failure, database failure, cancellation, and process restart leave
  no successful response that lacks the required durable record and artifact.
- A review decision remains traceable to its immutable evidence snapshot after
  later extraction or field corrections.

## Fixtures

- Two tenants with distinct administrators, submitters, reviewers, and
  unauthorized principals.
- Identical document bytes and idempotency keys across tenants.
- Object-storage failure/timeout and cleanup fixtures.
- PostgreSQL transaction rollback and concurrent idempotency fixtures.
- Kafka duplicate, delayed, reordered, retry, and dead-letter fixtures.
- A JP invoice with deterministic OCR evidence plus a later corrected
  extraction version.

## Commands

The local structured compose profile provisions PostgreSQL, Redis, Kafka,
MinIO, the JP outbox worker, the JP extraction worker, and deterministic
tenant proof tokens. The validation command chooses a free API port when
`8000` is occupied:

```text
powershell -ExecutionPolicy Bypass -File .\scripts\validate-jp-enterprise-live.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\validate-jp-failure-recovery-live.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\validate-jp-outbox-retry-dlq-live.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\validate-jp-webhook-recovery-live.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\validate-jp-console-live.ps1
python scripts/prepare-jawildtext-receipt-corpus.py --output data/jawildtext/receipt-kie --count 1000
```

Before this initiative is marked complete, record tenant-scoped PostgreSQL,
Kafka/outbox, worker, restart, and multi-tenant E2E evidence here.

## Acceptance Evidence

On 2026-07-17, the local profile started `paddleocr-minio` without publishing
host ports, so it did not conflict with the already occupied host ports 9000
and 9001. `paddleocr-minio-init` created bucket `pocr`.

`POST /v1/invoice-jp/extract` accepted `tests/fixtures/img1.png` and returned
document `626b1ef1-a43f-4e7f-a467-7980e215e6d6`. A live MinIO listing showed
both `documents/626b1ef1-a43f-4e7f-a467-7980e215e6d6/raw` and
`documents/626b1ef1-a43f-4e7f-a467-7980e215e6d6/extracted.json`.
An in-container `S3StorageAdapter` scratch-key put/get/exists/delete round
trip also passed.

After moving blocking boto3 calls off the request event loop, the rebuilt API
accepted another invoice upload as `4f5b316c-7a5d-4bfd-8390-0c151b2ee48a`;
MinIO contained both its `raw` and `extracted.json` artifacts. Focused local
storage, S3 adapter, and worker tests passed `15/15`.

On 2026-07-17, a rebuilt local profile accepted
`tests/fixtures/invoice-jp/clean/sample_001.png` for tenant A as
`c4ca495e-20b7-4430-be6b-90444d63ef53`. Tenant B received `404` for the
guessed ID. Tenant A approval produced PostgreSQL document version `2` and
append-only `create`/`approve` audits. Both committed outbox rows had
`published_at`; restarting the API preserved tenant-A read access and
tenant-B denial. MinIO listed `raw` and `extracted.json`. Republishing an
existing Kafka envelope left completed consumer receipts unchanged (`2 -> 2`).

On 2026-07-17, `POST /v1/invoice-jp/extract:async` accepted
`sample_001.png` as job `job_a07ac9ad4c954b5db0f3fd91bd3a0969`. PostgreSQL
recorded the durable job, replayed the same idempotency key to that job, and
the extraction worker completed it once. The job, document, MinIO `raw` and
`extracted.json`, and tenant-A-only keyword search survived API, outbox, and
extraction-worker restarts. Republishing the completed Kafka envelope left
consumer receipts unchanged (`1 -> 1`).

The same profile accepted a generated five-page PDF derived from the checked-in
JP fixture. The public synchronous route returned `page_count=5`; PostgreSQL
held five documents and five committed extraction events, while MinIO retained
the original PDF plus the first page's immutable artifacts.

A real HTTPS receiver at `https://httpbin.org/post` accepted one
`document.extraction_completed` delivery with HTTP `200`. The durable delivery
record remained at one attempt after a duplicate Kafka envelope. This proves
the sender's retry-safe local effect; receivers must still deduplicate
`X-Webhook-Event-Id` for the unavoidable crash window after an external `2xx`.

Playwright loaded the review console with a tenant token, opened approval with
the `A` shortcut, and confirmed it with `Ctrl+Enter`. PostgreSQL recorded one
`approve` audit with reason `browser-live-proof`. Two concurrent approve calls
returned `200` and `409`; the document remained version `2` with one approve
audit.

On 2026-07-17, a 20-page PDF async job reached `running` with its MinIO
artifact candidates journaled in PostgreSQL. The operator cancelled it, the
extraction worker was killed, and a restarted worker removed the source plus
all journaled derived MinIO objects. The terminal job stayed `cancelled` with
no document, audit, or extraction-completed outbox record.

On 2026-07-17, `scripts/validate-jp-outbox-fencing-live.ps1` stopped the
outbox worker, used the running PostgreSQL-backed application repository to
reclaim expired outbox, consumer-receipt, and webhook-delivery leases, then
restarted the worker. In each case, the stale owner was rejected and only the
new fencing token could commit the terminal state. The script deletes its
synthetic proof rows before restarting the worker.

On 2026-07-18, `scripts/validate-jp-failure-recovery-live.ps1` proved the
durable synchronous path stays idempotent while Redis is stopped and after it
is restarted, concurrent same-key requests converge on one document, and an
expired PostgreSQL idempotency record is reclaimed. It also forced a
multi-write PostgreSQL transaction rollback and observed zero invoice, audit,
and outbox rows. A stopped MinIO returned `503` without an idempotency record
or job; a temporary database trigger then forced queue rollback after a real
MinIO source `PUT`, and MinIO trace recorded the matching `DELETE` with no
job, outbox, or idempotency record left behind.

On 2026-07-18, `scripts/validate-jp-outbox-retry-dlq-live.ps1` published one
invalid envelope into the running Kafka source topic. The outbox worker
published three delayed retries and then one DLQ envelope with
`delivery_attempt=4` and the original validation error. The script removes
its PostgreSQL proof rows; Kafka retains the local evidence message.

On 2026-07-18, `scripts/validate-jp-console-live.ps1` used Playwright against
the running durable stack. It proved shortcuts `R`, `J`, `K`, and `P`, patch,
reject, and approve audit rows, then approved 50 scoped documents in
`00:00:18.8896547`. The validator deletes all scoped proof documents after
the run.

On 2026-07-18, `scripts/validate-jp-webhook-recovery-live.ps1` created a
tenant-scoped public subscription to `https://httpbin.org/status/500`,
submitted a real extraction, observed the durable external failure, changed
the receiver to `https://httpbin.org/status/200`, and observed completion
under a new durable delivery lease (`claims=2->3`). It stops the outbox worker
before deleting only its generated delivery, event, document, and subscription
records, then restarts the worker.

On 2026-07-18, `scripts/prepare-jawildtext-receipt-corpus.py` verified and
pinned the public Apache-2.0 `llm-jp/jawildtext` `receipt_kie` revision
`627ca7ea7c224ffe1accff8737991fc2240784fa`. The rebuilt local API then ran
the same two-image public-route smoke corpus. OCR had split total labels as
`合言十`; the extractor now matches that label to a nearby right-aligned
currency cell, producing total F1 `1.0`. The evaluator also treats Japanese
date formatting and JPY presentation as lossless equivalents, producing date
F1 `1.0`. Legal issuer F1 remains `0.0` because the source label is a store
name while the product field is a legal issuer; ECE remains `0.4309`, above
the ≤0.05 threshold. These are partial real-data results, not acceptance
evidence. The source has line-item polygons but no explicit table-region
labels, so it cannot close invoice, receipt, table, or calibration gates.
The corpus preparer now requires image assets to contain the captured immutable
revision and marks the resulting metadata ineligible for production gating
until legal-issuer adjudication exists.

The rebuilt local API now uses a tenant-scoped direct PostgreSQL keyword-chunk
query rather than reconstructing 200 documents before every keyword search.
This removes that structural ceiling but is not a 10k latency proof.

Still unverified: adjudicated JP invoice fields and table regions; a 50-query
relevance set over a fully indexed corpus; a 1,000-document ingest; a licensed
10,000-document JP workload; semantic/hybrid vector scale; and a selected
reference machine with the required throughput and p95 artifacts.
