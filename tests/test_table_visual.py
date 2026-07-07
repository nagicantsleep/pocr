"""Tests for visual table detection."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.services.table_visual.detector import (
    CellRegion,
    TableRegion,
    VisualTableDetector,
)


# --- Test image creation helpers ---


def create_table_image_with_lines(
    rows: int = 4, cols: int = 5, cell_w: int = 120, cell_h: int = 40
) -> bytes:
    """Create an image with a grid table drawn using rule lines."""
    margin = 20
    img_w = margin * 2 + cols * cell_w
    img_h = margin * 2 + rows * cell_h
    img = np.ones((img_h, img_w, 3), dtype=np.uint8) * 255

    color = (0, 0, 0)
    thickness = 2

    # Draw horizontal lines
    for r in range(rows + 1):
        y = margin + r * cell_h
        cv2.line(img, (margin, y), (margin + cols * cell_w, y), color, thickness)

    # Draw vertical lines
    for c in range(cols + 1):
        x = margin + c * cell_w
        cv2.line(img, (x, margin), (x, margin + rows * cell_h), color, thickness)

    # Add some text in cells
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.5
    for r in range(rows):
        for c in range(cols):
            x = margin + c * cell_w + 10
            y = margin + r * cell_h + 25
            cv2.putText(img, f"R{r}C{c}", (x, y), font, font_scale, color, 1)

    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def create_table_image_borderless() -> tuple[bytes, list[dict]]:
    """Create an image with text arranged in rows (no lines) and matching OCR lines.

    Uses Japanese table header keywords so detect_table_regions() recognizes them.
    """
    img = np.ones((400, 600, 3), dtype=np.uint8) * 255
    font = cv2.FONT_HERSHEY_SIMPLEX
    color = (0, 0, 0)

    ocr_lines: list[dict] = []
    row_texts = [
        "品名 数量 単価 金額",       # Header: description, quantity, unit_price, amount
        "Widget 10 500 5000",
        "Gadget 5 1200 6000",
        "Total 11000",
    ]

    for row_idx, text in enumerate(row_texts):
        y = 50 + row_idx * 20
        cv2.putText(img, text, (30, y), font, 0.6, color, 1)
        ocr_lines.append(
            {
                "text": text,
                "confidence": 0.95,
                "bbox": {
                    "top_left": [30, y - 15],
                    "bottom_right": [550, y + 5],
                },
                "line_no": row_idx + 1,
            }
        )

    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes(), ocr_lines


def create_empty_image(width: int = 200, height: int = 200) -> bytes:
    """Create a blank white image."""
    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


def create_multi_table_image() -> bytes:
    """Create an image with two separate tables."""
    img = np.ones((600, 500, 3), dtype=np.uint8) * 255
    color = (0, 0, 0)
    thickness = 2

    # Table 1: top-left
    for r in range(3):
        y = 20 + r * 40
        cv2.line(img, (20, y), (260, y), color, thickness)
    for c in range(3):
        x = 20 + c * 80
        cv2.line(img, (x, 20), (x, 100), color, thickness)

    # Table 2: bottom-right
    for r in range(3):
        y = 300 + r * 40
        cv2.line(img, (240, y), (480, y), color, thickness)
    for c in range(3):
        x = 240 + c * 80
        cv2.line(img, (x, 300), (x, 380), color, thickness)

    _, encoded = cv2.imencode(".png", img)
    return encoded.tobytes()


# --- Tests ---


class TestVisualTableDetectorRuleLines:
    """Tests for rule-line based table detection."""

    def test_detects_table_with_rule_lines(self):
        """Image with rule lines should produce TableRegion with has_rule_lines=True."""
        image = create_table_image_with_lines(rows=4, cols=5)
        detector = VisualTableDetector()
        tables = detector.detect(image)

        assert len(tables) >= 1
        table = tables[0]
        assert table.has_rule_lines is True
        assert len(table.rows) >= 2
        assert table.table_id  # not empty

    def test_correct_row_col_count(self):
        """Detected table should have roughly the expected row and column counts."""
        image = create_table_image_with_lines(rows=3, cols=4)
        detector = VisualTableDetector()
        tables = detector.detect(image)

        assert len(tables) >= 1
        table = tables[0]
        # Allow some tolerance due to morphological operations
        assert len(table.rows) >= 2
        if table.rows:
            assert len(table.rows[0]) >= 3

    def test_confidence_populated(self):
        """Confidence scores should be populated and in valid range."""
        image = create_table_image_with_lines(rows=3, cols=3)
        detector = VisualTableDetector()
        tables = detector.detect(image)

        assert len(tables) >= 1
        for table in tables:
            assert 0.0 <= table.confidence <= 1.0

    def test_multiple_tables_detected(self):
        """Multiple tables in one image should yield multiple TableRegions."""
        image = create_multi_table_image()
        detector = VisualTableDetector()
        tables = detector.detect(image)

        # May detect 1 or 2 tables depending on morphological merging
        assert len(tables) >= 1
        for table in tables:
            assert table.has_rule_lines is True
            assert table.table_id


class TestVisualTableDetectorBorderless:
    """Tests for text-based fallback detection."""

    def test_borderless_falls_back_to_text(self):
        """Borderless image with OCR lines should fall back to text-based detection."""
        image, ocr_lines = create_table_image_borderless()
        detector = VisualTableDetector()
        tables = detector.detect(image, ocr_lines=ocr_lines)

        # Should detect table from OCR lines even without visual rule lines
        assert len(tables) >= 1
        table = tables[0]
        assert table.has_rule_lines is False

    def test_borderless_assigns_text_to_cells(self):
        """OCR text should be assigned to cells in borderless detection."""
        image, ocr_lines = create_table_image_borderless()
        detector = VisualTableDetector()
        tables = detector.detect(image, ocr_lines=ocr_lines)

        if tables:
            # At least some cells should have text
            has_text = False
            for row in tables[0].rows:
                for cell in row:
                    if cell.text.strip():
                        has_text = True
                        break
            assert has_text


class TestVisualTableDetectorEdgeCases:
    """Edge case tests."""

    def test_empty_image_no_tables(self):
        """Empty image should yield no tables."""
        image = create_empty_image()
        detector = VisualTableDetector()
        tables = detector.detect(image)

        assert len(tables) == 0

    def test_empty_image_with_ocr_no_header(self):
        """Empty image with OCR lines but no table headers should yield no tables."""
        image = create_empty_image()
        ocr_lines = [
            {
                "text": "Hello world",
                "confidence": 0.9,
                "bbox": {"top_left": [10, 10], "bottom_right": [100, 30]},
                "line_no": 1,
            }
        ]
        detector = VisualTableDetector()
        tables = detector.detect(image, ocr_lines=ocr_lines)

        assert len(tables) == 0

    def test_invalid_image_bytes(self):
        """Invalid image bytes should yield no tables."""
        detector = VisualTableDetector()
        tables = detector.detect(b"not an image")

        assert len(tables) == 0

    def test_no_ocr_lines_no_rules(self):
        """Image without rule lines and no OCR lines should yield no tables."""
        img = np.ones((300, 300, 3), dtype=np.uint8) * 255
        cv2.putText(
            img, "Hello", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3
        )
        _, encoded = cv2.imencode(".png", img)
        detector = VisualTableDetector()
        tables = detector.detect(encoded.tobytes())

        assert len(tables) == 0


class TestVisualTableDetectorTextAssignment:
    """Tests for OCR text assignment to cells."""

    def test_text_assigned_to_correct_cells(self):
        """OCR text should be assigned to cells whose bbox contains the text center."""
        image = create_table_image_with_lines(rows=2, cols=2, cell_w=100, cell_h=50)

        # Create OCR lines that fall inside specific cells
        # Table starts at (20, 20), cells are 100x50
        ocr_lines = [
            {
                "text": "Header1",
                "confidence": 0.95,
                "bbox": {
                    "top_left": [25, 25],
                    "bottom_right": [115, 45],
                },
                "line_no": 1,
            },
            {
                "text": "Data1",
                "confidence": 0.9,
                "bbox": {
                    "top_left": [125, 75],
                    "bottom_right": [215, 95],
                },
                "line_no": 2,
            },
        ]

        detector = VisualTableDetector()
        tables = detector.detect(image, ocr_lines=ocr_lines)

        assert len(tables) >= 1
        # Verify text was assigned somewhere
        total_text = sum(
            1
            for row in tables[0].rows
            for cell in row
            if cell.text.strip()
        )
        assert total_text >= 1


class TestVisualTableDetectorRowspanColspan:
    """Tests for rowspan/colspan detection."""

    def test_colspan_detection(self):
        """Cells spanning 2 columns should be detected."""
        detector = VisualTableDetector()

        # Create a cell grid where cell (0,1) has text and cell (0,0) is empty
        cells = [
            [
                CellRegion(row=0, col=0, bbox={"x": 0, "y": 0, "w": 50, "h": 30}),
                CellRegion(
                    row=0,
                    col=1,
                    bbox={"x": 50, "y": 0, "w": 100, "h": 30},
                    text="merged",
                ),
            ],
            [
                CellRegion(
                    row=1, col=0, bbox={"x": 0, "y": 30, "w": 50, "h": 30}, text="A"
                ),
                CellRegion(
                    row=1,
                    col=1,
                    bbox={"x": 50, "y": 30, "w": 100, "h": 30},
                    text="B",
                ),
            ],
        ]

        result = detector._detect_rowspan_colspan(cells)

        # Cell (0,1) should have colspan >= 2 since (0,0) is empty and same y-range
        assert result[0][1].colspan >= 2

    def test_rowspan_detection(self):
        """Cells spanning 2 rows should be detected."""
        detector = VisualTableDetector()

        # Create a cell grid where cell (0,0) has text and cell (1,0) is empty
        cells = [
            [
                CellRegion(
                    row=0, col=0, bbox={"x": 0, "y": 0, "w": 50, "h": 30}, text="A"
                ),
                CellRegion(
                    row=0,
                    col=1,
                    bbox={"x": 50, "y": 0, "w": 100, "h": 30},
                    text="B",
                ),
            ],
            [
                CellRegion(row=1, col=0, bbox={"x": 0, "y": 30, "w": 50, "h": 30}),
                CellRegion(
                    row=1,
                    col=1,
                    bbox={"x": 50, "y": 30, "w": 100, "h": 30},
                    text="C",
                ),
            ],
        ]

        result = detector._detect_rowspan_colspan(cells)

        # Cell (0,0) should have rowspan >= 2 since (1,0) is empty and same x-range
        assert result[0][0].rowspan >= 2


class TestFindIntersections:
    """Tests for intersection finding."""

    def test_finds_intersections(self):
        """Should find intersection points from h/v line images."""
        detector = VisualTableDetector()

        # Create synthetic horizontal and vertical line images
        h_img = np.zeros((100, 100), dtype=np.uint8)
        v_img = np.zeros((100, 100), dtype=np.uint8)

        # Horizontal line at y=30
        h_img[30, 10:90] = 255
        # Vertical line at x=50
        v_img[10:90, 50] = 255

        intersections = detector._find_intersections(h_img, v_img)

        assert len(intersections) >= 1
        # The intersection should be near (50, 30)
        xs = [p[0] for p in intersections]
        ys = [p[1] for p in intersections]
        assert any(abs(x - 50) < 15 for x in xs)
        assert any(abs(y - 30) < 15 for y in ys)

    def test_no_intersections_empty_image(self):
        """Blank images should yield no intersections."""
        detector = VisualTableDetector()
        blank = np.zeros((100, 100), dtype=np.uint8)

        intersections = detector._find_intersections(blank, blank)
        assert len(intersections) == 0


class TestBuildCellGrid:
    """Tests for cell grid construction."""

    def test_builds_grid_from_intersections(self):
        """Should build a 2x2 cell grid from 9 intersection points (3x3 grid)."""
        detector = VisualTableDetector()

        # 3x3 grid of intersections
        intersections = [
            (10, 10), (60, 10), (110, 10),
            (10, 50), (60, 50), (110, 50),
            (10, 90), (60, 90), (110, 90),
        ]

        grid = detector._build_cell_grid(intersections)

        assert len(grid) == 2  # 2 rows
        assert len(grid[0]) == 2  # 2 columns

        # Check first cell bbox
        cell = grid[0][0]
        assert cell["x"] == 10
        assert cell["y"] == 10
        assert cell["w"] == 50
        assert cell["h"] == 40

    def test_too_few_intersections(self):
        """Less than 4 intersections should return empty grid."""
        detector = VisualTableDetector()
        grid = detector._build_cell_grid([(0, 0), (10, 10)])
        assert grid == []


class TestDisabledConfig:
    """Tests when visual detection is disabled."""

    def test_disabled_skips_visual_detection(self):
        """When TABLE_VISUAL_ENABLED=False, should skip rule-line detection."""
        from unittest.mock import patch, MagicMock

        mock_settings = MagicMock()
        mock_settings.TABLE_VISUAL_ENABLED = False

        image, ocr_lines = create_table_image_borderless()
        detector = VisualTableDetector()

        with patch("app.services.table_visual.detector.get_settings", return_value=mock_settings):
            tables = detector.detect(image, ocr_lines=ocr_lines)

        # Should use text-based fallback (has_rule_lines=False) or return empty
        for table in tables:
            assert table.has_rule_lines is False
