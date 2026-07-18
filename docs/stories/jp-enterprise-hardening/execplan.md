# Exec Plan

## Goal

Move the JP document workflow from an anchor-slice, in-process boundary to a
tenant-isolated durable architecture without weakening current proof rules.

## Scope

In scope:

- Tenant-principal authentication and role-based authorization design.
- PostgreSQL ownership for document, workflow, review, audit, idempotency,
  outbox, and consumer-deduplication records.
- Tenant-scoped object storage for immutable source and derived artifacts.
- Kafka/outbox publication, worker retry/DLQ behavior, and guarded state
  transitions.
- Evidence-aware review and eventual-consistency rules for search projections.
- Migration, compatibility, retention, observability, and validation plans.

Out of scope:

- Deployment changes, public API versioning, or a durable-completion claim.
- Specific identity provider, billing/quota implementation, multi-region DR,
  SDKs, custom model training, or collaborative review.

## Risk Classification

Risk flags:

- Authorization
- Data model
- Audit/security
- External systems
- Public contracts
- Weak proof
- Multi-domain

Hard gates:

- Authorization
- Audit/security
- Durable data migration

## Work Phases

1. Confirm tenant ownership, roles, retention requirements, and compatibility
   expectations with the product owner before public-contract work.
2. Define PostgreSQL schema, tenant indexes/constraints, object-storage key
   rules, artifact lifecycle, migration/backfill, and rollback strategy.
3. Introduce repository boundaries and authenticated-principal enforcement
   before replacing in-process reads or writes.
4. Add transactional outbox publication, consumer receipt/deduplication,
   retry/DLQ handling, and conditional job transitions.
5. Migrate idempotency to durable tenant-bound records and verify replay,
   contention, expiry, and fingerprint-conflict behavior.
6. Add immutable extraction evidence snapshots, versioned review decisions,
   audit records, and search-projection freshness behavior.
7. Run live PostgreSQL, object-storage, Kafka, and worker proof before
   announcing any durable or tenant-isolation milestone.
8. Update product contracts, test matrix evidence, decision follow-ups, and
   Harness trace only from observed results.

## Stop Conditions

Pause for human confirmation if:

- The tenant/role model, retention obligations, or external identity boundary
  is ambiguous.
- Existing data needs destructive migration, deletion, or an irreversible
  backfill.
- A compatibility change requires a public API version decision.
- A proposal weakens tenant isolation, audit completeness, or validation
  requirements.
- Object storage, PostgreSQL, Kafka, or a worker cannot be exercised in a
  reproducible environment.
