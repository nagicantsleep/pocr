# Harness Backlog

Use this file when an agent discovers a missing harness capability but should
not change the operating model immediately.

## Template

```md
## Missing Harness Capability

### Title

Short name.

### Discovered While

Task or story that exposed the gap.

### Current Pain

What was hard, repeated, ambiguous, or unsafe?

### Suggested Improvement

What should be added or changed?

### Risk

Tiny, normal, or high-risk.

### Status

proposed | accepted | implemented | rejected
```

## Items

## Missing Harness Capability

### Title

Durable structured stack validation.

### Discovered While

US-003 durable structured OCR jobs.

### Current Pain

The repo has no repeatable command that starts PostgreSQL, Kafka, Redis,
MinIO, the API, and the worker, then proves a fixture image moves from queued
to success or failed, checks a PostgreSQL row and Kafka topics, stores JP
artifacts through the S3 adapter, and verifies worker restart recovery. The
current CPU image also lacks `pytest`, so focused tests cannot run through the
documented pytest command until dependencies are rebuilt or a test image
exists.

### Suggested Improvement

Add a validation command or script that runs the structured compose profile,
submits fixture images, verifies Kafka-to-worker processing and PostgreSQL
state, performs a MinIO adapter round trip, and proves worker restart recovery
with a stale-job fixture. Keep the mock OpenRouter-compatible provider for
success, retry, and DLQ cases without real credentials.

### Risk

normal

### Status

proposed
