"""Health check and metrics router."""

import logging
import sys
from typing import Optional

from fastapi import APIRouter, Response

from app.config import get_settings
from app.schemas.responses import HealthResponse
from app.services.ocr_engine import is_engine_ready
from app.utils.metrics import metrics_endpoint, model_ready

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


def check_gpu_available() -> bool:
    """
    Check if GPU is available for PaddleOCR.

    Returns:
        True if GPU is available
    """
    try:
        import paddle

        # Check for GPU availability
        if paddle.is_compiled_with_cuda():
            return True
        return False
    except ImportError:
        return False
    except Exception as e:
        logger.warning(f"GPU check failed: {e}")
        return False


@router.get(
    "",
    response_model=HealthResponse,
)
async def health_check():
    """
    Basic health check endpoint.

    Returns service status and engine information.
    """
    gpu_available = check_gpu_available()

    return HealthResponse(
        status="ok" if is_engine_ready() else "loading",
        engine="paddleocr",
        gpu_available=gpu_available,
        version="3.5.0",
    )


@router.get(
    "/ready",
    responses={
        200: {"description": "Service Ready"},
        503: {"description": "Service Not Ready"},
    },
)
async def readiness_check():
    """
    Readiness probe for Kubernetes/container orchestration.

    Returns 200 if OCR models are loaded and ready.
    Returns 503 if still loading or unavailable.
    """
    if is_engine_ready():
        return {"status": "ready", "message": "OCR engine is ready"}
    else:
        return Response(
            content='{"status": "not_ready", "message": "OCR engine still loading"}',
            status_code=503,
            media_type="application/json",
        )


@router.get(
    "/live",
    responses={
        200: {"description": "Service Alive"},
    },
)
async def liveness_check():
    """
    Liveness probe for Kubernetes/container orchestration.

    Returns 200 if the service process is alive.
    """
    return {"status": "alive", "message": "Service is running"}


@router.get(
    "/metrics",
    include_in_schema=True,
)
async def get_metrics():
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format.
    """
    metrics_bytes, content_type = metrics_endpoint()
    return Response(content=metrics_bytes, media_type=content_type)
