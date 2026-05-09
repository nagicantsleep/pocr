"""Pydantic response schemas for OCR API."""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class StructuredTax(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str = Field(..., description="Tax label")
    tax_rate: float = Field(..., ge=0.0, description="Tax rate as decimal", alias="taxRate")
    taxable_amount: int = Field(..., ge=0, description="Amount before tax", alias="taxableAmount")
    tax_amount: int = Field(..., ge=0, description="Tax amount", alias="taxAmount")


class StructuredInputCostImage(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    image_url: str = Field(..., description="Original image URL or storage path", alias="imageUrl")
    presigned_image_url: Optional[str] = Field(
        default=None,
        description="Temporary signed URL for image access",
        alias="presignedImageUrl",
    )


class StructuredInputCostItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    transaction_date: Optional[date] = Field(
        default=None,
        description="Transaction date for the line item",
        alias="transactionDate",
    )
    item_code: Optional[str] = Field(default=None, description="Vendor item code", alias="itemCode")
    item_name: str = Field(..., description="Line item description", alias="itemName")
    unit: Optional[str] = Field(default=None, description="Unit name")
    quantity: Optional[float] = Field(default=None, ge=0, description="Quantity")
    price: Optional[int] = Field(default=None, ge=0, description="Unit price")
    tax_rate: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Tax rate as decimal",
        alias="taxRate",
    )
    description: Optional[str] = Field(default=None, description="Supplemental note")
    amount: Optional[int] = Field(default=None, ge=0, description="Line total")


class StructuredOCRData(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    title: Optional[str] = Field(default=None, description="Document title")
    original_number: Optional[str] = Field(
        default=None,
        description="Original document number",
        alias="originalNumber",
    )
    input_cost_type: Optional[str] = Field(
        default=None,
        description="Input cost document type label or enum description found in the image",
        alias="inputCostType",
    )
    issue_date: Optional[date] = Field(default=None, description="Issue date", alias="issueDate")
    payment_date: Optional[date] = Field(default=None, description="Payment date", alias="paymentDate")
    vendor_name: Optional[str] = Field(default=None, description="Vendor name", alias="vendorName")
    payment_method: Optional[str] = Field(
        default=None,
        description="Payment method label or enum description found in the image",
        alias="paymentMethod",
    )
    description: Optional[str] = Field(default=None, description="Document note")
    total_amount: Optional[int] = Field(default=None, ge=0, description="Grand total", alias="totalAmount")
    taxes: list[StructuredTax] = Field(default_factory=list, description="Tax breakdown")
    input_cost_items: list[StructuredInputCostItem] = Field(
        default_factory=list,
        description="Structured line items",
        alias="inputCostItems",
    )


class StructuredOCRResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_id: str = Field(..., description="Unique request identifier", alias="requestId")
    status: str = Field(default="success", description="Processing status")
    meta: OCRMeta = Field(..., description="Processing metadata")
    data: StructuredOCRData = Field(..., description="Structured document output")
    raw_results: list[OCRResult] = Field(
        default_factory=list,
        description="Underlying OCR detections used for extraction",
        alias="rawResults",
    )


class StructuredJobCreateResponse(BaseModel):
    """Response for queued structured OCR standardization jobs."""

    job_id: str = Field(..., description="Unique structured job identifier")
    status: str = Field(default="queued", description="Initial job status")
    status_url: str = Field(..., description="URL to poll for job status")

class StructuredJobResponse(BaseModel):
    """Status and result response for structured OCR standardization jobs."""

    job_id: str = Field(..., description="Unique structured job identifier")
    status: str = Field(..., description="queued, running, success, or failed")
    provider: str = Field(..., description="Standardizer provider")
    created_at: Optional[datetime] = Field(default=None, description="Job creation time")
    started_at: Optional[datetime] = Field(default=None, description="Processing start time")
    completed_at: Optional[datetime] = Field(default=None, description="Completion time")
    structured_json: Optional[StructuredOCRData] = Field(
        default=None,
        description="Validated structured result when status is success",
    )
    error: Optional[str] = Field(default=None, description="Failure reason when status is failed")

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
