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
docker exec paddleocr-postgres psql -U pocr -d pocr -c "SELECT job_id, status FROM structured_ocr_jobs ORDER BY created_at DESC LIMIT 5"
docker exec paddleocr-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list
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
- The worker fails only `running` rows older than
  `STRUCTURED_JOB_STALE_SECONDS` at startup, so restart recovery has an
  observable terminal outcome instead of leaving stale jobs indefinitely.
- On 2026-07-17, `docker compose -p pocr-proof -f docker-compose.cpu.yml
  --profile structured up -d --build` started the API, PostgreSQL, Kafka,
  Redis, mock standardizer, MinIO, and standardizer worker. `minio-init`
  completed after creating bucket `pocr`.
- On 2026-07-17, `POST /ocr/structured` accepted
  `structured_6932ffaa882640c2a50b89c90dbb70cb`; polling returned
  `success` with `structured_json.title=Mock OpenRouter Invoice`.
- The live PostgreSQL row for that job had `raw_ocr_json`, terminal
  `status=success`, `structured_json.title=Mock OpenRouter Invoice`, and
  `completed_at`. Kafka listed `ocr.standardize`, `ocr.standardize.retry`,
  and `ocr.standardize.dlq`; Redis key `standardizer:openrouter:minute`
  was `1`.
- A manually seeded `running` job older than 301 seconds,
  `structured_restart_7460918ff05e4b7d8522dfd9af1c1d68`, was changed to
  `failed` with a completed timestamp after restarting
  `structured-standardizer-worker`. The worker logged one recovered stale
  job.
- On the rebuilt stack, `structured_0c4a8e08bfd6412baafb8e359f790d2c`
  reached `success` with raw OCR evidence, `Mock OpenRouter Invoice`, and a
  completion timestamp. A delayed Kafka message for terminal job
  `structured_terminal_f05d7f04c29c407c847cfa579c159428` left it `failed`;
  the worker logged that it ignored the duplicate. A new stale-running
  fixture, `structured_restart_a8d710fb90fb479582f24cedfbed8eab`, recovered
  to `failed` after the rebuilt worker restarted.
- Retry-to-success fixture
  `structured_retry_fe573490256c447e9397f571a4545613` reached
  `success` with `structured_json` present and `error` cleared to `null`.
