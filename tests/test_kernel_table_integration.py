"""Tests for kernel table extraction integration with schema-driven pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch, MagicMock

import pytest

from app.schemas.registry.schema_model import (
    SchemaDefinition,
    FieldDefinition,
    TableDefinition,
)
from app.services.extraction_kernel.kernel import (
    ExtractionKernel,
    ExtractionResult,
    _table_region_to_dicts,
)
from app.services.extraction_kernel.source_registry import SourceRegistry, source_registry


# -- helpers -------------------------------------------------------------------

def _make_ocr(text: str, confidence: float = 0.9, bbox=None) -> dict:
    if bbox is None:
        bbox = {"top_left": [10, 10], "bottom_right": [200, 30]}
    return {"text": text, "confidence": confidence, "bbox": bbox}


mock_table_ocr = [
    _make_ocr("品名 数量 単価 金額", 0.9, {"top_left": [10, 100], "bottom_right": [400, 120]}),
    _make_ocr("商品A 2 1,000 2,000", 0.85, {"top_left": [10, 125], "bottom_right": [400, 145]}),
    _make_ocr("商品B 1 3,000 3,000", 0.88, {"top_left": [10, 150], "bottom_right": [400, 170]}),
]

# Minimal OCR for field extraction (non-table lines)
field_ocr = [
    _make_ocr("登録番号: T1234567890123", 0.95, {"top_left": [10, 10], "bottom_right": [300, 30]}),
    _make_ocr("株式会社テスト", 0.88, {"top_left": [10, 50], "bottom_right": [200, 70]}),
]


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


def _make_mock_table_region():
    """Create a mock TableRegion with 2 data rows and 4 columns."""
    return _MockTableRegion(
        rows=[
            [
                _MockCell("商品A", 0.90, 0, [10, 125, 100, 145]),
                _MockCell("2", 0.85, 1, [110, 125, 150, 145]),
                _MockCell("1,000", 0.88, 2, [160, 125, 250, 145]),
                _MockCell("2,000", 0.92, 3, [260, 125, 350, 145]),
            ],
            [
                _MockCell("商品B", 0.88, 0, [10, 150, 100, 170]),
                _MockCell("1", 0.90, 1, [110, 150, 150, 170]),
                _MockCell("3,000", 0.85, 2, [160, 150, 250, 170]),
                _MockCell("3,000", 0.87, 3, [260, 150, 350, 170]),
            ],
        ]
    )


def _make_schema_with_visual_table() -> SchemaDefinition:
    return SchemaDefinition(
        id="test-visual",
        version="1.0.0",
        document_type="test",
        fields=[],
        tables=[TableDefinition(id="line_items", source="table_visual", confidence="avg_cell")],
    )


def _make_schema_with_text_table() -> SchemaDefinition:
    return SchemaDefinition(
        id="test-text",
        version="1.0.0",
        document_type="test",
        fields=[],
        tables=[TableDefinition(id="line_items", source="table_text", confidence="avg_cell")],
    )


def _make_schema_no_tables() -> SchemaDefinition:
    return SchemaDefinition(
        id="test-no-tables",
        version="1.0.0",
        document_type="test",
        fields=[],
        tables=[],
    )


def _make_schema_multiple_tables() -> SchemaDefinition:
    return SchemaDefinition(
        id="test-multi",
        version="1.0.0",
        document_type="test",
        fields=[],
        tables=[
            TableDefinition(id="table_a", source="table_text"),
            TableDefinition(id="table_b", source="table_visual"),
        ],
    )


# -- _table_region_to_dicts tests ----------------------------------------------

class TestTableRegionToDicts:
    def test_converts_cells_to_row_dicts(self) -> None:
        region = _make_mock_table_region()
        result = _table_region_to_dicts(region)

        assert len(result) == 2
        # First row
        assert result[0]["col_0"]["text"] == "商品A"
        assert result[0]["col_0"]["confidence"] == 0.90
        assert result[0]["col_1"]["text"] == "2"
        assert result[0]["col_3"]["text"] == "2,000"
        # Second row
        assert result[1]["col_0"]["text"] == "商品B"

    def test_preserves_bbox(self) -> None:
        region = _make_mock_table_region()
        result = _table_region_to_dicts(region)

        assert result[0]["col_0"]["bbox"] == [10, 125, 100, 145]

    def test_empty_region_returns_empty(self) -> None:
        region = _MockTableRegion(rows=[])
        assert _table_region_to_dicts(region) == []


# -- Kernel table integration tests -------------------------------------------

class TestKernelTableIntegration:
    def test_schema_with_no_tables_gives_empty_tables_dict(self) -> None:
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_no_tables()
        result = kernel.extract(schema, mock_table_ocr)

        assert isinstance(result, ExtractionResult)
        assert result.tables == {}

    def test_text_table_source_used_when_no_image_bytes(self) -> None:
        """When source=table_text, text-based extraction is used regardless of image_bytes."""
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_with_text_table()
        # Provide table-like OCR that layout_analyzer will detect as table_candidates
        result = kernel.extract(schema, mock_table_ocr)

        assert "line_items" in result.tables
        assert isinstance(result.tables["line_items"], list)

    def test_visual_source_with_image_bytes_calls_detector(self) -> None:
        """When source=table_visual and image_bytes is provided, the visual detector is invoked."""
        mock_region = _make_mock_table_region()
        mock_detector_cls = MagicMock()
        mock_detector_cls.return_value.detect.return_value = [mock_region]

        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with patch.dict("sys.modules", {"app.services.table_visual.detector": MagicMock(
            VisualTableDetector=mock_detector_cls
        )}):
            result = kernel.extract(schema, mock_table_ocr, image_bytes=b"\x89PNG fake")

        assert "line_items" in result.tables
        assert len(result.tables["line_items"]) == 2
        mock_detector_cls.assert_called_once()

    def test_visual_source_without_image_bytes_falls_back_to_text(self) -> None:
        """When source=table_visual but image_bytes=None, falls back to text-based extraction."""
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_with_visual_table()
        result = kernel.extract(schema, mock_table_ocr, image_bytes=None)

        assert "line_items" in result.tables
        # Should still produce a result (text-based path), even if empty
        assert isinstance(result.tables["line_items"], list)

    def test_visual_detector_import_error_graceful(self) -> None:
        """If VisualTableDetector module doesn't exist, kernel handles ImportError gracefully."""
        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        # Patch the import to raise ImportError
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "app.services.table_visual.detector":
                raise ImportError("No module named 'app.services.table_visual.detector'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = kernel.extract(schema, mock_table_ocr, image_bytes=b"\x89PNG")

        assert "line_items" in result.tables
        assert result.tables["line_items"] == []

    def test_visual_detector_returns_empty_list(self) -> None:
        """When detector finds no tables, returns empty list."""
        mock_detector_cls = MagicMock()
        mock_detector_cls.return_value.detect.return_value = []

        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with patch.dict("sys.modules", {"app.services.table_visual.detector": MagicMock(
            VisualTableDetector=mock_detector_cls
        )}):
            result = kernel.extract(schema, mock_table_ocr, image_bytes=b"\x89PNG fake")

        assert result.tables["line_items"] == []

    def test_visual_detector_exception_handled(self) -> None:
        """When detector raises an exception, kernel handles it gracefully."""
        mock_detector_cls = MagicMock()
        mock_detector_cls.return_value.detect.side_effect = RuntimeError("GPU error")

        schema = _make_schema_with_visual_table()
        kernel = ExtractionKernel(source_registry)

        with patch.dict("sys.modules", {"app.services.table_visual.detector": MagicMock(
            VisualTableDetector=mock_detector_cls
        )}):
            result = kernel.extract(schema, mock_table_ocr, image_bytes=b"\x89PNG fake")

        assert result.tables["line_items"] == []

    def test_multiple_tables_in_schema(self) -> None:
        """Schema with multiple table definitions produces results for each."""
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_multiple_tables()
        result = kernel.extract(schema, mock_table_ocr)

        assert "table_a" in result.tables
        assert "table_b" in result.tables

    def test_table_results_appear_in_extraction_result(self) -> None:
        """Verify the tables field of ExtractionResult is populated."""
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_with_text_table()
        result = kernel.extract(schema, mock_table_ocr)

        assert hasattr(result, "tables")
        assert isinstance(result.tables, dict)

    def test_kernel_with_invoice_jp_schema_and_table_ocr(self) -> None:
        """Full integration: invoice-jp schema with table-like OCR data."""
        from app.schemas.registry.schema_registry import SchemaRegistry
        from pathlib import Path

        registry = SchemaRegistry(Path("app/schemas/registry"))
        registry.load()
        schema = registry.get("invoice-jp", "1.0.0")
        assert schema is not None

        full_ocr = field_ocr + mock_table_ocr
        kernel = ExtractionKernel(source_registry)
        result = kernel.extract(schema, full_ocr)

        # Field extraction still works
        assert result.fields["issuer_registration_number"].value == "T1234567890123"
        # Table result exists (even if empty due to text-based fallback)
        assert "line_items" in result.tables
        assert isinstance(result.tables["line_items"], list)

    def test_extract_signature_accepts_image_bytes(self) -> None:
        """Verify extract() accepts the image_bytes parameter."""
        kernel = ExtractionKernel(source_registry)
        schema = _make_schema_no_tables()

        # Should not raise
        result = kernel.extract(schema, [], image_bytes=None)
        assert isinstance(result, ExtractionResult)

        result2 = kernel.extract(schema, [], image_bytes=b"test")
        assert isinstance(result2, ExtractionResult)
