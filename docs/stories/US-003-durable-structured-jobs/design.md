# Design

## Domain Model

`structured_ocr_jobs` is the durable job record:

- `job_id`
- `provider`
- `status`: `queued`, `running`, `success`, `failed`
- `raw_ocr_json`
- `structured_json`
- `error`
- `created_at`
- `started_at`
- `completed_at`
- `updated_at`

## Application Flow

```text
POST /ocr/structured
  -> validate image
  -> PaddleOCR
  -> insert PostgreSQL job row with status=queued
  -> produce Kafka message to ocr.standardize
  -> return 202 + job_id

worker
  -> consume ocr.standardize or ocr.standardize.retry
  -> acquire Redis token at standardizer:openrouter:minute
  -> mark job running
  -> call OpenRouter through the standardizer boundary
  -> validate StructuredOCRData
  -> mark job success with structured_json
```

## Interface Contract

`POST /ocr/structured` returns:

```json
{
  "job_id": "structured_...",
  "status": "queued",
  "status_url": "/ocr/structured/jobs/structured_..."
}
```

Kafka message:

```json
{ "job_id": "structured_...", "provider": "openrouter" }
```

`GET /ocr/structured/jobs/{job_id}` returns the durable status and validated
structured result when available.

## Data Model

The API creates `structured_ocr_jobs` if it does not exist. Future production
deployments should replace bootstrap DDL with migration tooling before
multi-environment rollout.

## UI / Platform Impact

No browser, mobile, desktop, or CLI surface is added. Platform impact is runtime
operation of API, worker, PostgreSQL, Kafka, Redis, and OpenRouter credentials.

## Observability

Existing request metrics record the enqueue request. Worker logging records
rate-limit retries, provider errors, and crashes. Dedicated worker metrics are
still a proof gap.

## Alternatives Considered

1. Synchronous OpenRouter calls from the API. Rejected because provider latency,
   rate limits, and retries would make the request path fragile.
2. Redis-only queues. Rejected because the requested durable queue, retry
   topic, and dead-letter topic map better to Kafka.
