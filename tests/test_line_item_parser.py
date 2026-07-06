"""Tests for line item parsing from reconstructed table rows."""

import pytest

from app.schemas.invoice import InvoiceLineItem
from app.services.table_reconstructor import (
    parse_line_items,
    _parse_quantity,
    _parse_tax_rate,
    _rate_to_float,
)


def _make_cell(text: str, confidence: float = 0.95) -> dict:
    return {"text": text, "confidence": confidence, "column_name": "test"}


def _make_row(cells: dict, is_discount: bool = False, text: str = "") -> dict:
    return {"cells": cells, "is_discount": is_discount, "text": text, "line_nos": []}


class TestParseQuantity:
    def test_integer_string(self):
        assert _parse_quantity("2") == 2.0

    def test_decimal_string(self):
        assert _parse_quantity("2.5") == 2.5

    def test_comma_separated(self):
        assert _parse_quantity("1,000") == 1000.0

    def test_none_input(self):
        assert _parse_quantity(None) is None

    def test_empty_string(self):
        assert _parse_quantity("") is None

    def test_non_numeric(self):
        assert _parse_quantity("abc") is None


class TestParseTaxRate:
    def test_percentage_only(self):
        assert _parse_tax_rate("10%") == "10%"

    def test_percentage_with_suffix(self):
        assert _parse_tax_rate("10%対象") == "10%"

    def test_eight_percent(self):
        assert _parse_tax_rate("8%") == "8%"

    def test_non_taxable(self):
        assert _parse_tax_rate("非課税") == "non_taxable"

    def test_exempt(self):
        assert _parse_tax_rate("免税") == "exempt"

    def test_none_input(self):
        assert _parse_tax_rate(None) is None

    def test_unknown_string(self):
        assert _parse_tax_rate("something") == "unknown"


class TestRateToFloat:
    def test_eight_percent(self):
        assert _rate_to_float("8%") == 0.08

    def test_ten_percent(self):
        assert _rate_to_float("10%") == 0.10

    def test_none(self):
        assert _rate_to_float(None) is None

    def test_unknown(self):
        assert _rate_to_float("unknown") is None


class TestParseLineItems:
    def test_simple_two_rows(self):
        """Parse a reconstructed table with two data rows."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("VCTケーブル"),
                    "quantity": _make_cell("2"),
                    "unit_price": _make_cell("45000"),
                    "amount": _make_cell("90000"),
                }),
                _make_row({
                    "description": _make_cell("現場消耗品"),
                    "quantity": _make_cell("1"),
                    "unit_price": _make_cell("15000"),
                    "amount": _make_cell("15000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 2

        # First item
        assert items[0].line_no == 1
        assert items[0].description == "VCTケーブル"
        assert items[0].quantity == 2.0
        assert items[0].unit_price == 45000
        assert items[0].amount_excluding_tax == 90000
        assert items[0].confidence == 0.95
        assert items[0].needs_review is False

        # Second item
        assert items[1].line_no == 2
        assert items[1].description == "現場消耗品"
        assert items[1].quantity == 1.0
        assert items[1].unit_price == 15000
        assert items[1].amount_excluding_tax == 15000

    def test_multiline_description(self):
        """Multiline description merged in cells should be preserved."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Long product name here"),
                    "quantity": _make_cell("5"),
                    "amount": _make_cell("25000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].description == "Long product name here"
        assert items[0].quantity == 5.0
        assert items[0].amount_excluding_tax == 25000

    def test_discount_row(self):
        """Rows with is_discount flag should have negative amount as discount."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("値引"),
                    "amount": _make_cell("-5000"),
                }, is_discount=True, text="値引 -5000"),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].description == "値引"
        assert items[0].discount == 5000
        # amount_excluding_tax should be None for discount rows
        assert items[0].amount_excluding_tax is None

    def test_missing_columns_null_fields(self):
        """Rows with missing optional columns should have null fields, not errors."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Item only"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].description == "Item only"
        assert items[0].quantity is None
        assert items[0].unit_price is None
        assert items[0].amount_excluding_tax is None
        assert items[0].confidence == 0.95
        assert items[0].needs_review is True  # missing required fields

    def test_low_ocr_confidence(self):
        """Low cell confidence should set needs_review=True."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Low conf item", confidence=0.40),
                    "amount": _make_cell("1000", confidence=0.35),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].confidence < 0.50
        assert items[0].needs_review is True

    def test_tax_rate_parsed_from_cell(self):
        """Tax rate cells like '10%対象' should parse to '10%'."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Item A"),
                    "quantity": _make_cell("1"),
                    "unit_price": _make_cell("1000"),
                    "tax_rate": _make_cell("10%対象"),
                    "amount": _make_cell("1000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].tax_rate == "10%"
        assert items[0].tax_amount == 100  # 1000 * 0.10
        assert items[0].amount_including_tax == 1100  # 1000 + 100

    def test_tax_amount_computed_from_rate(self):
        """tax_amount and amount_including_tax should be computed from amount and rate."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Item B"),
                    "quantity": _make_cell("3"),
                    "unit_price": _make_cell("2000"),
                    "tax_rate": _make_cell("8%"),
                    "amount": _make_cell("6000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].tax_rate == "8%"
        assert items[0].tax_amount == 480  # 6000 * 0.08
        assert items[0].amount_including_tax == 6480  # 6000 + 480

    def test_no_tax_rate_no_derived_amounts(self):
        """Without tax_rate, derived amounts should be None."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Item C"),
                    "amount": _make_cell("5000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].tax_amount is None
        assert items[0].amount_including_tax is None

    def test_empty_table_result(self):
        """Empty table should return empty list."""
        assert parse_line_items({"rows": []}) == []

    def test_missing_rows_key(self):
        """Missing rows key should return empty list."""
        assert parse_line_items({}) == []

    def test_unit_column_parsed(self):
        """Unit column text should be captured."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("Item D"),
                    "quantity": _make_cell("10"),
                    "unit": _make_cell("m"),
                    "unit_price": _make_cell("500"),
                    "amount": _make_cell("5000"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert len(items) == 1
        assert items[0].unit == "m"
        assert items[0].quantity == 10.0
        assert items[0].unit_price == 500

    def test_source_cells_preserved(self):
        """Source cells should be preserved in the line item."""
        cells = {
            "description": _make_cell("Item E"),
            "amount": _make_cell("3000"),
        }
        table_result = {
            "rows": [_make_row(cells)],
        }
        items = parse_line_items(table_result)
        assert items[0].source_cells == cells

    def test_needs_review_when_no_amount(self):
        """Missing both amount and unit_price should set needs_review."""
        table_result = {
            "rows": [
                _make_row({
                    "description": _make_cell("No numbers"),
                }),
            ]
        }
        items = parse_line_items(table_result)
        assert items[0].needs_review is True
