"""Visual table detection using OpenCV rule-line detection with text-based fallback."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.config import get_settings
from app.services.table_reconstructor import detect_table_regions

logger = logging.getLogger(__name__)


@dataclass
class CellRegion:
    """A detected cell in a table."""

    row: int
    col: int
    bbox: dict  # {x, y, w, h}
    text: str = ""
    confidence: float = 1.0
    rowspan: int = 1
    colspan: int = 1


@dataclass
class TableRegion:
    """A detected table with cells."""

    table_id: str
    page_no: int
    bbox: dict  # {x, y, w, h}
    rows: list[list[CellRegion]] = field(default_factory=list)
    header_row: list[CellRegion] | None = None
    has_rule_lines: bool = False
    confidence: float = 1.0


class VisualTableDetector:
    """Detects tables visually using OpenCV, with text-based fallback."""

    def detect(
        self,
        image_bytes: bytes,
        ocr_lines: list[dict] | None = None,
        page_no: int = 0,
    ) -> list[TableRegion]:
        """
        Detect tables in an image.

        Strategy:
        1. Convert image to grayscale
        2. Try rule-line detection (morphological operations)
        3. If no rule lines: fall back to text-based detection
        4. Merge overlapping table regions
        """
        settings = get_settings()
        if not settings.TABLE_VISUAL_ENABLED:
            if ocr_lines:
                return self._detect_borderless(image_bytes, ocr_lines, page_no)
            return []

        img_array = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        if img is None:
            logger.warning("Failed to decode image bytes")
            return []

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Try rule-line detection first
        rule_tables = self._detect_rule_lines(gray, page_no)

        if rule_tables:
            # Assign OCR text to cells if available
            if ocr_lines:
                for table in rule_tables:
                    self._assign_text_to_cells_from_ocr(table.rows, ocr_lines)
                    table.rows = self._detect_rowspan_colspan(table.rows)
                    table.header_row = table.rows[0] if table.rows else None
            return rule_tables

        # Fallback to text-based detection
        if ocr_lines:
            return self._detect_borderless(image_bytes, ocr_lines, page_no)

        return []

    def _detect_rule_lines(
        self, gray: np.ndarray, page_no: int
    ) -> list[TableRegion]:
        """Detect tables using horizontal/vertical rule lines."""
        settings = get_settings()
        kernel_size = settings.TABLE_VISUAL_KERNEL_SIZE
        min_line_length = settings.TABLE_VISUAL_MIN_LINE_LENGTH

        # Adaptive threshold
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 10
        )

        # Horizontal lines: kernel width >> height
        h_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_size, 1)
        )
        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)

        # Vertical lines: kernel height >> width
        v_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (1, kernel_size)
        )
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        # Combine horizontal and vertical lines
        combined = cv2.add(h_lines, v_lines)

        # Find contours to identify table regions
        contours, _ = cv2.findContours(
            combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        tables: list[TableRegion] = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            # Filter small contours
            if w < min_line_length * 2 or h < min_line_length * 2:
                continue

            # Extract region of interest
            roi_h = h_lines[y : y + h, x : x + w]
            roi_v = v_lines[y : y + h, x : x + w]

            # Find intersection points within this region
            intersections = self._find_intersections(roi_h, roi_v)

            if len(intersections) < 4:  # Need at least 4 points for a cell
                continue

            # Build cell grid from intersections
            cells = self._build_cell_grid(intersections, offset_x=x, offset_y=y)

            if not cells:
                continue

            # Convert cell grid to CellRegion objects
            cell_rows = self._cells_to_regions(cells)

            # Compute confidence based on grid regularity
            confidence = self._compute_grid_confidence(cells)

            table = TableRegion(
                table_id=str(uuid.uuid4()),
                page_no=page_no,
                bbox={"x": x, "y": y, "w": w, "h": h},
                rows=cell_rows,
                header_row=cell_rows[0] if cell_rows else None,
                has_rule_lines=True,
                confidence=confidence,
            )
            tables.append(table)

        return tables

    def _detect_borderless(
        self, image_bytes: bytes, ocr_lines: list[dict], page_no: int
    ) -> list[TableRegion]:
        """Fall back to text-based table detection."""
        text_regions = detect_table_regions(ocr_lines)
        if not text_regions:
            return []

        tables: list[TableRegion] = []
        for region in text_regions:
            bbox = region.get("bbox", {})
            tl = bbox.get("top_left", [0, 0])
            br = bbox.get("bottom_right", [0, 0])
            x, y = tl[0], tl[1]
            w, h = br[0] - tl[0], br[1] - tl[1]

            # Group OCR lines into rows by y-coordinate
            row_groups = self._group_lines_into_rows(ocr_lines, region)

            # Global column clustering across all rows
            all_region_lines = [line for row in row_groups for line in row]
            global_col_centers = self._compute_global_columns(all_region_lines, x, w)

            cell_rows: list[list[CellRegion]] = []
            for row_idx, row_lines in enumerate(row_groups):
                row_cells = self._assign_to_global_columns(row_lines, global_col_centers)
                for cell in row_cells:
                    cell.row = row_idx
                if row_cells:
                    cell_rows.append(row_cells)

            if cell_rows:
                tables.append(
                    TableRegion(
                        table_id=str(uuid.uuid4()),
                        page_no=page_no,
                        bbox={"x": x, "y": y, "w": w, "h": h},
                        rows=cell_rows,
                        header_row=cell_rows[0] if cell_rows else None,
                        has_rule_lines=False,
                        confidence=0.85,
                    )
                )

        return tables

    def _bin_columns_by_x(
        self, row_lines: list[dict], region_x: int, region_width: int
    ) -> list[CellRegion]:
        """Assign columns to lines based on x-coordinate overlap across rows.

        Lines with similar x_min values are placed in the same column.
        """
        if not row_lines:
            return []

        tolerance = max(10, region_width * 0.15)

        sorted_lines = sorted(row_lines, key=lambda l: l["bbox"]["top_left"][0])

        bins: list[list[dict]] = []
        bin_mins: list[int] = []
        for line in sorted_lines:
            x_min = line["bbox"]["top_left"][0]
            placed = False
            for i, center in enumerate(bin_mins):
                if abs(x_min - center) <= tolerance:
                    bins[i].append(line)
                    bin_mins[i] = min(center, x_min)
                    placed = True
                    break
            if not placed:
                bins.append([line])
                bin_mins.append(x_min)

        cells: list[CellRegion] = []
        for col_idx, bin_lines in enumerate(bins):
            for line in bin_lines:
                line_bbox = line.get("bbox", {})
                line_tl = line_bbox.get("top_left", [0, 0])
                line_br = line_bbox.get("bottom_right", [0, 0])
                cells.append(
                    CellRegion(
                        row=0,
                        col=col_idx,
                        bbox={
                            "x": line_tl[0],
                            "y": line_tl[1],
                            "w": line_br[0] - line_tl[0],
                            "h": line_br[1] - line_tl[1],
                        },
                        text=line.get("text", ""),
                        confidence=line.get("confidence", 0.9),
                    )
                )

        return cells

    def _compute_global_columns(
        self, all_lines: list[dict], region_x: int, region_width: int
    ) -> list[int]:
        """Compute global column x-centers from all lines in a region."""
        if not all_lines:
            return []
        tolerance = max(15, region_width * 0.08)
        x_positions = sorted(
            [(l["bbox"]["top_left"][0] + l["bbox"]["bottom_right"][0]) / 2 for l in all_lines]
        )
        clusters: list[list[float]] = []
        for x_pos in x_positions:
            if clusters and abs(x_pos - clusters[-1][-1]) <= tolerance:
                clusters[-1].append(x_pos)
            else:
                clusters.append([x_pos])
        return [int(sum(c) / len(c)) for c in clusters]

    def _assign_to_global_columns(
        self, row_lines: list[dict], global_centers: list[int]
    ) -> list[CellRegion]:
        """Assign each line to its nearest global column."""
        if not global_centers:
            return []
        cells: list[CellRegion] = []
        for line in row_lines:
            line_bbox = line.get("bbox", {})
            line_tl = line_bbox.get("top_left", [0, 0])
            line_br = line_bbox.get("bottom_right", [0, 0])
            cx = (line_tl[0] + line_br[0]) / 2
            best_col = min(range(len(global_centers)), key=lambda i: abs(cx - global_centers[i]))
            cells.append(
                CellRegion(
                    row=0,
                    col=best_col,
                    bbox={
                        "x": line_tl[0],
                        "y": line_tl[1],
                        "w": line_br[0] - line_tl[0],
                        "h": line_br[1] - line_tl[1],
                    },
                    text=line.get("text", ""),
                    confidence=line.get("confidence", 0.9),
                )
            )
        return cells

    def _group_lines_into_rows(
        self, ocr_lines: list[dict], region: dict
    ) -> list[list[dict]]:
        """Group OCR lines within a table region into rows by y-coordinate."""
        header_nos = set(region.get("header_line_nos", []))
        row_line_nos = set(region.get("row_line_nos", []))
        all_nos = header_nos | row_line_nos

        table_lines = [l for l in ocr_lines if l.get("line_no") in all_nos]
        if not table_lines:
            return []

        def y_center(line: dict) -> float:
            bbox = line["bbox"]
            return (bbox["top_left"][1] + bbox["bottom_right"][1]) / 2

        sorted_lines = sorted(
            table_lines, key=lambda l: (y_center(l), l["bbox"]["top_left"][0])
        )

        y_tolerance = 8.0
        rows: list[list[dict]] = []
        current_row: list[dict] = [sorted_lines[0]]
        current_y = y_center(sorted_lines[0])

        for line in sorted_lines[1:]:
            ly = y_center(line)
            if abs(ly - current_y) <= y_tolerance:
                current_row.append(line)
            else:
                rows.append(
                    sorted(current_row, key=lambda l: l["bbox"]["top_left"][0])
                )
                current_row = [line]
                current_y = ly

        rows.append(sorted(current_row, key=lambda l: l["bbox"]["top_left"][0]))
        return rows

    def _find_intersections(
        self, h_lines: np.ndarray, v_lines: np.ndarray
    ) -> list[tuple[int, int]]:
        """Find intersection points of horizontal and vertical lines."""
        # Intersections are where both horizontal and vertical lines exist
        intersection = cv2.bitwise_and(h_lines, v_lines)

        # Find non-zero points
        points = cv2.findNonZero(intersection)
        if points is None:
            return []

        # Convert to list of (x, y) tuples and deduplicate nearby points
        # findNonZero returns shape (N, 1, 2) — flatten to (x, y)
        raw_points = []
        for p in points:
            pt = p.ravel()
            raw_points.append((int(pt[0]), int(pt[1])))

        # Cluster nearby points (within 10px)
        clustered: list[tuple[int, int]] = []
        merge_dist = 10
        used = [False] * len(raw_points)

        for i, (px, py) in enumerate(raw_points):
            if used[i]:
                continue
            cluster_x, cluster_y = [px], [py]
            used[i] = True
            for j, (qx, qy) in enumerate(raw_points):
                if used[j]:
                    continue
                if abs(px - qx) <= merge_dist and abs(py - qy) <= merge_dist:
                    cluster_x.append(qx)
                    cluster_y.append(qy)
                    used[j] = True
            clustered.append(
                (int(sum(cluster_x) / len(cluster_x)),
                 int(sum(cluster_y) / len(cluster_y)))
            )

        return clustered

    def _build_cell_grid(
        self,
        intersections: list[tuple[int, int]],
        offset_x: int = 0,
        offset_y: int = 0,
    ) -> list[list[dict]]:
        """Build cell bounding boxes from intersection points."""
        if len(intersections) < 4:
            return []

        # Sort unique x and y coordinates
        xs = sorted(set(p[0] for p in intersections))
        ys = sorted(set(p[1] for p in intersections))

        # Filter out very close coordinates (< 5px apart)
        min_gap = 5
        filtered_xs = [xs[0]]
        for x in xs[1:]:
            if x - filtered_xs[-1] >= min_gap:
                filtered_xs.append(x)
        filtered_ys = [ys[0]]
        for y in ys[1:]:
            if y - filtered_ys[-1] >= min_gap:
                filtered_ys.append(y)

        if len(filtered_xs) < 2 or len(filtered_ys) < 2:
            return []

        # Build cell grid: cells[row][col] = {x, y, w, h}
        cells: list[list[dict]] = []
        for row_idx in range(len(filtered_ys) - 1):
            row_cells: list[dict] = []
            for col_idx in range(len(filtered_xs) - 1):
                cell_x = filtered_xs[col_idx] + offset_x
                cell_y = filtered_ys[row_idx] + offset_y
                cell_w = filtered_xs[col_idx + 1] - filtered_xs[col_idx]
                cell_h = filtered_ys[row_idx + 1] - filtered_ys[row_idx]
                row_cells.append(
                    {"x": cell_x, "y": cell_y, "w": cell_w, "h": cell_h}
                )
            cells.append(row_cells)

        return cells

    def _cells_to_regions(
        self, cells: list[list[dict]]
    ) -> list[list[CellRegion]]:
        """Convert raw cell dicts to CellRegion objects."""
        result: list[list[CellRegion]] = []
        for row_idx, row in enumerate(cells):
            region_row: list[CellRegion] = []
            for col_idx, cell in enumerate(row):
                region_row.append(
                    CellRegion(
                        row=row_idx,
                        col=col_idx,
                        bbox=cell,
                    )
                )
            result.append(region_row)
        return result

    def _assign_text_to_cells_from_ocr(
        self, rows: list[list[CellRegion]], ocr_lines: list[dict]
    ) -> None:
        """Assign OCR text to detected cell regions based on overlap."""
        for line in ocr_lines:
            line_bbox = line.get("bbox", {})
            line_tl = line_bbox.get("top_left", [0, 0])
            line_br = line_bbox.get("bottom_right", [0, 0])
            line_cx = (line_tl[0] + line_br[0]) / 2
            line_cy = (line_tl[1] + line_br[1]) / 2

            best_cell: CellRegion | None = None
            best_overlap = 0.0

            for row in rows:
                for cell in row:
                    cx = cell.bbox["x"]
                    cy = cell.bbox["y"]
                    cw = cell.bbox["w"]
                    ch = cell.bbox["h"]

                    # Check if line center is within cell
                    if (
                        cx <= line_cx <= cx + cw
                        and cy <= line_cy <= cy + ch
                    ):
                        # Compute overlap area for best match
                        overlap_w = min(line_br[0], cx + cw) - max(
                            line_tl[0], cx
                        )
                        overlap_h = min(line_br[1], cy + ch) - max(
                            line_tl[1], cy
                        )
                        overlap = max(0, overlap_w) * max(0, overlap_h)
                        if overlap > best_overlap:
                            best_overlap = overlap
                            best_cell = cell

            if best_cell is not None:
                if best_cell.text:
                    best_cell.text += " " + line.get("text", "")
                else:
                    best_cell.text = line.get("text", "")
                best_cell.confidence = min(
                    best_cell.confidence, line.get("confidence", 0.9)
                )

    def _detect_rowspan_colspan(
        self, cells: list[list[CellRegion]]
    ) -> list[list[CellRegion]]:
        """Detect merged cells by checking for empty adjacent cells.

        After detection, spanned-over cells are removed from the output and
        the spanning cell's bbox is expanded to cover the merged region.
        Rowspan takes priority over colspan at intersections.
        """
        if not cells:
            return cells

        rowspan_absorbed: set[tuple[int, int]] = set()
        colspan_absorbed: set[tuple[int, int]] = set()

        # --- rowspan first (top-to-bottom, priority over colspan) ---
        for row_idx, row in enumerate(cells):
            for cell in row:
                if not cell.text or (cell.row, cell.col) in rowspan_absorbed:
                    continue
                new_y = cell.bbox["y"]
                new_h = cell.bbox["h"]
                spans = 0
                check_row = cell.row + 1
                while True:
                    below = self._get_cell(cells, check_row, cell.col)
                    if below is None or below.text or (below.row, below.col) in rowspan_absorbed:
                        break
                    rowspan_absorbed.add((below.row, below.col))
                    new_h = (below.bbox["y"] + below.bbox["h"]) - new_y
                    spans += 1
                    check_row += 1
                if spans:
                    cell.rowspan += spans
                    cell.bbox["h"] = new_h

        # --- colspan second (absorb empty cells in the same row) ---
        for row in cells:
            for cell in row:
                if not cell.text:
                    continue
                new_x = cell.bbox["x"]
                new_w = cell.bbox["w"]
                spans = 0
                # Right
                check_col = cell.col + 1
                while True:
                    right = self._get_cell(cells, cell.row, check_col)
                    if right is None or right.text or (right.row, right.col) in rowspan_absorbed or (right.row, right.col) in colspan_absorbed:
                        break
                    colspan_absorbed.add((right.row, right.col))
                    new_w = (right.bbox["x"] + right.bbox["w"]) - new_x
                    spans += 1
                    check_col += 1
                # Left
                check_col = cell.col - 1
                while True:
                    left = self._get_cell(cells, cell.row, check_col)
                    if left is None or left.text or (left.row, left.col) in rowspan_absorbed or (left.row, left.col) in colspan_absorbed:
                        break
                    colspan_absorbed.add((left.row, left.col))
                    new_w = (new_x + new_w) - left.bbox["x"]
                    new_x = left.bbox["x"]
                    spans += 1
                    check_col -= 1
                if spans:
                    cell.colspan += spans
                    cell.bbox["x"] = new_x
                    cell.bbox["w"] = new_w

        # Remove absorbed cells and re-index columns
        absorbed = rowspan_absorbed | colspan_absorbed
        result: list[list[CellRegion]] = []
        for row in cells:
            remaining = [c for c in row if (c.row, c.col) not in absorbed]
            for idx, c in enumerate(remaining):
                c.col = idx
            result.append(remaining)

        return result

    def _get_cell(
        self, cells: list[list[CellRegion]], row: int, col: int
    ) -> CellRegion | None:
        """Get cell at (row, col) or None if out of bounds."""
        if row < 0 or row >= len(cells):
            return None
        row_cells = cells[row]
        if col < 0 or col >= len(row_cells):
            return None
        return row_cells[col]

    def _compute_grid_confidence(self, cells: list[list[dict]]) -> float:
        """Compute confidence based on grid regularity."""
        if not cells or not cells[0]:
            return 0.0

        # Check row height consistency
        row_heights = [row[0]["h"] for row in cells if row]
        if not row_heights:
            return 0.0

        avg_h = sum(row_heights) / len(row_heights)
        if avg_h == 0:
            return 0.5

        h_variance = sum((h - avg_h) ** 2 for h in row_heights) / len(row_heights)
        h_cv = (h_variance**0.5) / avg_h  # coefficient of variation

        # Check column width consistency (per column)
        num_cols = len(cells[0])
        col_widths_list: list[list[int]] = [[] for _ in range(num_cols)]
        for row in cells:
            for col_idx, cell in enumerate(row):
                if col_idx < num_cols:
                    col_widths_list[col_idx].append(cell["w"])

        col_cvs: list[float] = []
        for widths in col_widths_list:
            if not widths:
                continue
            avg_w = sum(widths) / len(widths)
            if avg_w == 0:
                col_cvs.append(1.0)
                continue
            w_var = sum((w - avg_w) ** 2 for w in widths) / len(widths)
            col_cvs.append((w_var**0.5) / avg_w)

        avg_col_cv = sum(col_cvs) / len(col_cvs) if col_cvs else 1.0

        # Lower CV = more regular = higher confidence
        regularity = 1.0 - min(1.0, (h_cv + avg_col_cv) / 2)
        return round(max(0.5, regularity), 2)
