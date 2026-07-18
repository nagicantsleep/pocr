# JP Enterprise Hardening

## Status

In progress, high-risk initiative. The current increment routes the structured
compose `/v1` JP extraction, review, document, and audit path through
PostgreSQL plus a transactional Kafka outbox and MinIO artifacts. It does not
claim durable end-to-end completion.

## Current Behavior

The structured compose profile authenticates configured tenant principals and
uses durable document, extraction-job, review, audit, artifact, outbox,
consumer-receipt, search-chunk, and webhook-delivery records for the `/v1` JP
path. `invoice-extraction-worker` claims durable extraction jobs from Kafka;
the outbox worker builds tenant-scoped search projections and dispatches
webhooks. Local development remains explicitly in-memory unless
`INVOICE_JP_DURABLE_MODE=true`.

## Target Behavior

The JP document workflow supports tenant-isolated, restart-safe ingestion,
extraction, review, audit, search projection, and asynchronous processing:

- An authenticated tenant principal, not a caller-supplied actor header,
  identifies the tenant, subject, and granted roles for every protected action.
- Immutable source and derived artifacts live in tenant-scoped object storage;
  PostgreSQL holds the authoritative document, workflow, review, audit,
  idempotency, and outbox records.
- Transactional writes create an outbox record in the same PostgreSQL
  transaction. A publisher sends committed work to Kafka; consumers tolerate
  at-least-once delivery through durable deduplication and guarded transitions.
- An idempotency key is bound to the authenticated tenant principal and a
  canonical request fingerprint. It replays only the resource created by that
  matching request.
- Review decisions and patches cite the evidence snapshot and field provenance
  on which the operator acted. Audit entries are append-only product records.

## Affected Users

- Tenant members submitting and reading JP documents.
- Tenant reviewers approving, rejecting, or correcting extracted fields.
- Tenant administrators managing role grants and retention policy.
- Operators running API, outbox publisher, Kafka consumers, PostgreSQL, and
  object storage.

## Affected Product Docs

- `docs/product/ocr-api.md`
- `docs/stories/jp-receipt-slice/`
- `docs/TEST_MATRIX.md`
- `docs/decisions/0010-anchor-slice-complete.md`
- `docs/decisions/0011-jp-enterprise-durable-boundary.md`

## Non-Goals

- Retrofitting a production-complete claim onto the current in-process slice.
- Choosing a specific identity provider, billing model, SDK set, multi-region
  topology, or disaster-recovery target.
- Defining a public `/v2` endpoint shape before authentication, migration, and
  compatibility decisions are approved.
- Replacing PaddleOCR, schema-driven extraction, or the existing durable
  structured OCR standardization pipeline.
- Building real-time collaborative review, custom model training, or a new
  browser console.
