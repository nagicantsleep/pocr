"""Schema registry that loads YAML definitions and converts to JSON Schema / Pydantic models."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, create_model

from app.schemas.registry.schema_model import (
    FieldDefinition,
    FieldValidator,
    SchemaDefinition,
    TableDefinition,
)

# Mapping from YAML field types to JSON Schema types
_TYPE_MAP: dict[str, str | dict[str, Any]] = {
    "string": "string",
    "number": "number",
    "date": "string",
    "money": "number",
    "object": "object",
    "array": "array",
}

# Pattern for enum type: enum[val1, val2, ...]
_ENUM_RE = re.compile(r"^enum\[(.+)]$")


class SchemaRegistry:
    """Loads schema YAML files and provides lookup, JSON Schema conversion, and dynamic Pydantic model generation."""

    def __init__(self, schemas_dir: str | Path) -> None:
        self._schemas_dir = Path(schemas_dir)
        self._schemas: dict[tuple[str, str], SchemaDefinition] = {}

    # -- loading ---------------------------------------------------------------

    def load(self) -> None:
        """Walk schemas_dir for YAML files and register each one."""
        for yaml_path in self._schemas_dir.rglob("*.yaml"):
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            schema = SchemaDefinition(**raw)
            self._schemas[(schema.id, schema.version)] = schema

    # -- lookup ----------------------------------------------------------------

    def get(self, schema_id: str, version: str) -> Optional[SchemaDefinition]:
        return self._schemas.get((schema_id, version))

    def list_schemas(self) -> list[SchemaDefinition]:
        return list(self._schemas.values())

    # -- JSON Schema conversion ------------------------------------------------

    @staticmethod
    def to_json_schema(schema: SchemaDefinition) -> dict[str, Any]:
        """Convert a SchemaDefinition to a JSON Schema dict."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for field in schema.fields:
            prop = _field_to_json_schema(field)
            properties[field.name] = prop
            if field.required:
                required.append(field.name)

        result: dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": schema.id,
            "properties": properties,
        }
        if required:
            result["required"] = required
        if schema.review_threshold is not None:
            result["x-review-threshold"] = schema.review_threshold
        if schema.prompt_template:
            result["x-prompt-template"] = schema.prompt_template
        return result

    # -- Pydantic model generation ---------------------------------------------

    @staticmethod
    def generate_pydantic_model(schema: SchemaDefinition) -> type[BaseModel]:
        """Dynamically create a Pydantic model from a SchemaDefinition."""
        field_definitions: dict[str, Any] = {}

        for f in schema.fields:
            py_type, default = _field_to_python_type(f)
            field_definitions[f.name] = (py_type, default)

        model = create_model(
            _schema_model_name(schema.id, schema.version),
            **field_definitions,
        )
        return model


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _schema_model_name(schema_id: str, version: str) -> str:
    safe_id = schema_id.replace("-", "_").replace(".", "_")
    safe_ver = version.replace(".", "_")
    return f"Dynamic_{safe_id}_v{safe_ver}"


def _field_to_json_schema(field: FieldDefinition) -> dict[str, Any]:
    """Convert a single FieldDefinition to a JSON Schema property dict."""
    raw_type = field.type

    # enum[val1, val2]
    enum_match = _ENUM_RE.match(raw_type)
    if enum_match:
        values = [v.strip() for v in enum_match.group(1).split(",")]
        return {"type": "string", "enum": values}

    # object with properties
    if raw_type == "object" and field.properties:
        sub_props = {}
        for sub_name, sub_type in field.properties.items():
            sub_props[sub_name] = _type_token_to_json_schema(sub_type)
        return {"type": "object", "properties": sub_props}

    # array with item
    if raw_type == "array" and field.item:
        item_props = {}
        for item_key, item_type in field.item.items():
            item_props[item_key] = _type_token_to_json_schema(item_type)
        return {
            "type": "array",
            "items": {"type": "object", "properties": item_props},
        }

    # simple types
    js_type = _TYPE_MAP.get(raw_type, "string")
    result: dict[str, Any] = {"type": js_type}
    if field.pattern and raw_type == "string":
        result["pattern"] = field.pattern
    return result


def _type_token_to_json_schema(token: str | dict) -> dict[str, Any]:
    """Convert a bare type token (e.g. 'string', 'money', 'enum[...]') to JSON Schema."""
    if isinstance(token, dict):
        # nested object like { subtotal: money, tax: money }
        props = {}
        for k, v in token.items():
            props[k] = _type_token_to_json_schema(v)
        return {"type": "object", "properties": props}

    s = str(token)
    enum_match = _ENUM_RE.match(s)
    if enum_match:
        values = [v.strip() for v in enum_match.group(1).split(",")]
        return {"type": "string", "enum": values}

    js_type = _TYPE_MAP.get(s, "string")
    return {"type": js_type}


def _field_to_python_type(field: FieldDefinition) -> tuple[type, Any]:
    """Return (python_type, default_value) for dynamic Pydantic model creation."""
    raw_type = field.type
    required = field.required

    enum_match = _ENUM_RE.match(raw_type)
    if enum_match:
        py_type = str
        return (py_type, ... if required else None)

    if raw_type == "object":
        py_type = dict
        return (py_type, ... if required else None)

    if raw_type == "array":
        py_type = list
        return (py_type, ... if required else [])

    if raw_type == "number" or raw_type == "money":
        py_type = float
        return (py_type, ... if required else None)

    if raw_type == "date":
        py_type = str
        return (py_type, ... if required else None)

    # string and anything else
    py_type = str
    return (py_type, ... if required else None)
