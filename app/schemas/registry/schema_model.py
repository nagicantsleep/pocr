"""Pydantic models for YAML schema definitions."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FieldValidator(BaseModel):
    """A validation rule attached to a field."""

    code: str
    severity: str = "error"


class FieldDefinition(BaseModel):
    """Definition of a single field in a schema."""

    name: str
    type: str  # string, number, date, money, enum, array, object
    pattern: Optional[str] = None
    sources: list[str] = Field(default_factory=list)
    required: bool = False
    validators: list[FieldValidator] = Field(default_factory=list)
    cross_field: list[dict[str, Any]] = Field(default_factory=list)
    cross_field_tolerance: Optional[float] = None
    properties: Optional[dict[str, Any]] = None
    item: Optional[dict[str, Any]] = None


class TableDefinition(BaseModel):
    """Definition of a table extraction target."""

    id: str
    source: str
    confidence: Optional[str] = None


class SchemaDefinition(BaseModel):
    """Top-level schema definition loaded from YAML."""

    id: str
    version: str
    document_type: str
    locale: str = "en-US"
    currency: Optional[str] = None
    fields: list[FieldDefinition] = Field(default_factory=list)
    tables: list[TableDefinition] = Field(default_factory=list)
    review_threshold: Optional[float] = None
    prompt_template: Optional[str] = None
