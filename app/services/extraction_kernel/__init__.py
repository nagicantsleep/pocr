"""Extraction kernel: schema-driven extraction pipeline."""

from app.services.extraction_kernel.kernel import (
    ExtractionKernel,
    ExtractionResult,
    FieldResult,
    register_validator_handler,
    unregister_validator_handler,
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
    "register_validator_handler",
    "source_registry",
    "unregister_validator_handler",
]
