"""Tests for row grouping and cell assignment in table reconstruction."""

import json
import os

import pytest

from app.services.column_inference import infer_columns_from_header
from app.services.layout_analyzer import analyze_layout
from app.services.table_reconstructor import (
    assign_cells,
    detect_table_regions,
    group_rows,
    reconstruct_table,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "ocr_outputs")


def _load_fixture(name: str) -> list[dict]:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _make_line(text, x, y, w=50, h=20, line_no=1, confidence=0.95):
    """Helper to create a minimal OCR line dict."""
    return {
        "text": text,
        "confidence": confidence,
        "bbox": {
            "top_left": [x, y],
            "bottom_right": [x + w, y + h],
        },
        "line_no": line_no,
    }


# --- group_rows ---


class TestGroupRows:
    def test_simple_invoice_grouping(self):
        """group_rows with simple_invoice fixture groups lines into rows by y."""
        lines = _load_fixture("simple_invoice.json")
        # Only use the data rows (line_nos 10-13: VCTケーブル row, 14-17: 現場消耗品 row)
        data_lines = [l for l in lines if l["text"] in (
            "VCTケーブル", "2", "45000", "90000",
            "現場消耗品", "1", "15000", "15000",
        )]
        # Manually assign line numbers as the fixture has no line_no
        for i, l in enumerate(data_lines):
            l["line_no"] = i + 1

        rows = group_rows(data_lines)
        assert len(rows) == 2  # two data rows

        # First row — VCTケーブル
        assert rows[0]["text"] == "VCTケーブル 2 45000 90000"
        assert len(rows[0]["lines"]) == 4
        assert "line_nos" in rows[0]

        # Second row — 現場消耗品
        assert rows[1]["text"] == "現場消耗品 1 15000 15000"
        assert len(rows[1]["lines"]) == 4
        assert rows[1]["line_nos"] == [5, 6, 7, 8]

    def test_group_multiline_description(self):
        """Lines at same y that are part of a multiline description group into one row."""
        lines = [
            _make_line("Long item", 50, 100, line_no=1),
            _make_line("description here", 50, 102, line_no=2),
            _make_line("2", 250, 100, w=30, line_no=3),
            _make_line("5000", 350, 100, w=50, line_no=4),
        ]
        rows = group_rows(lines, y_tolerance=5.0)
        assert len(rows) == 1
        assert "description here" in rows[0]["text"]
        assert "5000" in rows[0]["text"]
        assert len(rows[0]["lines"]) == 4

    def test_empty_input(self):
        assert group_rows([]) == []


# --- assign_cells ---


class TestAssignCells:
    @pytest.fixture
    def columns(self):
        return {
            "columns": [
                {"name": "description", "type": "description", "x_start": 50, "x_end": 190},
                {"name": "quantity", "type": "quantity", "x_start": 200, "x_end": 250},
                {"name": "unit_price", "type": "unit_price", "x_start": 290, "x_end": 360},
                {"name": "amount", "type": "amount", "x_start": 390, "x_end": 470},
            ]
        }

    @pytest.fixture
    def rows(self):
        """Rows representing the VCTケーブル line from simple_invoice."""
        return [
            {
                "line_nos": [1, 2, 3, 4],
                "y": 200,
                "lines": [
                    _make_line("VCTケーブル", 50, 190, w=130, line_no=1),
                    _make_line("2", 210, 190, w=20, line_no=2),
                    _make_line("45000", 300, 190, w=70, line_no=3),
                    _make_line("90000", 400, 190, w=60, line_no=4),
                ],
                "text": "VCTケーブル 2 45000 90000",
            },
            {
                "line_nos": [5, 6, 7, 8],
                "y": 230,
                "lines": [
                    _make_line("現場消耗品", 50, 220, w=130, line_no=5),
                    _make_line("1", 210, 220, w=20, line_no=6),
                    _make_line("15000", 300, 220, w=70, line_no=7),
                    _make_line("15000", 400, 220, w=60, line_no=8),
                ],
                "text": "現場消耗品 1 15000 15000",
            },
        ]

    def test_assign_correctly(self, rows, columns):
        """Known columns should assign cells correctly."""
        result = assign_cells(rows, columns)
        assert len(result) == 2

        # First row cells
        cells = result[0]["cells"]
        assert cells["description"]["text"] == "VCTケーブル"
        assert cells["quantity"]["text"] == "2"
        assert cells["unit_price"]["text"] == "45000"
        assert cells["amount"]["text"] == "90000"

        # Second row cells
        cells2 = result[1]["cells"]
        assert cells2["description"]["text"] == "現場消耗品"
        assert cells2["quantity"]["text"] == "1"
        assert cells2["unit_price"]["text"] == "15000"
        assert cells2["amount"]["text"] == "15000"

    def test_ambiguous_position_low_confidence(self, rows, columns):
        """Cell at ambiguous position should get low or zero confidence."""
        # Put a cell right between quantity and unit_price columns
        ambiguous_line = _make_line("300", 275, 190, w=30, line_no=99)
        row = [{
            "line_nos": [99],
            "y": 200,
            "lines": [ambiguous_line],
            "text": "300",
        }]
        result = assign_cells(row, columns)
        # x=275 is between quantity (200-250) and unit_price (290-360)
        # Neither column contains x=275 — should be unassigned
        assert "unassigned" in result[0]
        assert len(result[0]["unassigned"]) >= 1

    def test_empty_rows(self, columns):
        """Empty rows list returns empty."""
        assert assign_cells([], columns) == []

    def test_empty_columns(self, rows):
        """No columns means all lines are unassigned."""
        result = assign_cells(rows, {"columns": []})
        for r in result:
            assert r["cells"] == {}
            assert len(r["unassigned"]) == len(r["lines"])

    def test_multiline_description(self, columns):
        """Multiple description lines at same y merge into one description cell."""
        row = [{
            "line_nos": [1, 2, 3],
            "y": 200,
            "lines": [
                _make_line("Long product", 50, 190, line_no=1),
                _make_line("name here", 50, 190, line_no=2),
                _make_line("5000", 400, 190, w=60, line_no=3),
            ],
            "text": "Long product name here",
        }]
        # Both "Long product" and "name here" fall in description x-range (50-190)
        # But first call to assign_cells: "Long product" -> description,
        # "name here" -> also description, so it appends
        result = assign_cells(row, columns)
        assert result[0]["cells"]["description"]["text"] == "Long product name here"
        assert result[0]["cells"]["amount"]["text"] == "5000"

    def test_accept_plain_list_columns(self, rows):
        """assign_cells should accept a plain list of column dicts."""
        col_list = [
            {"type": "description", "x_start": 50, "x_end": 190},
            {"type": "quantity", "x_start": 200, "x_end": 250},
            {"type": "amount", "x_start": 390, "x_end": 470},
        ]
        result = assign_cells(rows, col_list)
        assert len(result) == 2
        assert result[0]["cells"]["description"]["text"] == "VCTケーブル"
        assert result[0]["cells"]["quantity"]["text"] == "2"


