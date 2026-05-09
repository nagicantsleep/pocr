# US-003 Durable Structured OCR Jobs

## Status

implemented

## Current Behavior

`/ocr/structured/json` can synchronously standardize OCR evidence through the
configured standardizer provider. The file-upload `/ocr/structured` path now
needs to become the durable production job entrypoint.

## Target Behavior

`POST /ocr/structured` runs PaddleOCR, persists OCR evidence and a queued job
row in PostgreSQL, publishes `{ "job_id": "...", "provider": "openrouter" }`
to Kafka, and returns `202 Accepted` with a `job_id`.

A standardizer worker consumes Kafka, uses Redis to enforce a shared
OpenRouter limit of 20 requests per minute, validates the provider response
with Pydantic, writes `structured_json` to PostgreSQL, and updates the job
status.

`GET /ocr/structured/jobs/{job_id}` returns `queued`, `running`, `success`, or
`failed` from PostgreSQL.

## Affected Users

- API clients submitting document images for structured OCR.
- Operators running API, worker, PostgreSQL, Kafka, Redis, and OpenRouter
  credentials.

## Affected Product Docs

- `docs/product/ocr-api.md`
- `docs/ARCHITECTURE.md`
- `docs/TEST_MATRIX.md`

## Non-Goals

- Do not add vendor enrichment or internal ID lookup.
- Do not weaken the evidence-only structured output rule.
- Do not remove the synchronous `/ocr/structured/json` test surface in this
  story.
