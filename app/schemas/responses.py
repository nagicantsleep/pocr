"""Pydantic response schemas for OCR API."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BBox(BaseModel):
    """Bounding box coordinates."""

    top_left: list[float] = Field(
        ...,
        description="Top-left corner coordinates [x, y]",
        min_length=2,
        max_length=2,
    )
    bottom_right: list[float] = Field(
        ...,
        description="Bottom-right corner coordinates [x, y]",
        min_length=2,
        max_length=2,
    )


class OCRResult(BaseModel):
    """Single OCR detection result."""

    text: str = Field(..., description="Recognized text content")
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the recognized text",
    )
    bbox: BBox = Field(..., description="Axis-aligned bounding box")
    bbox_normalized: BBox = Field(
        ...,
        description="Normalized bounding box (0-1 range)",
    )
    type: str = Field(
        default="text",
        description="Type of detected content (text, table, title, etc.)",
    )
    polygon: list[list[float]] = Field(
        default_factory=list,
        description="Polygon points for the detected region",
    )


class OCRMeta(BaseModel):
    """Metadata about the OCR processing."""

    engine: str = Field(default="paddleocr", description="OCR engine name")
    engine_version: str = Field(
        default="3.5.0",
        description="OCR engine version",
    )
    model: str = Field(..., description="Model name used for inference")
    lang: str = Field(..., description="Language code used")
    inference_time_ms: int = Field(
        ...,
        ge=0,
        description="Inference time in milliseconds",
    )
    image_width: Optional[int] = Field(
        default=None,
        ge=0,
        description="Original image width",
    )
    image_height: Optional[int] = Field(
        default=None,
        ge=0,
        description="Original image height",
    )
    was_resized: bool = Field(
        default=False,
        description="Whether image was resized before processing",
    )


class OCRSummary(BaseModel):
    """Summary statistics for OCR results."""

    total_lines: int = Field(
        default=0,
        ge=0,
        description="Total number of text lines detected",
    )
    total_characters: int = Field(
        default=0,
        ge=0,
        description="Total number of characters recognized",
    )
    avg_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Average confidence score across all results",
    )


class OCRResponse(BaseModel):
    """Response schema for single OCR operation."""

    request_id: str = Field(..., description="Unique request identifier")
    status: str = Field(
        default="success",
        description="Processing status (success, error)",
    )
    meta: OCRMeta = Field(..., description="Processing metadata")
    results: list[OCRResult] = Field(
        default_factory=list,
        description="List of detected text regions",
    )
    summary: OCRSummary = Field(
        default_factory=OCRSummary,
        description="Summary statistics",
    )


class ImageOCRResult(BaseModel):
    """Result for a single image in batch processing."""

    filename: str = Field(
        default="image",
        description="Image filename or identifier",
    )
    status: str = Field(
        default="success",
        description="Processing status (success, error)",
    )
    data: Optional[dict[str, Any]] = Field(
        default=None,
        description="OCR results data",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if processing failed",
    )


class BatchOCRResponse(BaseModel):
    """Response schema for batch OCR operation."""

    request_id: str = Field(..., description="Unique request identifier")
    status: str = Field(
        default="success",
        description="Overall processing status",
    )
    results: list[ImageOCRResult] = Field(
        default_factory=list,
        description="Results for each processed image",
    )


class JobProgress(BaseModel):
    """Progress information for async job."""

    processed: int = Field(
        default=0,
        ge=0,
        description="Number of images processed",
    )
    total: int = Field(
        default=0,
        ge=0,
        description="Total number of images in job",
    )


class JobCreateResponse(BaseModel):
    """Response schema for async job creation."""

    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(
        default="queued",
        description="Initial job status",
    )
    created_at: str = Field(..., description="ISO timestamp of job creation")
    status_url: str = Field(..., description="URL to check job status")
    estimated_completion: Optional[str] = Field(
        default=None,
        description="Estimated completion time",
    )


class JobResponse(BaseModel):
    """Response schema for job status/results."""

    job_id: str = Field(..., description="Unique job identifier")
    status: str = Field(
        ...,
        description="Current job status",
    )
    created_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of job creation",
    )
    started_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when processing started",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp when processing completed",
    )
    progress: Optional[JobProgress] = Field(
        default=None,
        description="Processing progress information",
    )
    results: Optional[list[ImageOCRResult]] = Field(
        default=None,
        description="Final results if completed",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if failed",
    )


class ErrorResponse(BaseModel):
    """Standard error response schema."""

    error: str = Field(..., description="Error code identifier")
    detail: str = Field(..., description="Human-readable error message")
    request_id: Optional[str] = Field(
        default=None,
        description="Request ID for error tracking",
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    engine: str = Field(default="paddleocr", description="OCR engine name")
    gpu_available: bool = Field(
        default=False,
        description="Whether GPU is available",
    )
    version: str = Field(default="3.5.0", description="Engine version")