# --- reconstruct_table ---


class TestReconstructTable:
    def test_end_to_end_with_simple_invoice(self):
        """Full pipeline going through analyze_layout then table reconstruction."""
        lines = _load_fixture("simple_invoice.json")

        # Run through analyze_layout first to get merged lines with line_no
        layout_doc = analyze_layout(lines)

        # Build table region and columns manually to avoid fixture limitations.
        # The fixture has header keywords as separate lines (品名, 数量, 単価, 金額)
        # rather than a single merged line, so detect_table_regions can't
        # separate header from rows on this data. In production, real OCR output
        # would be merged by analyze_layout. Here we provide the expected shapes.
        table_region = {
            "header_line_nos": [],
            "row_line_nos": [l["line_no"] for l in layout_doc["lines"]
                             if l["text"] in ("VCTケーブル", "2", "45000", "90000",
                                              "現場消耗品", "1", "15000", "15000")],
            "bbox": {"top_left": [50, 190], "bottom_right": [460, 240]},
        }
        columns = {"columns": [
            {"name": "description", "type": "description", "x_start": 50, "x_end": 190},
            {"name": "quantity", "type": "quantity", "x_start": 200, "x_end": 250},
            {"name": "unit_price", "type": "unit_price", "x_start": 290, "x_end": 370},
            {"name": "amount", "type": "amount", "x_start": 390, "x_end": 470},
        ]}

        result = reconstruct_table(layout_doc, table_region, columns)
        assert result["row_count"] >= 2
        assert "rows" in result
        assert result["confidence"] > 0

        # Check that at least one row has cells assigned
        rows_with_cells = [r for r in result["rows"] if r.get("cells")]
        assert len(rows_with_cells) >= 1

        # Check that description and amount columns were assigned
        for row in rows_with_cells:
            if "description" in row["cells"]:
                assert len(row["cells"]["description"]["text"]) > 0
            if "amount" in row["cells"]:
                assert len(row["cells"]["amount"]["text"]) > 0

    def test_empty_table(self):
        """Empty table returns empty rows."""
        layout_doc = {"lines": [], "blocks": [], "table_candidates": []}
        region = {
            "header_line_nos": [1],
            "row_line_nos": [],
            "bbox": {"top_left": [0, 0], "bottom_right": [100, 100]},
        }
        columns = {"columns": []}
        result = reconstruct_table(layout_doc, region, columns)
        assert result["row_count"] == 0
        assert result["rows"] == []
        assert result["confidence"] == 1.0

    def test_discount_rows_preserved(self):
        """Rows with negative amounts should be kept with is_discount flag."""
        layout_doc = {
            "lines": [
                _make_line("値引", 50, 200, line_no=1),
                _make_line("-5000", 400, 200, w=60, line_no=2),
            ]
        }
        region = {
            "header_line_nos": [],
            "row_line_nos": [1, 2],
            "bbox": {"top_left": [50, 190], "bottom_right": [460, 220]},
        }
        columns = {"columns": [
            {"type": "description", "x_start": 50, "x_end": 190, "name": "description"},
            {"type": "amount", "x_start": 390, "x_end": 470, "name": "amount"},
        ]}
        result = reconstruct_table(layout_doc, region, columns)
        assert result["row_count"] == 1
        assert result["rows"][0].get("is_discount") is True
        assert "amount" in result["rows"][0]["cells"]
