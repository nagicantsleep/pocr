# Exec Plan

## Goal

Use PostgreSQL, Kafka, Redis, and OpenRouter as the production infrastructure
for structured OCR standardization jobs.

## Scope

In scope:

- Add PostgreSQL job persistence for raw OCR evidence and structured results.
- Publish standardization messages to Kafka.
- Add a worker that consumes Kafka, applies the Redis 20 req/min limiter,
  calls the existing standardizer provider boundary, validates with Pydantic,
  and updates PostgreSQL.
- Add retry and DLQ topic behavior for retryable and permanent failures.
- Expose job status/result through `GET /ocr/structured/jobs/{job_id}`.

Out of scope:

- Cloud deployment manifests.
- Database migration tooling beyond executable table bootstrap.
- Real OpenRouter account validation without credentials.

## Risk Classification

Risk flags:

- Data model.
- External systems.
- Public contracts.
- Weak proof.
- Multi-domain.

Hard gates:

- External provider behavior.

## Work Phases

1. Document the durable workflow and selected infrastructure roles.
2. Add repository, publisher, worker, and rate limiter code behind boundaries.
3. Change the file-upload structured route to return `202` queued jobs.
4. Add focused tests with faked PostgreSQL/Kafka boundaries.
5. Add live infrastructure validation before marking implemented.

## Stop Conditions

Pause for human confirmation if:

- The public `/ocr/structured` compatibility break is not acceptable.
- PostgreSQL schema ownership needs migration tooling before bootstrap DDL.
- OpenRouter retry semantics require a different backoff policy.
