"""Prometheus metrics for OCR API."""

import logging
from typing import Callable

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    REGISTRY,
)

logger = logging.getLogger(__name__)

# Custom registry for app metrics
APP_REGISTRY = REGISTRY

# Request counters
ocr_requests_total = Counter(
    "ocr_requests_total",
    "Total number of OCR requests",
    ["endpoint", "lang", "status"],
    registry=APP_REGISTRY,
)

# Request duration histogram
ocr_request_duration_seconds = Histogram(
    "ocr_request_duration_seconds",
    "OCR request duration in seconds",
    ["endpoint", "lang"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
    registry=APP_REGISTRY,
)

# Batch size histogram
ocr_batch_size = Histogram(
    "ocr_batch_size",
    "Batch size for batch OCR requests",
    ["job_type"],
    buckets=(1, 2, 5, 10, 15, 20, 25, 50),
    registry=APP_REGISTRY,
)

# Job queue depth
ocr_job_queue_depth = Gauge(
    "ocr_job_queue_depth",
    "Number of pending OCR jobs",
    registry=APP_REGISTRY,
)

# Inference time histogram
ocr_inference_time_seconds = Histogram(
    "ocr_inference_time_seconds",
    "OCR inference time in seconds",
    ["model", "device"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
    registry=APP_REGISTRY,
)

# Active workers
ocr_active_workers = Gauge(
    "ocr_active_workers",
    "Number of active OCR workers",
    registry=APP_REGISTRY,
)

# GPU memory usage (if available)
gpu_memory_usage_bytes = Gauge(
    "gpu_memory_usage_bytes",
    "GPU memory usage in bytes",
    ["device_id"],
    registry=APP_REGISTRY,
)

# Model loading status
model_ready = Gauge(
    "model_ready",
    "Whether OCR model is ready (1=ready, 0=loading)",
    ["model_type"],
    registry=APP_REGISTRY,
)


def record_request(
    endpoint: str,
    lang: str,
    status: str,
    duration: float,
    batch_size: int | None = None,
    job_type: str | None = None,
) -> None:
    """
    Record metrics for an OCR request.

    Args:
        endpoint: API endpoint (e.g., "/ocr", "/ocr/batch")
        lang: Language code used
        status: Request status (success, error)
        duration: Request duration in seconds
        batch_size: Number of images in batch (if applicable)
        job_type: Type of job (sync, async)
    """
    ocr_requests_total.labels(endpoint=endpoint, lang=lang, status=status).inc()
    ocr_request_duration_seconds.labels(endpoint=endpoint, lang=lang).observe(duration)

    if batch_size is not None and job_type is not None:
        ocr_batch_size.labels(job_type=job_type).observe(batch_size)


def record_inference(
    model: str,
    device: str,
    duration: float,
) -> None:
    """
    Record inference time metrics.

    Args:
        model: Model name used
        device: Device used (cpu, gpu)
        duration: Inference duration in seconds
    """
    ocr_inference_time_seconds.labels(model=model, device=device).observe(duration)


def increment_queue_depth() -> None:
    """Increment the job queue depth counter."""
    ocr_job_queue_depth.inc()


def decrement_queue_depth() -> None:
    """Decrement the job queue depth counter."""
    ocr_job_queue_depth.dec()


def set_model_ready(model_type: str, ready: bool) -> None:
    """
    Set the model ready status.

    Args:
        model_type: Type of model (det, rec, cls, combined)
        ready: Whether model is ready
    """
    model_ready.labels(model_type=model_type).set(1 if ready else 0)


# Invoice metrics (to be emitted when invoice features land)
INVOICE_EXTRACT_TOTAL = "invoice_extract_total"
INVOICE_EXTRACT_SUCCESS_TOTAL = "invoice_extract_success_total"
INVOICE_EXTRACT_ERROR_TOTAL = "invoice_extract_error_total"
INVOICE_EXTRACT_NEEDS_REVIEW_TOTAL = "invoice_extract_needs_review_total"
INVOICE_PROCESSING_DURATION_SECONDS = "invoice_processing_duration_seconds"
INVOICE_FIELD_CONFIDENCE_AVG = "invoice_field_confidence_avg"
INVOICE_VALIDATION_ERROR_TOTAL = "invoice_validation_error_total"
INVOICE_LINE_ITEMS_EXTRACTED_TOTAL = "invoice_line_items_extracted_total"
INVOICE_LINE_ITEMS_NEEDS_REVIEW_TOTAL = "invoice_line_items_needs_review_total"
INVOICE_LINE_ITEMS_CONFIDENCE_AVG = "invoice_line_items_confidence_avg"
INVOICE_TABLE_DETECTION_FAILED_TOTAL = "invoice_table_detection_failed_total"


def record_invoice_request(
    endpoint: str,
    status: str,
    duration: float,
    batch_size: int | None = None,
) -> None:
    """
    Record metrics for an invoice request.

    Args:
        endpoint: API endpoint (e.g., "/invoice/extract")
        status: Request status (success, error)
        duration: Request duration in seconds
        batch_size: Number of images in batch (if applicable)
    """
    ocr_requests_total.labels(endpoint=endpoint, lang="invoice", status=status).inc()
    ocr_request_duration_seconds.labels(endpoint=endpoint, lang="invoice").observe(duration)

    if batch_size is not None:
        ocr_batch_size.labels(job_type="sync").observe(batch_size)


def metrics_endpoint() -> tuple[bytes, str]:
    """
    Get Prometheus metrics in proper format.

    Returns:
        Tuple of (metrics_bytes, content_type)
    """
    return generate_latest(APP_REGISTRY), CONTENT_TYPE_LATEST
