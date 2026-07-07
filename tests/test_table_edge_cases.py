"""Edge case tests for table extraction in the kernel pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest

from app.schemas.registry.schema_model import SchemaDefinition, TableDefinition
from app.services.extraction_kernel.kernel import (
    ExtractionKernel,
    ExtractionResult,
    _table_region_to_dicts,
)
from app.services.extraction_kernel.source_registry import source_registry


# -- helpers -------------------------------------------------------------------

def _make_ocr(text: str, confidence: float = 0.9, bbox=None) -> dict:
    if bbox is None:
        bbox = {"top_left": [10, 10], "bottom_right": [200, 30]}
    return {"text": text, "confidence": confidence, "bbox": bbox}


@dataclass
class _MockCell:
    text: str
    confidence: float
    column: int
    bbox: list

    @property
    def col(self):
        return f"col_{self.column}"


@dataclass
class _MockTableRegion:
    rows: list[list[_MockCell]]
    bbox: list = None


def _make_schema_with_visual_table() -> SchemaDefinition:
    return SchemaDefinition(
        id="test-edge",
        version="1.0.0",
        document_type="test",
        fields=[],
        tables=[TableDefinition(id="line_items", source="table_visual", confidence="avg_cell")],
    )


def _mock_visual_detector(table_region):
    """Return a patch context that mocks the VisualTableDetector."""
    mock_cls = MagicMock()
    mock_cls.return_value.detect.return_value = (
        [table_region] if table_region is not None else []
    )
    return patch.dict("sys.modules", {"app.services.table_visual.detector": MagicMock(
        VisualTableDetector=mock_cls
    )})


# -- Edge cases ---------------------------------------------------------------

class TestEmptyTableHeaderOnly:
    """Table with header only, no data rows."""

    def test_header_only_visual(self) -> None:
        header_only = _MockTableRegion(rows=[])
        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with _mock_visual_detector(header_only):
            result = kernel.extract(schema, [
                _make_ocr("品名 数量 単価 金額", 0.9, {"top_left": [10, 100], "bottom_right": [400, 120]}),
            ], image_bytes=b"\x89PNG fake")

        assert result.tables["line_items"] == []


class TestSingleRowTable:
    """Table with exactly one data row."""

    def test_single_row_visual(self) -> None:
        single_row = _MockTableRegion(rows=[
            [
                _MockCell("商品A", 0.90, 0, [10, 125, 100, 145]),
                _MockCell("2", 0.85, 1, [110, 125, 150, 145]),
                _MockCell("1,000", 0.88, 2, [160, 125, 250, 145]),
                _MockCell("2,000", 0.92, 3, [260, 125, 350, 145]),
            ],
        ])
        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with _mock_visual_detector(single_row):
            result = kernel.extract(schema, [
                _make_ocr("品名 数量 単価 金額", 0.9),
                _make_ocr("商品A 2 1,000 2,000", 0.85),
            ], image_bytes=b"\x89PNG fake")

        assert len(result.tables["line_items"]) == 1
        assert result.tables["line_items"][0]["col_0"]["text"] == "商品A"

    def test_single_row_text(self) -> None:
        """Text-based with a single data row."""
        schema = SchemaDefinition(
            id="test-single-text",
            version="1.0.0",
            document_type="test",
            tables=[TableDefinition(id="line_items", source="table_text")],
        )
        kernel = ExtractionKernel(source_registry)
        ocr = [
            _make_ocr("品名 数量 単価 金額", 0.9, {"top_left": [10, 100], "bottom_right": [400, 120]}),
            _make_ocr("商品A 2 1,000 2,000", 0.85, {"top_left": [10, 125], "bottom_right": [400, 145]}),
        ]
        result = kernel.extract(schema, ocr)
        assert "line_items" in result.tables


class TestMixedConfidenceCells:
    """Table with cells at very different confidence levels."""

    def test_mixed_confidence_cells(self) -> None:
        mixed = _MockTableRegion(rows=[
            [
                _MockCell("商品A", 0.10, 0, [10, 125, 100, 145]),  # very low
                _MockCell("2", 0.99, 1, [110, 125, 150, 145]),     # very high
                _MockCell("1,000", 0.50, 2, [160, 125, 250, 145]), # medium
                _MockCell("2,000", 0.75, 3, [260, 125, 350, 145]),
            ],
        ])
        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with _mock_visual_detector(mixed):
            result = kernel.extract(schema, [
                _make_ocr("品名 数量 単価 金額", 0.9),
            ], image_bytes=b"\x89PNG fake")

        rows = result.tables["line_items"]
        assert len(rows) == 1
        # Each cell retains its own confidence
        assert rows[0]["col_0"]["confidence"] == 0.10
        assert rows[0]["col_1"]["confidence"] == 0.99
        assert rows[0]["col_2"]["confidence"] == 0.50


class TestNoisyImageDetection:
    """Table detection on a very noisy image should degrade gracefully."""

    def test_noisy_image_detector_returns_empty(self) -> None:
        """Detector finds nothing on a noisy image — empty result, no crash."""
        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with _mock_visual_detector(None):
            result = kernel.extract(schema, [
                _make_ocr("asdfg 12345 !@#$%", 0.3, {"top_left": [5, 5], "bottom_right": [400, 25]}),
                _make_ocr("noise line here", 0.2, {"top_left": [5, 30], "bottom_right": [200, 50]}),
            ], image_bytes=b"\x89PNG noisy")

        assert result.tables["line_items"] == []

    def test_noisy_image_detector_raises(self) -> None:
        """Detector throws on corrupted image — kernel catches gracefully."""
        mock_cls = MagicMock()
        mock_cls.return_value.detect.side_effect = ValueError("corrupt image data")

        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with patch.dict("sys.modules", {"app.services.table_visual.detector": MagicMock(
            VisualTableDetector=mock_cls
        )}):
            result = kernel.extract(schema, [
                _make_ocr("noise", 0.1),
            ], image_bytes=b"corrupt")

        assert result.tables["line_items"] == []

    def test_noisy_ocr_text_table_fallback(self) -> None:
        """When OCR is garbage and source is table_text, returns empty gracefully."""
        schema = SchemaDefinition(
            id="test-noisy-text",
            version="1.0.0",
            document_type="test",
            tables=[TableDefinition(id="items", source="table_text")],
        )
        kernel = ExtractionKernel(source_registry)
        result = kernel.extract(schema, [
            _make_ocr("asdf", 0.1, {"top_left": [0, 0], "bottom_right": [50, 20]}),
            _make_ocr("qwerty", 0.15, {"top_left": [0, 25], "bottom_right": [80, 45]}),
        ])

        assert "items" in result.tables
        assert isinstance(result.tables["items"], list)


class TestTableRegionToDictsEdgeCases:
    """Edge cases for the _table_region_to_dicts helper."""

    def test_cell_with_col_attribute(self) -> None:
        """When cell has a .col attribute, use it as the key name."""
        @dataclass
        class CellWithCol:
            text: str
            confidence: float
            col: str
            bbox: list

        region = _MockTableRegion(rows=[
            [CellWithCol("x", 0.5, "品名", [0, 0, 10, 10])],
        ])
        # Override rows with the custom cell type
        region.rows = [[CellWithCol("x", 0.5, "品名", [0, 0, 10, 10])]]

        result = _table_region_to_dicts(region)
        assert "品名" in result[0]
        assert result[0]["品名"]["text"] == "x"

    def test_many_columns(self) -> None:
        """Table with many columns."""
        cells = [_MockCell(f"val{i}", 0.8, i, [i * 50, 0, (i + 1) * 50, 20]) for i in range(10)]
        region = _MockTableRegion(rows=[cells])
        result = _table_region_to_dicts(region)

        assert len(result[0]) == 10
        assert result[0]["col_5"]["text"] == "val5"

    def test_many_rows(self) -> None:
        """Table with many rows."""
        rows = [
            [_MockCell(f"item{i}", 0.8, 0, [0, i * 25, 100, (i + 1) * 25])]
            for i in range(50)
        ]
        region = _MockTableRegion(rows=rows)
        result = _table_region_to_dicts(region)

        assert len(result) == 50
        assert result[49]["col_0"]["text"] == "item49"
