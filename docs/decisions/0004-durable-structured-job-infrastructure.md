# 0004 Durable Structured Job Infrastructure

## Status

accepted

## Context

Structured OCR standardization now needs durable job state, retriable work,
shared provider rate limiting, and asynchronous OpenRouter calls.

## Decision

Use PostgreSQL for structured OCR job state and final structured JSON, Kafka
for standardization work, retry, and dead-letter topics, Redis for the shared
20 requests/minute OpenRouter limiter, and OpenRouter through the existing
OpenAI-compatible standardizer boundary.

## Consequences

- `POST /ocr/structured` is a queued `202 Accepted` workflow instead of a
  synchronous structured result.
- API and worker runtimes both need PostgreSQL connectivity.
- API needs Kafka producer connectivity.
- Workers need Kafka consumer, Redis, PostgreSQL, and OpenRouter credentials.
- Live integration proof is required before the story is marked implemented.
