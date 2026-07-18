# Design

## Domain Model

### Tenant Principal

Every protected command and query receives a parsed `TenantPrincipal` from an
authenticated credential. It contains a stable `tenant_id`, `subject_id`,
granted roles, credential/session identifier when applicable, and request
correlation ID. `X-Actor` is not an authorization input in the target model.

Authorization happens before loading a resource. Every repository read and
write is scoped by `tenant_id`; IDs alone are never sufficient to locate a
document, job, review, audit record, or idempotency record.

### Durable Records

PostgreSQL is authoritative for metadata and state:

- `documents`, `document_versions`, `document_pages`, and extracted field
  snapshots reference immutable object-storage keys and content digests.
- `jobs` record workflow state, attempt count, lease/version, error summary,
  and the document version being processed.
- `review_decisions` and `audit_entries` append immutable actor, action,
  reason, evidence snapshot reference, and correlation data.
- `idempotency_records` bind tenant principal scope, request fingerprint,
  resource type/ID, state, response snapshot, expiry, and terminal outcome.
- `outbox_events` hold committed event envelopes until publication; consumer
  receipt/deduplication records prevent replaying business side effects.

All tenant-owned tables include `tenant_id`. Foreign keys and composite unique
indexes prevent cross-tenant references and enforce one active idempotency
record for its tenant, operation, and key. Database row-level security is an
implementation option, not a substitute for application authorization and
tenant-scoped repository predicates.

### Artifact Boundary

Object storage owns original uploads, rendered pages, OCR evidence, and
reviewable derived artifacts. PostgreSQL stores object keys, media type, byte
size, digest, retention class, and lifecycle state. A record never reports a
persisted artifact until its storage write is confirmed. Compensating cleanup
is required for an object written before a failed database transaction.

## Application Flow

```text
authenticated request
  -> parse TenantPrincipal
  -> authorize tenant action
  -> validate and fingerprint request
  -> create/replay idempotency record
  -> persist artifact metadata, document/job state, audit intent, and outbox
     record in PostgreSQL
  -> publish committed outbox envelope to Kafka
  -> worker claims job with guarded state transition
  -> write immutable extraction evidence and terminal state
  -> emit committed domain event for indexing, notification, or review work
```

Kafka is a delivery mechanism, not the source of truth. The outbox publisher
may retry publication; consumers must be idempotent and must not overwrite a
cancelled, failed, superseded, or completed terminal state. Retry and
dead-letter handling preserve the event ID, tenant ID, document version, and
causation/correlation IDs.

## Interface Contract

The exact public versioned API is deferred. The following rules are fixed:

- Protected reads and writes derive identity from authentication, never
  caller-supplied tenant or actor headers.
- Responses expose tenant-owned resource IDs and permitted metadata only; raw
  upload bytes, storage credentials, and cross-tenant existence signals are
  never returned.
- Idempotent create commands require a defined canonical fingerprint and
  return the original canonical response only for the same tenant, operation,
  key, and fingerprint. Key reuse with a different fingerprint is a conflict.
- Long-running operations return a durable resource reference; status reads
  are tenant-scoped and hide internal worker/provider detail.
- Event envelopes carry identifiers and safe metadata, not raw document bytes
  or secrets.

## Review Evidence

Review is evidence-aware rather than field-value-only:

- Extraction creates an immutable evidence snapshot with source artifact
  digest, schema/version, OCR or model provenance, field candidates, and
  confidence.
- Approve, reject, and patch commands reference the reviewed snapshot and
  record the reviewed version, actor, role, timestamp, reason, and field
  changes.
- A correction creates a new document/review version; it does not mutate the
  evidence used by a prior decision.
- Search and downstream projections consume committed document/review events.
  They are eventually consistent and must expose a projection version or
  freshness state when that matters to a caller.

## Observability And Operations

Each request, outbox envelope, worker attempt, and review decision carries
correlation and causation IDs. Operational logs exclude raw document content
and credentials. Product audit records are durable, tenant-scoped, append-only
records and are not replaced by application logs.

Metrics and alerting must cover authorization denials, idempotency conflicts,
outbox age/publish failures, consumer lag, duplicate suppression, transition
conflicts, artifact cleanup failures, retry/DLQ volume, and projection lag.

## Alternatives Considered

1. Keep in-process stores and add process-local locks. Rejected because restart,
   horizontal scale, tenant isolation, and audit durability remain unproven.
2. Publish Kafka messages before the database transaction commits. Rejected
   because consumers can observe work with no durable source record.
3. Use Kafka as the only durable record. Rejected because document queries,
   authorization, review history, retention, and transactional constraints
   require a queryable system of record.
4. Trust `X-Actor` plus tenant headers. Rejected because caller-controlled
   headers cannot establish tenant identity or authorization.
