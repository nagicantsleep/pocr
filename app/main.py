"""FastAPI application entry point for PaddleOCR REST API."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import ocr, jobs, health
from app.services.ocr_engine import get_ocr_engine, is_engine_ready
from app.utils.metrics import set_model_ready

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for lazy OCR engine initialization.

    - On startup: Don't load PaddleOCR here (lazy load on first request)
    - Store ready flag in app.state
    - On shutdown: Cleanup if needed
    """
    settings = get_settings()

    # Initialize state
    app.state.ocr_ready = False
    logger.info("Application starting - OCR engine will be initialized on first request")
    set_model_ready("combined", False)

    # Create job directory if using filesystem backend
    if settings.JOB_BACKEND == "filesystem":
        job_dir = settings.JOB_DIR
        if not os.path.exists(job_dir):
            os.makedirs(job_dir, exist_ok=True)
            logger.info(f"Created job directory: {job_dir}")

    yield

    # Cleanup on shutdown
    logger.info("Application shutting down")
    app.state.ocr_ready = False


# Create FastAPI application
app = FastAPI(
    title="PaddleOCR REST API",
    description=(
        "A REST API for text recognition using PaddleOCR. "
        "Supports single image OCR, batch processing, and async jobs."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8080"],  # Adjust for your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """Handle ValueError exceptions."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "validation_error",
            "detail": str(exc),
            "request_id": request.headers.get("X-Request-ID"),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.exception(f"Unexpected error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "detail": "An unexpected error occurred",
            "request_id": request.headers.get("X-Request-ID"),
        },
    )


# Include routers
app.include_router(ocr.router)
app.include_router(jobs.router)
app.include_router(health.router)


# Root endpoint
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint redirect to docs."""
    return {
        "service": "PaddleOCR REST API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }


# Metrics endpoint
from fastapi import Response
from app.utils.metrics import metrics_endpoint

@app.get("/metrics", include_in_schema=True)
async def metrics():
    """Prometheus metrics endpoint."""
    return metrics_endpoint()


def create_app() -> FastAPI:
    """
    Factory function to create FastAPI application.

    Returns:
        Configured FastAPI application instance
    """
    return app


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        log_level=settings.LOG_LEVEL.lower(),
        reload=False,
    )
