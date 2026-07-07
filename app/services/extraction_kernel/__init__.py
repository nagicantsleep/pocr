"""Extraction kernel: schema-driven extraction pipeline."""

from app.services.extraction_kernel.kernel import (
    ExtractionKernel,
    ExtractionResult,
    FieldResult,
)
from app.services.extraction_kernel.source_registry import (
    SourceRegistry,
    source_registry,
)

__all__ = [
    "ExtractionKernel",
    "ExtractionResult",
    "FieldResult",
    "SourceRegistry",
    "source_registry",
]
