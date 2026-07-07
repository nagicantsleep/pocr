"""Tests for receipt-jp schema loading and structure."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.registry import SchemaDefinition, SchemaRegistry

REGISTRY_DIR = Path(__file__).resolve().parent.parent / "app" / "schemas" / "registry"


@pytest.fixture
def registry() -> SchemaRegistry:
    reg = SchemaRegistry(REGISTRY_DIR)
    reg.load()
    return reg


@pytest.fixture
def receipt_schema(registry: SchemaRegistry) -> SchemaDefinition:
    schema = registry.get("receipt-jp", "1.0.0")
    assert schema is not None, "receipt-jp v1.0.0 must be loaded"
    return schema


class TestReceiptSchemaLoading:
    def test_receipt_schema_loads(self, receipt_schema: SchemaDefinition):
        assert receipt_schema.id == "receipt-jp"
        assert receipt_schema.version == "1.0.0"
        assert receipt_schema.document_type == "receipt"
        assert receipt_schema.locale == "ja-JP"
        assert receipt_schema.currency == "JPY"

    def test_review_threshold(self, receipt_schema: SchemaDefinition):
        assert receipt_schema.review_threshold == 0.80


class TestReceiptSchemaFields:
    def test_required_fields_present(self, receipt_schema: SchemaDefinition):
        names = [f.name for f in receipt_schema.fields]
        assert "store_name" in names
        assert "total_amount" in names
        assert "transaction_date" in names

    def test_optional_fields_present(self, receipt_schema: SchemaDefinition):
        names = [f.name for f in receipt_schema.fields]
        assert "store_address" in names
        assert "store_phone" in names
        assert "tax_amount" in names
        assert "subtotal" in names
        assert "payment_method" in names
        assert "change_amount" in names
        assert "line_items" in names

    def test_store_name_required(self, receipt_schema: SchemaDefinition):
        field = next(f for f in receipt_schema.fields if f.name == "store_name")
        assert field.required is True
        assert "layout_header" in field.sources
        assert "regex_vendor" in field.sources

    def test_total_amount_has_cross_field(self, receipt_schema: SchemaDefinition):
        field = next(f for f in receipt_schema.fields if f.name == "total_amount")
        assert field.required is True
        assert len(field.cross_field) == 1
        assert "subtotal + tax_amount" in field.cross_field[0].get("eq", "")

    def test_store_phone_pattern(self, receipt_schema: SchemaDefinition):
        field = next(f for f in receipt_schema.fields if f.name == "store_phone")
        assert field.required is False
        assert field.pattern is not None

    def test_line_items_array(self, receipt_schema: SchemaDefinition):
        field = next(f for f in receipt_schema.fields if f.name == "line_items")
        assert field.type == "array"
        assert field.item is not None
        assert "description" in field.item
        assert "quantity" in field.item
        assert "unit_price" in field.item
        assert "amount" in field.item
        assert "tax_rate" in field.item


class TestReceiptSchemaTables:
    def test_line_items_table(self, receipt_schema: SchemaDefinition):
        assert len(receipt_schema.tables) == 1
        table = receipt_schema.tables[0]
        assert table.id == "line_items"
        assert table.source == "table_visual"
        assert table.confidence == "avg_cell"


class TestReceiptSchemaListedInRegistry:
    def test_receipt_appears_in_list(self, registry: SchemaRegistry):
        all_schemas = registry.list_schemas()
        ids = [s.id for s in all_schemas]
        assert "receipt-jp" in ids

    def test_invoice_jp_also_loaded(self, registry: SchemaRegistry):
        schema = registry.get("invoice-jp", "1.0.0")
        assert schema is not None
