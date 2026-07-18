# OCR API

## Contract

The REST API accepts image uploads or base64 image payloads and returns a
successful OCR response with normalized text results, confidence scores,
bounding boxes, optional polygons, metadata, and summary counts.

For PaddleOCR 3.5.x, the OCR engine receives image input as a decoded RGB
`numpy.ndarray`, not raw encoded image bytes. Raw bytes are not a supported
PaddleOCR input type and must not be passed to the engine.

PaddleOCR 3.5.x result dictionaries may expose recognized text in `rec_texts`,
scores in `rec_scores`, and polygons in `dt_polys`. The API normalizes this
shape into the public `results[]` response.

## CPU Deployment Fixture Expectation

The CPU container must return non-empty OCR results for the fixture images in
`tests/fixtures/img*.png` when called with Japanese OCR language.

## Structured Output Boundary

The OCR service extracts evidence from images. It must not invent business
fields that are not present in the image.

The downstream structured JSON shape is represented by `sample.json`. Structured
output should contain only information supported by OCR/VLM evidence from the
source image. Fields that cannot be found in the image should be `null` or
omitted according to the downstream schema, not guessed.

The intended production flow is:

```text
image
  -> PaddleOCR OCR/VLM evidence extraction
  -> LLM standardizer for sample.json-compatible fields
  -> schema validation
  -> downstream JSON
```

PaddleOCR remains the extraction layer. The LLM standardizer is responsible for
mapping extracted evidence into the downstream contract, including enum labels,
dates, amounts, taxes, and `inputCostItems`.

The default standardizer provider is `heuristic`, which makes no external calls.
`STANDARDIZER_PROVIDER=openrouter` enables the OpenRouter OpenAI-compatible
chat-completions adapter. `STANDARDIZER_PROVIDER=openai` enables the direct
OpenAI Responses adapter. Both adapters request JSON schema output and the
service validates the returned JSON with Pydantic before responding.

## Durable Structured Job Flow

The production structured OCR flow is asynchronous and durable:

```text
POST /ocr/structured
  -> PaddleOCR
  -> PostgreSQL structured_ocr_jobs row with raw_ocr_json and status=queued
  -> Kafka ocr.standardize message
  -> standardizer worker
  -> Redis shared OpenRouter rate limit, 20 requests/minute
  -> OpenRouter standardizer
  -> Pydantic StructuredOCRData validation
  -> PostgreSQL structured_json and status=success
  -> GET /ocr/structured/jobs/{job_id}
```

`POST /ocr/structured` returns `202 Accepted` with `job_id`, `status=queued`,
and `status_url`. The queued row stores OCR evidence in `raw_ocr_json` and
leaves `structured_json` null until the worker succeeds.

`GET /ocr/structured/jobs/{job_id}` reads PostgreSQL and returns one of:

- `queued`
- `running`
- `success`
- `failed`

Retryable OpenRouter failures are HTTP 429, 502, 503, and 504. The worker
publishes retryable failures to `ocr.standardize.retry`; permanent failures are
marked `failed` and published to `ocr.standardize.dlq`.

## Version 1 JP Invoice API

| Method | Endpoint | Contract |
| --- | --- | --- |
| `POST` | `/v1/invoice-jp/extract` | Extract an uploaded PNG, JPEG, TIFF, or PDF and return the first document ID, fields, confidence, `needs_review`, and `page_count`. |
| `POST` | `/v1/invoice-jp/extract:async` | Schedule extraction and return a `job_id` with status `received`. |
| `GET` | `/v1/jobs/{job_id}` | Read the filtered job status and results; raw upload images are never returned. |
| `POST` | `/v1/jobs/{job_id}/cancel` | Cancel a queued or running job before its non-cancellable commit phase. |
| `GET` | `/v1/invoice-jp/{document_id}` | Read a stored JP invoice. |
| `POST` | `/v1/invoice-jp/{document_id}/approve` | Approve as the authenticated tenant principal; accepts optional `X-Reason`. |
| `POST` | `/v1/invoice-jp/{document_id}/reject` | Reject as the authenticated tenant principal; accepts optional `X-Reason`. |
| `PATCH` | `/v1/invoice-jp/{document_id}/fields` | Patch fields as the authenticated tenant principal; accepts optional `X-Reason` and `X-Force`. |
| `GET` | `/v1/documents` | List review documents. |
| `GET` | `/v1/search` | Search indexed document chunks. |
| `GET` | `/v1/audit` | List audit entries. |
| `POST`, `GET`, `DELETE` | `/v1/webhooks` | Register, list, or remove subscriptions. |

Extraction completion publishes `document.extraction_completed` with
`document_id`, status, document type, confidence, and `needs_review`.
`document.review_completed` is reserved for approve and reject actions.

`Idempotency-Key` is optional on extraction endpoints. The key binds the
normalized request bytes, content type, language override, and schema version.
It creates an expiring pending lease scoped to the authenticated tenant;
duplicate callers retain the owner resource and never delete-reclaim it. A
completed retry returns the persisted canonical representation. Same-resource
behavior depends on the configured idempotency store being reachable.
`OPERATOR_TOKEN_MAP` maps a bearer token to a tenant, user, and roles;
production fails closed when no identity map is configured. Review mutations
require `admin`, `operator`, or `reviewer` roles in production. Document, job,
audit, search, and webhook reads are tenant-filtered in this slice, but their
backing stores remain in-process and are not durable across restart.
