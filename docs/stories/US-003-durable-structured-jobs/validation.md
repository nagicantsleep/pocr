# Validation

## Proof Strategy

Unit tests prove route behavior and boundary messages with faked PostgreSQL and
Kafka adapters. Integration proof must run against live PostgreSQL, Kafka, and
Redis. Provider proof must use either a mocked OpenRouter-compatible endpoint
or real credentials with a deterministic fixture.

## Test Plan

| Layer | Cases |
| --- | --- |
| Unit | `/ocr/structured` returns `202` and publishes `{ job_id, provider }`; status route serializes `success`; worker marks success, maps retryable provider errors to retry topic, retries before provider call when Redis denies a token, and marks permanent failures failed with DLQ publish. |
| Integration | API inserts PostgreSQL row; Kafka message is produced; worker consumes and updates row; retry and DLQ topics receive expected messages. |
| E2E | Client submits fixture image, polls status, and receives validated structured JSON. |
| Platform | Compose or deployment smoke starts API, worker, PostgreSQL, Kafka, and Redis. |
| Performance | Redis limiter enforces 20 OpenRouter calls per minute across workers. |
| Logs/Audit | Worker logs job id, topic path, retry/DLQ decisions, and provider failures without leaking API keys. |

## Fixtures

- `tests/fixtures/img*.png`
- Mock OpenRouter chat-completions response compatible with
  `StructuredOCRData`
- PostgreSQL `structured_ocr_jobs` table
- Kafka topics: `ocr.standardize`, `ocr.standardize.retry`,
  `ocr.standardize.dlq`
- Redis key: `standardizer:openrouter:minute`

## Commands

```text
python -m compileall app tests
pytest tests/test_ocr.py tests/test_structured_worker.py -q
docker compose -f docker-compose.cpu.yml --profile structured up -d --build
curl -X POST http://localhost:8000/ocr/structured -F "file=@tests/fixtures/img1.png" -H "X-Lang: japan"
curl http://localhost:8000/ocr/structured/jobs/{job_id}
```

## Acceptance Evidence

- `python -m compileall app tests` passed on host Python.
- `docker run --rm -v ${PWD}:/work -w /work pocr-ocr-api-cpu python -m compileall app tests` passed.
- Direct FastAPI TestClient smoke in the CPU image passed for
  `POST /ocr/structured` returning `202` and
  `GET /ocr/structured/jobs/{job_id}` returning `success`.
- Direct worker smoke in the CPU image passed for consume-to-success behavior.
- Direct worker smoke in the CPU image passed for retryable 429 behavior
  publishing to `ocr.standardize.retry` with attempt, backoff seconds, and
  `available_at`.
- `docker compose -f docker-compose.cpu.yml --profile structured config --quiet`
  passed.
- Focused pytest passed in the rebuilt CPU image after installing pytest in the
  disposable test container: `14 passed`.
- Structured compose profile started API, worker, PostgreSQL, Kafka, Redis, and
  a local OpenRouter-compatible mock.
- `POST /ocr/structured` with `tests/fixtures/img1.png` returned `202` and
  `job_id=structured_82e9708ce3f54c2ca2290558bc366ecf`.
- `GET /ocr/structured/jobs/structured_82e9708ce3f54c2ca2290558bc366ecf`
  returned `success` with `structured_json.title=Mock OpenRouter Invoice`.
- Direct PostgreSQL query showed the same job with `status=success`,
  `raw_ocr_json is not null`, `structured_json.title=Mock OpenRouter Invoice`,
  and `completed_at is not null`.
- Redis contained `standardizer:openrouter:minute=1` with a positive TTL after
  the worker ran.
- Kafka topics `ocr.standardize`, `ocr.standardize.retry`, and
  `ocr.standardize.dlq` exist.
