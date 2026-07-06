"""Tests for column inference."""

import pytest

from app.services.column_inference import (
    assign_cell_to_column,
    infer_columns_from_header,
    infer_columns_from_positions,
)


class TestInferColumnsFromHeader:
    def test_standard_invoice_header(self):
        """Standard invoice header with 品名, 数量, 単価, 金額."""
        header = {
            "text": "品名 数量 単価 金額",
            "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]},
        }
        columns = infer_columns_from_header(header)
        col_types = [c["type"] for c in columns]
        assert "description" in col_types
        assert "quantity" in col_types
        assert "unit_price" in col_types
        assert "amount" in col_types

    def test_partial_header(self):
        """Header with only some keywords."""
        header = {
            "text": "品名 金額",
            "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]},
        }
        columns = infer_columns_from_header(header)
        col_types = [c["type"] for c in columns]
        assert "description" in col_types
        assert "amount" in col_types
        assert "quantity" not in col_types

    def test_no_keywords(self):
        """Header without any known keywords returns empty."""
        header = {
            "text": "Item Details",
            "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]},
        }
        columns = infer_columns_from_header(header)
        assert len(columns) == 0

    def test_columns_sorted_by_x(self):
        """Returned columns should be sorted by x_start."""
        header = {
            "text": "金額 品名 数量",
            "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]},
        }
        columns = infer_columns_from_header(header)
        x_starts = [c["x_start"] for c in columns]
        assert x_starts == sorted(x_starts)

    def test_duplicate_type_not_repeated(self):
        """Same column type should not appear twice."""
        header = {
            "text": "品名 商品名 金額 合計",
            "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]},
        }
        columns = infer_columns_from_header(header)
        col_types = [c["type"] for c in columns]
        # description may appear once (品名 maps to description, 商品名 also)
        assert col_types.count("description") <= 1
        # amount may appear once (金額 maps to amount, 合計 also)
        assert col_types.count("amount") <= 1


class TestInferColumnsFromPositions:
    def test_with_header_columns(self):
        """When header columns provided, refine using data positions."""
        header_columns = [
            {"type": "description", "x_start": 50, "x_end": 200},
            {"type": "quantity", "x_start": 250, "x_end": 300},
            {"type": "amount", "x_start": 400, "x_end": 460},
        ]
        row_lines = [
            {"text": "Widget", "bbox": {"top_left": [55, 130], "bottom_right": [180, 150]}},
            {"text": "10", "bbox": {"top_left": [260, 130], "bottom_right": [290, 150]}},
            {"text": "5000", "bbox": {"top_left": [410, 130], "bottom_right": [455, 150]}},
        ]
        columns = infer_columns_from_positions(row_lines, header_columns)
        assert len(columns) == 3
        assert columns[0]["type"] == "description"
        assert columns[0]["cell_count"] == 1

    def test_without_header_cluster(self):
        """Without header, cluster x-positions to infer columns."""
        row_lines = [
            {"text": "Widget", "bbox": {"top_left": [50, 130], "bottom_right": [180, 150]}},
            {"text": "10", "bbox": {"top_left": [260, 130], "bottom_right": [290, 150]}},
            {"text": "5000", "bbox": {"top_left": [410, 130], "bottom_right": [455, 150]}},
        ]
        columns = infer_columns_from_positions(row_lines)
        assert len(columns) >= 2
        # Leftmost should be description
        assert columns[0]["type"] == "description"

    def test_empty_rows(self):
        assert infer_columns_from_positions([]) == []

    def test_empty_rows_with_header(self):
        result = infer_columns_from_positions([], [{"type": "x", "x_start": 0, "x_end": 100}])
        assert len(result) == 1


class TestAssignCellToColumn:
    def test_exact_match(self):
        """Cell at column center should match that column."""
        columns = [
            {"type": "description", "x_start": 50, "x_end": 200},
            {"type": "amount", "x_start": 400, "x_end": 460},
        ]
        cell_bbox = {"top_left": [100, 130], "bottom_right": [180, 150]}
        assert assign_cell_to_column(cell_bbox, columns) == "description"

    def test_no_close_column(self):
        """Cell far from any column should return None."""
        columns = [
            {"type": "description", "x_start": 50, "x_end": 200},
        ]
        cell_bbox = {"top_left": [500, 130], "bottom_right": [580, 150]}
        assert assign_cell_to_column(cell_bbox, columns) is None

    def test_empty_columns(self):
        cell_bbox = {"top_left": [100, 130], "bottom_right": [180, 150]}
        assert assign_cell_to_column(cell_bbox, []) is None
