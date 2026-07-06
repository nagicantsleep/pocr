"""Tests for table reconstructor."""

import json
import os

import pytest

from app.services.table_reconstructor import (
    detect_table_regions,
    group_rows_by_y,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "ocr_outputs")


def _load_fixture(name: str) -> list[dict]:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


# --- Table region detection ---


class TestDetectTableRegions:
    def test_simple_invoice_has_table_region(self):
        """Simple invoice with header keywords should detect a table region."""
        lines = _load_fixture("simple_invoice.json")
        regions = detect_table_regions(lines)
        assert len(regions) >= 1
        assert "header_line_nos" in regions[0]
        assert "row_line_nos" in regions[0]
        assert len(regions[0]["row_line_nos"]) >= 1

    def test_no_table_invoice_no_regions(self):
        """Invoice without table headers should have no table regions."""
        lines = _load_fixture("no_table_invoice.json")
        regions = detect_table_regions(lines)
        assert len(regions) == 0

    def test_non_invoice_no_regions(self):
        """Non-invoice document should have no table regions."""
        lines = _load_fixture("non_invoice.json")
        regions = detect_table_regions(lines)
        assert len(regions) == 0

    def test_empty_input(self):
        """Empty input should return empty list."""
        assert detect_table_regions([]) == []

    def test_single_header_no_rows(self):
        """Header line with no subsequent numeric rows should return empty."""
        lines = [
            {"text": "品名 数量 単価 金額", "confidence": 0.95,
             "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]}, "line_no": 1},
        ]
        regions = detect_table_regions(lines)
        assert len(regions) == 0

    def test_header_with_data_rows(self):
        """Header line followed by numeric rows should form a region."""
        lines = [
            {"text": "品名 数量 単価 金額", "confidence": 0.95,
             "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]}, "line_no": 1},
            {"text": "Widget 10 500 5000", "confidence": 0.93,
             "bbox": {"top_left": [50, 130], "bottom_right": [450, 150]}, "line_no": 2},
            {"text": "Gadget 5 1000 5000", "confidence": 0.93,
             "bbox": {"top_left": [50, 160], "bottom_right": [450, 180]}, "line_no": 3},
        ]
        regions = detect_table_regions(lines)
        assert len(regions) == 1
        assert regions[0]["header_line_nos"] == [1]
        assert regions[0]["row_line_nos"] == [2, 3]

    def test_region_bbox_covers_all_lines(self):
        """Table region bbox should span from header top to last row bottom."""
        lines = [
            {"text": "品名 数量 金額", "confidence": 0.95,
             "bbox": {"top_left": [50, 100], "bottom_right": [450, 120]}, "line_no": 1},
            {"text": "Item 2 200", "confidence": 0.93,
             "bbox": {"top_left": [50, 130], "bottom_right": [450, 150]}, "line_no": 2},
        ]
        regions = detect_table_regions(lines)
        assert len(regions) == 1
        bbox = regions[0]["bbox"]
        assert bbox["top_left"][1] == 100  # header top
        assert bbox["bottom_right"][1] == 150  # row bottom


# --- Row grouping ---


class TestGroupRowsByY:
    def test_lines_sorted_top_to_bottom(self):
        """Rows should be ordered by y-coordinate."""
        lines = [
            {"text": "B", "confidence": 0.95, "bbox": {"top_left": [10, 50], "bottom_right": [50, 70]}},
            {"text": "A", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "C", "confidence": 0.95, "bbox": {"top_left": [10, 90], "bottom_right": [50, 110]}},
        ]
        rows = group_rows_by_y(lines)
        assert len(rows) == 3
        assert rows[0][0]["text"] == "A"
        assert rows[1][0]["text"] == "B"
        assert rows[2][0]["text"] == "C"

    def test_same_row_grouped(self):
        """Lines with similar y should be in the same row."""
        lines = [
            {"text": "L", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "R", "confidence": 0.95, "bbox": {"top_left": [200, 12], "bottom_right": [250, 32]}},
        ]
        rows = group_rows_by_y(lines, y_tolerance=5.0)
        assert len(rows) == 1
        assert len(rows[0]) == 2

    def test_different_rows_separated(self):
        """Lines far apart vertically should be in different rows."""
        lines = [
            {"text": "Top", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "Bottom", "confidence": 0.95, "bbox": {"top_left": [10, 200], "bottom_right": [50, 220]}},
        ]
        rows = group_rows_by_y(lines, y_tolerance=5.0)
        assert len(rows) == 2

    def test_empty_input(self):
        assert group_rows_by_y([]) == []

    def test_within_row_sorted_left_to_right(self):
        """Lines within a row should be sorted left-to-right."""
        lines = [
            {"text": "R", "confidence": 0.95, "bbox": {"top_left": [200, 10], "bottom_right": [250, 30]}},
            {"text": "L", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
        ]
        rows = group_rows_by_y(lines, y_tolerance=5.0)
        assert rows[0][0]["text"] == "L"
        assert rows[0][1]["text"] == "R"
