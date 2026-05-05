"""Pydantic request schemas for OCR API."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OCRRequest(BaseModel):
    """Request schema for single OCR operation."""

    image: str = Field(
        ...,
        description="Base64-encoded image data or data URI",
        min_length=1,
    )
    lang: str = Field(
        default="auto",
        description="Language code for OCR (auto, en, ch, japan, korean, etc.)",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for results",
    )
    layout_analysis: bool = Field(
        default=False,
        description="Enable layout analysis for document structure detection",
    )
    include_polygon: bool = Field(
        default=True,
        description="Include polygon points in response",
    )

    @field_validator("image")
    @classmethod
    def validate_image_data(cls, v: str) -> str:
        """Validate that image data is valid base64 or data URI."""
        if not v or len(v.strip()) == 0:
            raise ValueError("image data cannot be empty")
        return v.strip()


class BatchOCRRequest(BaseModel):
    """Request schema for batch OCR operation."""

    images: list[str] = Field(
        ...,
        description="List of base64-encoded images",
        min_length=1,
    )
    lang: str = Field(
        default="auto",
        description="Language code for OCR",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for results",
    )

    @field_validator("images")
    @classmethod
    def validate_images_not_empty(cls, v: list[str]) -> list[str]:
        """Validate that images list is not empty."""
        if not v:
            raise ValueError("images list cannot be empty")
        return v


class JobCreateRequest(BaseModel):
    """Request schema for creating async OCR job."""

    images: list[str] = Field(
        ...,
        description="List of base64-encoded images for batch processing",
        min_length=1,
    )
    lang: str = Field(
        default="auto",
        description="Language code for OCR",
    )
    min_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for results",
    )
    layout_analysis: bool = Field(
        default=False,
        description="Enable layout analysis",
    )

    @field_validator("images")
    @classmethod
    def validate_images_not_empty(cls, v: list[str]) -> list[str]:
        """Validate that images list is not empty."""
        if not v:
            raise ValueError("images list cannot be empty")
        return v
