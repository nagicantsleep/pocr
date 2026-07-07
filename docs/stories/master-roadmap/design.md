# Design — Master Roadmap

## Target Architecture

```
                                    ┌─────────────────────────┐
                                    │  Web Console (SPA)      │
                                    │  (review, label, train) │
                                    └────────────┬────────────┘
                                                 │
                                                 ▼
┌────────────────────────────────────────────────────────────────┐
│  API Gateway (FastAPI)                                         │
│  ────────────────────                                          │
│  /v1/{processor}/extract          — sync                        │
│  /v1/{processor}/extract:async    — durable                     │
│  /v1/jobs/{job_id}                — poll / webhook              │
│  /v1/search                       — semantic + FTS              │
│  /v1/qa                           — RAG grounded                │
│  /v1/datasets/{id}/labels         — labeling                    │
└────────────┬───────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────┐
│  Application Layer                                             │
│  ─────────────────                                             │
│  Processors:  invoice-jp / receipt-jp / passport / contract    │
│  Use cases:   Extract / Standardize / Validate / Review        │
│  Shared:      SchemaRegistry / StorageAdapter / EventBus       │
└────────────┬───────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────┐
│  Domain Layer                                                  │
│  ────────────                                                  │
│  Entities:   Document / Page / Region / Field / Table / Cell   │
│  Value objs: Confidence / Money / Date / Currency / Locale      │
│  Services:   LayoutAnalyzer / FieldExtractor / Validator       │
└────────────┬───────────────────────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────────────────────┐
│  Infrastructure Layer                                          │
│  ────────────────────                                          │
│  OCR Engine      PaddleOCR 3.5 (CPU/GPU, multi-lang)           │
│  Pre-processing  OpenCV (deskew, denoise, binarize, dewarping) │
│  PDF render      pdf2image / pymupdf                            │
│  Storage         Local / S3 / GCS / Azure Blob adapter         │
│  Persistence     PostgreSQL (jobs, audit, labels, embeddings)   │
│  Queue           Kafka (work / retry / DLQ)                    │
│  Cache / Limit   Redis (rate limit, idempotency)               │
│  Vector          pgvector / Qdrant / Vertex AI                  │
│  Search          Postgres FTS / OpenSearch                     │
│  LLM             OpenRouter / OpenAI / Anthropic / Bedrock     │
└────────────────────────────────────────────────────────────────┘
```

## Cross-cutting Concerns

### Schema Registry (tier 0/2 spine)

The schema registry replaces all hardcoded Pydantic models in `app/schemas/`. Each processor declares:

- `id`: stable identifier (e.g., `invoice-jp`)
- `version`: SemVer
- `document_type`: enum used by classifier
- `fields`: declarative list with type, source, validation, confidence formula
- `tables`: declarative table schema with column types
- `prompt_template`: LLM fallback prompt (if any)

Loading:

```python
registry = SchemaRegistry("schemas/")
schema = registry.load("invoice-jp", version="1.2.0")
extractor = ExtractorFactory.from_schema(schema)
```

### Storage Adapter (tier 0 spine)

```python
class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def presigned_url(self, key: str, ttl: int) -> str: ...
    def delete(self, key: str) -> None: ...
```

Concrete adapters:

- `LocalStorageAdapter(root: Path)`
- `S3StorageAdapter(bucket, region, ...)`
- `GcsStorageAdapter(bucket, ...)`
- `AzureBlobStorageAdapter(container, ...)`

Selected via `STORAGE_BACKEND` env.

### Event Bus (tier 0 spine)

Decouple producers from consumers via Kafka. Event types:

- `document.received`
- `document.ocr_completed`
- `document.extraction_completed`
- `document.review_completed`
- `document.indexed`

Every event carries:

```json
{
  "event_id": "uuid",
  "schema_id": "invoice-jp",
  "schema_version": "1.2.0",
  "occurred_at": "iso8601",
  "tenant_id": "...",
  "document_id": "...",
  "page_id": "...",
  "payload": { ... }
}
```

### Document Type Classifier (tier 0/2 spine)

Cheap first: keyword + layout heuristic. ML later.

```python
def classify(document_type_hint: str | None, pages: list[Page]) -> str: ...
```

Returns enum: `invoice-jp`, `receipt-jp`, `passport`, `contract`, `application-form`, `unknown`.

### Confidence Calibration (tier 2/5)

Per-processor calibration set. Tools:

- Isotonic regression on labeled validation set
- Per-field reliability diagrams
- Threshold tuning against user-accepted set

## Tier Boundaries

Tier 0 → 1 boundary: API exposes a `processor_id`. Pre-processing is invoked inside the processor; callers see only `Document` entities.

Tier 1 → 2 boundary: Schema registry is the only source of truth for fields and tables.

Tier 2 → 3 boundary: Visual detection adds geometry, not semantics.

Tier 3 → 4 boundary: Knowledge layer never modifies extraction; it only embeds and indexes extracted entities.

Tier 4 → 5 boundary: UI consumes the public API; no direct DB access.

## Compatibility Rules

- All API endpoints versioned under `/v1/`.
- Response envelope stable across schema versions for the same processor; breaking changes require `/v2/`.
- All times ISO 8601 UTC.
- All money values include `currency` field.

## Open Questions for Future Tiers

- pgvector vs Qdrant for embeddings (cost vs ops simplicity).
- Postgres FTS vs OpenSearch (scale vs ops).
- Labeling tool: Label Studio vs custom (cost vs integration).
- Online training (active learning) vs offline retraining cadence.