"""Tests for the schema registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.registry import SchemaDefinition, SchemaRegistry

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas" / "registry"


@pytest.fixture
def registry() -> SchemaRegistry:
    reg = SchemaRegistry(REGISTRY_DIR)
    reg.load()
    return reg


@pytest.fixture
def jp_schema(registry: SchemaRegistry) -> SchemaDefinition:
    schema = registry.get("invoice-jp", "1.0.0")
    assert schema is not None, "invoice-jp v1.0.0 must be loaded"
    return schema


# ---------------------------------------------------------------------------
# Loading and lookup
# ---------------------------------------------------------------------------


class TestSchemaLoading:
    def test_load_invoice_jp(self, jp_schema: SchemaDefinition):
        assert jp_schema.id == "invoice-jp"
        assert jp_schema.version == "1.0.0"
        assert jp_schema.document_type == "qualified_invoice"
        assert jp_schema.locale == "ja-JP"
        assert jp_schema.currency == "JPY"

    def test_fields_present(self, jp_schema: SchemaDefinition):
        names = [f.name for f in jp_schema.fields]
        assert "issuer_name" in names
        assert "issuer_registration_number" in names
        assert "transaction_date" in names
        assert "total_amount" in names
        assert "line_items" in names

    def test_required_fields(self, jp_schema: SchemaDefinition):
        required = {f.name for f in jp_schema.fields if f.required}
        assert "issuer_name" in required
        assert "issuer_registration_number" in required
        assert "transaction_date" in required
        assert "total_amount" in required
        assert "invoice_number" not in required

    def test_tables(self, jp_schema: SchemaDefinition):
        assert len(jp_schema.tables) == 1
        assert jp_schema.tables[0].id == "line_items"
        assert jp_schema.tables[0].source == "table_visual"
        assert jp_schema.tables[0].confidence == "avg_cell"

    def test_review_threshold(self, jp_schema: SchemaDefinition):
        assert jp_schema.review_threshold == 0.85

    def test_prompt_template(self, jp_schema: SchemaDefinition):
        assert jp_schema.prompt_template is not None
        assert "Extract Japanese invoice" in jp_schema.prompt_template


class TestRegistryLookup:
    def test_get_existing(self, registry: SchemaRegistry):
        schema = registry.get("invoice-jp", "1.0.0")
        assert schema is not None
        assert schema.id == "invoice-jp"

    def test_get_nonexistent(self, registry: SchemaRegistry):
        assert registry.get("no-such-schema", "0.0.0") is None

    def test_list_all(self, registry: SchemaRegistry):
        schemas = registry.list_schemas()
        assert len(schemas) >= 1
        ids = [s.id for s in schemas]
        assert "invoice-jp" in ids


# ---------------------------------------------------------------------------
# JSON Schema conversion
# ---------------------------------------------------------------------------


class TestJsonSchemaConversion:
    def test_roundtrip_structure(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        assert js["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert js["type"] == "object"
        assert js["title"] == "invoice-jp"
        assert "issuer_name" in js["properties"]
        assert "issuer_name" in js["required"]

    def test_field_types(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        props = js["properties"]
        assert props["issuer_name"]["type"] == "string"
        assert props["total_amount"]["type"] == "number"
        assert props["transaction_date"]["type"] == "string"
        assert props["line_items"]["type"] == "array"
        assert props["tax_breakdown"]["type"] == "object"

    def test_enum_field(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        # line_items is array with items containing tax_rate enum
        items = js["properties"]["line_items"]["items"]
        tax_rate = items["properties"]["tax_rate"]
        assert tax_rate["type"] == "string"
        assert "8pct" in tax_rate["enum"]
        assert "10pct" in tax_rate["enum"]

    def test_pattern_field(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        reg_no = js["properties"]["issuer_registration_number"]
        assert reg_no["pattern"] == "^T\\d{13}$"

    def test_object_field_properties(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        tax_bd = js["properties"]["tax_breakdown"]
        assert "rate_8pct" in tax_bd["properties"]
        assert "rate_10pct" in tax_bd["properties"]
        assert tax_bd["properties"]["rate_8pct"]["type"] == "object"

    def test_threshold_and_prompt_in_schema(self, jp_schema: SchemaDefinition):
        js = SchemaRegistry.to_json_schema(jp_schema)
        assert js["x-review-threshold"] == 0.85
        assert "Extract Japanese invoice" in js["x-prompt-template"]


# ---------------------------------------------------------------------------
# Dynamic Pydantic model generation
# ---------------------------------------------------------------------------


class TestDynamicPydanticModel:
    def test_model_creation(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        assert Model.__name__ == "Dynamic_invoice_jp_v1_0_0"

    def test_valid_data(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        instance = Model(
            issuer_name="Test Corp",
            issuer_registration_number="T1234567890123",
            transaction_date="2024-01-15",
            total_amount=11000.0,
        )
        assert instance.issuer_name == "Test Corp"
        assert instance.total_amount == 11000.0
        assert instance.invoice_number is None  # optional
        assert instance.line_items == []  # array default

    def test_optional_fields_omitted(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        instance = Model(
            issuer_name="Corp",
            issuer_registration_number="T1234567890123",
            transaction_date="2024-01-15",
            total_amount=100.0,
        )
        assert instance.invoice_number is None

    def test_missing_required_field(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        with pytest.raises(ValidationError):
            Model(
                issuer_name="Corp",
                # missing issuer_registration_number, transaction_date, total_amount
            )

    def test_model_with_object_field(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        instance = Model(
            issuer_name="Corp",
            issuer_registration_number="T1234567890123",
            transaction_date="2024-01-15",
            total_amount=11000.0,
            tax_breakdown={"rate_8pct": {"subtotal": 1000, "tax": 80}},
        )
        assert instance.tax_breakdown["rate_8pct"]["subtotal"] == 1000

    def test_model_with_array_field(self, jp_schema: SchemaDefinition):
        Model = SchemaRegistry.generate_pydantic_model(jp_schema)
        instance = Model(
            issuer_name="Corp",
            issuer_registration_number="T1234567890123",
            transaction_date="2024-01-15",
            total_amount=11000.0,
            line_items=[
                {"description": "Widget", "quantity": 10, "unit_price": 100.0}
            ],
        )
        assert len(instance.line_items) == 1
        assert instance.line_items[0]["description"] == "Widget"
