"""Column inference from table header lines and cell positions."""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Maps Japanese header keywords to column types
_HEADER_KEYWORD_MAP: dict[str, str] = {
    "品名": "description",
    "仕品名": "description",
    "商品名": "description",
    "摘要": "description",
    "明細": "description",
    "項目": "description",
    "内訳": "description",
    "件名": "description",
    "内容": "description",
    "数量": "quantity",
    "数": "quantity",
    "単位": "unit",
    "単価": "unit_price",
    "税率": "tax_rate",
    "税": "tax_rate",
    "金額": "amount",
    "小計": "amount",
    "合計": "amount",
    "価格": "unit_price",
    "料金": "amount",
}

# Column types that expect numeric values
_NUMERIC_COLUMNS = {"quantity", "unit_price", "tax_rate", "amount"}


def infer_columns_from_header(
    header_line: dict,
) -> list[dict]:
    """
    Infer column definitions from a table header line.

    The header_line should have 'text' and 'bbox'. We look for known
    keywords and assign column types based on keyword matches.

    Args:
        header_line: Dict with text, bbox, and optionally sub-cells.

    Returns:
        List of column dicts: [{"type": "description", "x_start": 50, "x_end": 200}, ...]
    """
    text = header_line["text"]
    bbox = header_line["bbox"]

    # Try to find keyword positions in the text
    columns: list[dict] = []
    found_types: set[str] = set()

    for keyword, col_type in _HEADER_KEYWORD_MAP.items():
        idx = text.find(keyword)
        if idx >= 0 and col_type not in found_types:
            # Estimate x-position from character position
            char_count = len(text)
            text_width = bbox["bottom_right"][0] - bbox["top_left"][0]
            char_width = text_width / char_count if char_count > 0 else 20.0

            x_start = bbox["top_left"][0] + idx * char_width
            x_end = x_start + len(keyword) * char_width

            columns.append({
                "type": col_type,
                "x_start": round(x_start, 1),
                "x_end": round(x_end, 1),
                "keyword": keyword,
            })
            found_types.add(col_type)

    # Sort columns by x_start
    columns.sort(key=lambda c: c["x_start"])

    return columns


def infer_columns_from_positions(
    row_lines: list[dict],
    header_columns: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Infer column positions from data row positions.

    If header_columns are provided, use them as anchor points.
    Otherwise, cluster x-positions from data cells.

    Args:
        row_lines: List of row line dicts with bbox.
        header_columns: Optional header column definitions.

    Returns:
        List of column dicts with type, x_start, x_end.
    """
    if not row_lines:
        return header_columns or []

    if header_columns:
        return _refine_columns_from_data(row_lines, header_columns)

    return _cluster_columns_from_data(row_lines)


def _refine_columns_from_data(
    row_lines: list[dict],
    header_columns: list[dict],
) -> list[dict]:
    """Refine header columns using data row x-positions."""
    # For each header column, find data cells that fall within its x-range
    refined = []
    for col in header_columns:
        x_start = col["x_start"]
        x_end = col["x_end"]
        # Expand range slightly to catch nearby cells
        margin = (x_end - x_start) * 0.3

        matching_cells = []
        for line in row_lines:
            cell_x = line["bbox"]["top_left"][0]
            if (x_start - margin) <= cell_x <= (x_end + margin):
                matching_cells.append(line)

        if matching_cells:
            # Recalculate column bounds from actual cells
            actual_left = min(c["bbox"]["top_left"][0] for c in matching_cells)
            actual_right = max(c["bbox"]["bottom_right"][0] for c in matching_cells)
            refined.append({
                **col,
                "x_start": actual_left,
                "x_end": actual_right,
                "cell_count": len(matching_cells),
            })
        else:
            refined.append({**col, "cell_count": 0})

    return refined


def _cluster_columns_from_data(row_lines: list[dict]) -> list[dict]:
    """
    Cluster x-positions from data rows to infer columns without headers.

    Uses a simple gap-based clustering: if the x-gap between consecutive
    cells is > threshold, they belong to different columns.
    """
    # Collect all cell x-positions (left edge)
    x_positions: list[float] = []
    for line in row_lines:
        x_positions.append(line["bbox"]["top_left"][0])

    if not x_positions:
        return []

    x_positions.sort()

    # Cluster by gap
    clusters: list[list[float]] = [[x_positions[0]]]
    gap_threshold = 30.0  # pixels

    for x in x_positions[1:]:
        if x - clusters[-1][-1] <= gap_threshold:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    # Build column definitions
    columns = []
    for i, cluster in enumerate(clusters):
        x_start = min(cluster)
        x_end = max(cluster) + 40  # estimate cell width
        # Guess column type from position (left = description, right = amounts)
        if i == 0:
            col_type = "description"
        elif i == len(clusters) - 1:
            col_type = "amount"
        elif i == len(clusters) - 2:
            col_type = "unit_price"
        else:
            col_type = "unknown"

        columns.append({
            "type": col_type,
            "x_start": x_start,
            "x_end": x_end,
            "cell_count": len(cluster),
        })

    return columns


def assign_cell_to_column(
    cell_bbox: dict,
    columns: list[dict],
) -> Optional[str]:
    """
    Assign a cell to the best-matching column based on x-position.

    Args:
        cell_bbox: Cell bbox dict with top_left/bottom_right.
        columns: List of column dicts with x_start, x_end, type.

    Returns:
        Column type string, or None if no match.
    """
    cell_x = cell_bbox["top_left"][0]
    best_col = None
    best_distance = float("inf")

    for col in columns:
        col_center = (col["x_start"] + col["x_end"]) / 2
        distance = abs(cell_x - col_center)
        if distance < best_distance:
            best_distance = distance
            best_col = col["type"]

    # Only assign if cell is reasonably close to a column
    if best_col and best_distance < 100:
        return best_col
    return None
