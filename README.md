# PaddleOCR REST API

A high-performance REST API for text recognition using PaddleOCR 3.5.0 with FastAPI.

## Features

- **Single Image OCR**: Upload images or send base64-encoded images for text recognition
- **Batch Processing**: Process up to 20 images in a single request
- **Async Jobs**: Submit large batch jobs for background processing with status polling
- **Multi-language Support**: English, Chinese, Japanese, Korean, French, German, and more
- **GPU Acceleration**: Optional GPU support via CUDA
- **Prometheus Metrics**: Built-in metrics for monitoring and observability
- **Docker Support**: Ready-to-deploy containers for CPU and GPU

## Quick Start

### Local Installation

```bash
# Clone or navigate to the project directory
cd /e/Workspaces/pocr

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env

# Run the API
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
# Build and run CPU-only deployment
docker-compose -f docker-compose.cpu.yml up --build

# Build and run GPU-only deployment (requires NVIDIA container runtime)
docker-compose -f docker-compose.gpu.yml up --build
```

## API Endpoints

### OCR Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /ocr` | Single Image | Upload an image file for OCR |
| `POST /ocr/json` | Single Image (JSON) | Send base64-encoded image |
| `POST /ocr/structured` | Structured Job | Upload an image file, run OCR, and queue structured standardization |
| `GET /ocr/structured/jobs/{job_id}` | Structured Job Status | Get structured OCR job status/result |
| `POST /ocr/batch` | Batch OCR | Upload multiple images |
| `POST /ocr/batch/json` | Batch OCR (JSON) | Send multiple base64 images |

### Job Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `POST /ocr/jobs` | Create Job | Submit async batch job |
| `GET /ocr/jobs/{job_id}` | Job Status | Get job status/results |
| `DELETE /ocr/jobs/{job_id}` | Cancel Job | Cancel a pending job |

### Health Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /health` | Health Check | Basic health status |
| `GET /health/ready` | Readiness | Readiness probe |
| `GET /health/live` | Liveness | Liveness probe |
| `GET /metrics` | Metrics | Prometheus metrics |

## Usage Examples

### Single Image OCR (curl)

```bash
# Upload a file
curl -X POST http://localhost:8000/ocr \
  -F "file=@image.jpg" \
  -H "X-Lang: en"

# With base64 image
curl -X POST http://localhost:8000/ocr/json \
  -H "Content-Type: application/json" \
  -d '{"image": "data:image/jpeg;base64,/9j/4AAQSk...", "lang": "en"}'
```

### Batch OCR (curl)

```bash
# Multiple files
curl -X POST http://localhost:8000/ocr/batch \
  -F "files=@image1.jpg" \
  -F "files=@image2.jpg" \
  -F "files=@image3.jpg"

# With base64
curl -X POST http://localhost:8000/ocr/batch/json \
  -H "Content-Type: application/json" \
  -d '{
    "images": ["base64string1", "base64string2"],
    "lang": "en",
    "min_confidence": 0.5
  }'
```

### Async Job (curl)

```bash
# Create job
curl -X POST http://localhost:8000/ocr/jobs \
  -H "Content-Type: application/json" \
  -d '{"images": ["base64string1", "base64string2"]}'
# Returns: {"job_id": "job_abc123", "status_url": "/ocr/jobs/job_abc123"}

# Check status
curl http://localhost:8000/ocr/jobs/job_abc123

# Cancel job
curl -X DELETE http://localhost:8000/ocr/jobs/job_abc123
```

## Configuration

All configuration is done via environment variables. Copy `.env.example` to `.env` and customize:

| Variable | Default | Description |
|----------|---------|-------------|
| `PADDLE_DEVICE` | `cpu` | Device: `cpu`, `gpu`, `gpu:0` |
| `MODEL_LANG` | `en` | Default OCR language |
| `MAX_IMAGE_SIZE_MB` | `20` | Maximum image size (MB) |
| `MAX_IMAGE_PIXELS` | `16777216` | Maximum image pixels |
| `MAX_BATCH_SIZE` | `20` | Maximum batch size |
| `DET_DB_THRESH` | `0.3` | Detection threshold |
| `USE_ANGLE_CLS` | `true` | Enable angle classification |
| `MIN_CONFIDENCE` | `0.0` | Minimum confidence filter |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `8000` | Bind port |
| `WORKERS` | `4` | Uvicorn workers |
| `LOG_LEVEL` | `INFO` | Logging level |
| `JOB_BACKEND` | `filesystem` | Job storage: `filesystem` or `redis` |
| `JOB_TTL_HOURS` | `24` | Job TTL in hours |

## API Documentation

FastAPI automatically generates API documentation:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Response Format

### Single OCR Response

```json
{
  "request_id": "uuid-string",
  "status": "success",
  "meta": {
    "engine": "paddleocr",
    "engine_version": "2.7.3",
    "model": "ch_PP-OCRv4_en",
    "lang": "en",
    "inference_time_ms": 1234,
    "image_width": 1920,
    "image_height": 1080,
    "was_resized": false
  },
  "results": [
    {
      "text": "Hello World",
      "confidence": 0.9823,
      "bbox": {
        "top_left": [100, 50],
        "bottom_right": [300, 90]
      },
      "bbox_normalized": {
        "top_left": [0.052, 0.046],
        "bottom_right": [0.156, 0.083]
      },
      "type": "text",
      "polygon": [[100,50], [300,50], [300,90], [100,90]]
    }
  ],
  "summary": {
    "total_lines": 1,
    "total_characters": 11,
    "avg_confidence": 0.9823
  }
}
```

## Error Handling

The API returns structured error responses:

| Status Code | Error Code | Description |
|-------------|------------|-------------|
| 400 | `image_empty` | Empty image data |
| 400 | `invalid_base64` | Invalid base64 encoding |
| 400 | `batch_too_large` | Batch exceeds limit |
| 413 | `file_too_large` | Image exceeds size limit |
| 415 | `unsupported_format` | Unsupported image format |
| 422 | `unreadable_image` | Corrupt/unreadable image |
| 404 | `job_not_found` | Job not found |
| 410 | `job_expired` | Job has expired |

## Development

### Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/test_ocr.py -v
```

### Project Structure

```
pocr/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Environment configuration
│   ├── routers/
│   │   ├── ocr.py           # OCR endpoints
│   │   ├── jobs.py          # Async job endpoints
│   │   └── health.py        # Health/metrics endpoints
│   ├── services/
│   │   ├── ocr_engine.py     # PaddleOCR wrapper
│   │   └── job_store.py     # Job storage backend
│   ├── schemas/
│   │   ├── requests.py      # Pydantic request models
│   │   └── responses.py    # Pydantic response models
│   └── utils/
│       ├── image_utils.py    # Image validation/processing
│       └── metrics.py       # Prometheus metrics
├── tests/
│   ├── test_ocr.py
│   ├── test_batch.py
│   └── test_async_jobs.py
├── docker-compose.app.yml
├── docker-compose.cpu.yml
├── Dockerfile.cpu
├── Dockerfile.gpu
├── requirements.txt
├── requirements-gpu.txt
├── .env.example
└── README.md
```

## License

MIT License
