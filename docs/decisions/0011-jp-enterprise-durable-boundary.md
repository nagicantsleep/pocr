# 0011 JP Enterprise Durable Boundary

Date: 2026-07-17

## Status

Accepted

## Context

The JP receipt anchor slice deliberately uses in-process document, audit,
search, and webhook stores and trusts `X-Actor` for internal operator identity.
That is insufficient for tenant isolation, restart recovery, durable audit,
review traceability, and distributed worker processing. Existing structured
OCR jobs already establish PostgreSQL, Kafka, Redis, and worker infrastructure,
but that boundary does not make the JP document workflow durable.

## Decision

Future enterprise hardening of the JP workflow will use these boundaries:

- A parsed authenticated `TenantPrincipal` owns tenant identity and roles.
  Caller-supplied actor or tenant headers are not authorization inputs.
- Tenant-scoped object storage owns immutable source and derived artifact bytes.
  PostgreSQL owns document metadata, workflow state, review versions, audit,
  idempotency, transactional outbox, and consumer-deduplication records.
- PostgreSQL transaction commits create outbox records atomically with the
  business state. Kafka distributes only committed events and is not the
  system of record.
- Kafka consumers use durable event deduplication and guarded state
  transitions to tolerate at-least-once delivery, retries, and delayed work.
- Idempotency records bind the tenant principal scope, operation, key, and
  canonical request fingerprint to a durable resource and canonical response.
- Review actions reference immutable extraction evidence and create versioned,
  append-only audit records. Search and other projections consume committed
  events and are explicitly eventually consistent.

This is an architecture decision and a planned initiative, not evidence that
the current `/v1` JP API implements any of these guarantees.

## Alternatives Considered

1. Extend in-process stores with locks and trusted headers. Rejected because
   restart safety, horizontal scaling, and tenant authorization remain absent.
2. Publish Kafka work directly from request handlers. Rejected because a
   consumer can observe work that failed to commit in PostgreSQL.
3. Use Kafka as the authoritative record. Rejected because tenant-scoped
   queries, audit history, retention, and transaction constraints need a
   relational system of record.
4. Implement only PostgreSQL persistence. Rejected because asynchronous
   extraction, indexing, notification, retry, and failure isolation still
   need an explicit committed-work boundary.

## Consequences

Positive:

- Tenant ownership and authorization become enforceable across API, database,
  storage, workers, and audit.
- Restart recovery and distributed worker behavior become testable.
- Review decisions retain evidence provenance instead of only final fields.
- Existing Kafka infrastructure is reused without making Kafka the source of
  truth.

Tradeoffs:

- The migration requires schema, repository, storage, worker, and public
  contract work with live infrastructure proof.
- Outbox, consumer-deduplication, artifact cleanup, and versioned review
  records add operational and testing complexity.
- The current anchor-slice contract remains non-production until those
  changes are implemented and observed.

## Follow-Up

- Execute `docs/stories/jp-enterprise-hardening/` only after tenant roles,
  retention, and compatibility choices receive human confirmation.
- Keep `docs/product/ocr-api.md` describing present behavior until runtime
  implementation changes the public contract.
- Add matrix evidence only from observed PostgreSQL, object-storage, Kafka,
  worker, and multi-tenant proof.
