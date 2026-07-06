"""Table region detection, row grouping, cell assignment, and line item parsing from OCR layout."""

import logging
import re
from typing import Optional

from app.schemas.invoice import InvoiceLineItem
from app.utils.money import normalize_amount

logger = logging.getLogger(__name__)

# Keywords that signal a table header row
_TABLE_HEADER_KEYWORDS = (
    "品名", "数量", "単位", "単価", "税率", "金額", "摘要", "明細",
    "仕品名", "商品名", "項目", "内訳", "件名", "内容",
)


def detect_table_regions(
    lines: list[dict],
    y_tolerance: float = 8.0,
) -> list[dict]:
    """
    Detect table regions from OCR lines.

    A table region starts when a line contains multiple header keywords
    (at least 2 from _TABLE_HEADER_KEYWORDS), and continues until a
    non-numeric/non-header line breaks the group.

    Args:
        lines: OCR lines with text, bbox, line_no (from layout_analyzer).
        y_tolerance: Max y-distance to consider lines in the same row.

    Returns:
        List of table region dicts with header_line_nos, row_line_nos, bbox.
    """
    if not lines:
        return []

    # Ensure each line has a line_no
    if lines and "line_no" not in lines[0]:
        lines = [{**l, "line_no": i + 1} for i, l in enumerate(lines)]

    # Find header lines (lines with 2+ table header keywords)
    header_indices: list[int] = []
    for i, line in enumerate(lines):
        text = line["text"]
        keyword_count = sum(1 for kw in _TABLE_HEADER_KEYWORDS if kw in text)
        if keyword_count >= 2:
            header_indices.append(i)

    # Also detect composite headers: multiple consecutive lines at similar y
    # each containing one keyword, collectively forming a header row
    composite_header_indices = _find_composite_headers(lines, y_tolerance)
    header_indices.extend(composite_header_indices)
    header_indices = sorted(set(header_indices))

    if not header_indices:
        return []

    regions: list[dict] = []
    for header_idx in header_indices:
        region = _build_region_from_header(lines, header_idx, y_tolerance)
        if region:
            regions.append(region)

    return regions


def _find_composite_headers(lines: list[dict], y_tolerance: float) -> list[int]:
    """
    Detect composite headers: multiple consecutive lines at similar y that
    each contain a table header keyword but no single line has 2+ keywords.
    """
    # Collect lines with exactly one keyword
    single_keyword_indices: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        text = line["text"]
        matched = [kw for kw in _TABLE_HEADER_KEYWORDS if kw in text]
        if len(matched) == 1:
            single_keyword_indices.append((i, matched[0]))

    if len(single_keyword_indices) < 2:
        return []

    # Group consecutive single-keyword lines that are at similar y
    composite_starts: list[int] = []
    current_group: list[int] = [single_keyword_indices[0][0]]
    current_bbox = lines[single_keyword_indices[0][0]]["bbox"]

    for idx, _ in single_keyword_indices[1:]:
        line_bbox = lines[idx]["bbox"]
        a_y_center = (current_bbox["top_left"][1] + current_bbox["bottom_right"][1]) / 2
        b_y_center = (line_bbox["top_left"][1] + line_bbox["bottom_right"][1]) / 2
        if abs(a_y_center - b_y_center) <= y_tolerance:
            current_group.append(idx)
        else:
            if len(current_group) >= 2:
                composite_starts.append(current_group[0])
            current_group = [idx]
            current_bbox = line_bbox

    if len(current_group) >= 2:
        composite_starts.append(current_group[0])

    return composite_starts


def _build_region_from_header(
    lines: list[dict],
    header_idx: int,
    y_tolerance: float,
) -> Optional[dict]:
    """Build a table region starting from a header line index."""
    header_line = lines[header_idx]
    row_line_nos: list[int] = []

    # Collect subsequent lines that look like table rows
    # (contain numeric content or are within y-tolerance of previous row)
    prev_bbox = header_line["bbox"]
    for i in range(header_idx + 1, len(lines)):
        line = lines[i]
        bbox = line["bbox"]

        # Check if this line is below the header and within y-tolerance of previous
        header_bottom = prev_bbox["bottom_right"][1]
        line_top = bbox["top_left"][1]
        y_gap = line_top - header_bottom

        if y_gap > y_tolerance * 3:
            # Too far below — table ended
            break

        # Check if line has numeric content (likely a data row)
        has_numeric = bool(re.search(r"\d+", line["text"]))
        # Or contains a table header keyword (another header row — stop)
        keyword_count = sum(1 for kw in _TABLE_HEADER_KEYWORDS if kw in line["text"])
        if keyword_count >= 2:
            break

        if has_numeric or _y_close(prev_bbox, bbox, y_tolerance):
            row_line_nos.append(line["line_no"])
            prev_bbox = bbox
        else:
            # Non-numeric, non-overlapping — table ended
            break

    if not row_line_nos:
        return None

    # Compute union bbox
    all_bboxes = [header_line["bbox"]] + [
        l["bbox"] for l in lines if l["line_no"] in row_line_nos
    ]
    all_left = min(b["top_left"][0] for b in all_bboxes)
    all_top = min(b["top_left"][1] for b in all_bboxes)
    all_right = max(b["bottom_right"][0] for b in all_bboxes)
    all_bottom = max(b["bottom_right"][1] for b in all_bboxes)

    return {
        "header_line_nos": [header_line["line_no"]],
        "row_line_nos": row_line_nos,
        "bbox": {"top_left": [all_left, all_top], "bottom_right": [all_right, all_bottom]},
    }


def _y_close(a: dict, b: dict, threshold: float = 8.0) -> bool:
    """Check if two bboxes are close vertically."""
    a_y_center = (a["top_left"][1] + a["bottom_right"][1]) / 2
    b_y_center = (b["top_left"][1] + b["bottom_right"][1]) / 2
    return abs(a_y_center - b_y_center) <= threshold


def group_rows_by_y(
    lines: list[dict],
    y_tolerance: float = 5.0,
) -> list[list[dict]]:
    """
    Group lines into rows by y-coordinate proximity.

    Args:
        lines: List of line dicts with bbox.
        y_tolerance: Max y-difference to consider same row.

    Returns:
        List of rows, each row is a list of lines sorted left-to-right.
    """
    if not lines:
        return []

    def y_center(line):
        bbox = line["bbox"]
        return (bbox["top_left"][1] + bbox["bottom_right"][1]) / 2

    sorted_lines = sorted(lines, key=lambda l: (y_center(l), l["bbox"]["top_left"][0]))

    rows: list[list[dict]] = []
    current_row: list[dict] = [sorted_lines[0]]
    current_y = y_center(sorted_lines[0])

    for line in sorted_lines[1:]:
        ly = y_center(line)
        if abs(ly - current_y) <= y_tolerance:
            current_row.append(line)
        else:
            rows.append(sorted(current_row, key=lambda l: l["bbox"]["top_left"][0]))
            current_row = [line]
            current_y = ly

    rows.append(sorted(current_row, key=lambda l: l["bbox"]["top_left"][0]))
    return rows


def group_rows(
    table_lines: list[dict],
    y_tolerance: float = 5.0,
) -> list[dict]:
    """
    Group OCR lines into table rows by y-position proximity.

    Args:
        table_lines: List of OCR line dicts with bbox, text, line_no.
        y_tolerance: Max y-difference to consider lines in the same row.

    Returns:
        List of row dicts, each with:
        - "line_nos": list of line numbers in this row
        - "y": average y position
        - "lines": list of line dicts sorted left-to-right
        - "text": concatenated text of all lines in this row
    """
    if not table_lines:
        return []

    def y_center(line):
        bbox = line["bbox"]
        return (bbox["top_left"][1] + bbox["bottom_right"][1]) / 2

    # Sort by y-center, then x
    sorted_lines = sorted(
        table_lines, key=lambda l: (y_center(l), l["bbox"]["top_left"][0])
    )

    rows: list[list[dict]] = []
    current_row: list[dict] = [sorted_lines[0]]
    current_y = y_center(sorted_lines[0])

    for line in sorted_lines[1:]:
        ly = y_center(line)
        if abs(ly - current_y) <= y_tolerance:
            current_row.append(line)
        else:
            rows.append(sorted(current_row, key=lambda l: l["bbox"]["top_left"][0]))
            current_row = [line]
            current_y = ly

    rows.append(sorted(current_row, key=lambda l: l["bbox"]["top_left"][0]))

    # Build row dicts
    result = []
    for row_lines in rows:
        y_vals = [y_center(l) for l in row_lines]
        result.append({
            "line_nos": [l["line_no"] for l in row_lines],
            "y": sum(y_vals) / len(y_vals),
            "lines": row_lines,
            "text": " ".join(l["text"] for l in row_lines).strip(),
        })

    return result


def _normalize_columns(columns: dict | list[dict]) -> list[dict]:
    """Accept either a dict with 'columns' key or a plain list of column dicts."""
    if isinstance(columns, list):
        return columns
    return columns.get("columns", [])


def assign_cells(rows: list[dict], columns: dict | list[dict]) -> list[dict]:
    """
    Assign each line in each row to a column based on x-position overlap.

    Args:
        rows: List of row dicts from group_rows().
        columns: Column dict with "columns" key (from infer_columns() output),
                 or a plain list of column dicts.

    Returns:
        List of rows with "cells" dict and "unassigned" list added.
    """
    col_list = _normalize_columns(columns)
    if not col_list:
        return [{**r, "cells": {}, "unassigned": list(r["lines"])} for r in rows]

    result = []
    for row in rows:
        cells: dict[str, dict] = {}
        unassigned: list[dict] = []

        for line in row["lines"]:
            cell_x = line["bbox"]["top_left"][0]
            best_col = None
            best_distance = float("inf")
            best_col_idx = -1

            for idx, col in enumerate(col_list):
                col_center = (col["x_start"] + col["x_end"]) / 2
                distance = abs(cell_x - col_center)
                if distance < best_distance:
                    best_distance = distance
                    best_col = col.get("type") or col.get("name")
                    best_col_idx = idx

            # Check column boundary overlap
            in_any = any(
                col["x_start"] <= cell_x <= col["x_end"]
                for col in col_list
            )

            if best_col and in_any:
                col = col_list[best_col_idx]
                col_width = col["x_end"] - col["x_start"]
                # Determine confidence based on how centered the cell is
                col_center = (col["x_start"] + col["x_end"]) / 2
                offset_ratio = (
                    abs(cell_x - col_center) / col_width if col_width > 0 else 1.0
                )

                if offset_ratio > 0.5:
                    # Overlaps but poorly centered — also check if it could be another column
                    other_matches = [
                        c
                        for c in col_list
                        if c["x_start"] <= cell_x <= c["x_end"]
                    ]
                    if len(other_matches) > 1:
                        confidence = 0.0
                    else:
                        confidence = round(max(0.0, 1.0 - offset_ratio), 2)
                else:
                    confidence = round(max(0.0, 1.0 - offset_ratio), 2)

                # Handle multiline descriptions: if line already has a
                # description cell, append text to it
                col_type = col.get("type") or col.get("name", best_col)
                if col_type == "description" and col_type in cells:
                    cells[col_type]["text"] += " " + line["text"]
                    # Keep minimum confidence across fragments
                    cells[col_type]["confidence"] = min(
                        cells[col_type]["confidence"], confidence
                    )
                else:
                    cells[col_type] = {
                        "text": line["text"],
                        "confidence": confidence,
                        "column_name": best_col,
                    }
            else:
                # Line doesn't fit any column boundary — check if it is near
                # the description column (multiline description handling)
                desc_col = next(
                    (c for c in col_list if c.get("type") == "description"), None
                )
                if desc_col and "description" in cells:
                    desc_center = (desc_col["x_start"] + desc_col["x_end"]) / 2
                    desc_width = desc_col["x_end"] - desc_col["x_start"]
                    if abs(cell_x - desc_center) <= desc_width * 0.8:
                        cells["description"]["text"] += " " + line["text"]
                        # Reduce confidence for appended text
                        cells["description"]["confidence"] = round(
                            cells["description"]["confidence"] * 0.9, 2
                        )
                    else:
                        unassigned.append(line)
                else:
                    unassigned.append(line)

        result.append({
            **row,
            "cells": cells,
            "unassigned": unassigned,
        })

    return result


def reconstruct_table(layout_doc: dict, table_region: dict, columns: dict) -> dict:
    """
    Full table reconstruction: get lines from table_region, group into rows,
    assign cells.

    Args:
        layout_doc: Layout analyzer output with "lines".
        table_region: A single table region dict from detect_table_regions().
        columns: Column dict from infer_columns() (has "columns" key).

    Returns:
        Dict with:
        - "rows": list of row dicts with cells assigned
        - "column_info": the columns dict
        - "row_count": number of rows
        - "confidence": overall confidence
    """
    lines_by_no = {l["line_no"]: l for l in layout_doc.get("lines", [])}

    line_nos = table_region.get("row_line_nos", [])
    # Exclude header lines from data rows
    header_nos = set(table_region.get("header_line_nos", []))
    data_nos = [n for n in line_nos if n not in header_nos]

    table_lines = [lines_by_no[n] for n in data_nos if n in lines_by_no]

    if not table_lines:
        return {
            "rows": [],
            "column_info": columns,
            "row_count": 0,
            "confidence": 1.0,
        }

    rows = group_rows(table_lines)
    col_list = _normalize_columns(columns)
    rows = assign_cells(rows, col_list)

    # Flag discount rows (lines with negative amounts or minus signs)
    for row in rows:
        row_text = row.get("text", "")
        has_minus = bool(re.search(r"[−\-–—]", row_text))
        has_negative_amount = False
        if "amount" in row.get("cells", {}):
            amount_text = row["cells"]["amount"].get("text", "")
            try:
                val = float(amount_text.replace(",", ""))
                if val < 0:
                    has_negative_amount = True
            except (ValueError, TypeError):
                pass
        row["is_discount"] = has_minus or has_negative_amount

    # Overall confidence: average cell confidence across all assigned cells
    confidences = []
    for row in rows:
        for cell in row.get("cells", {}).values():
            confidences.append(cell.get("confidence", 1.0))

    overall_conf = round(sum(confidences) / len(confidences), 2) if confidences else 1.0

    return {
        "rows": rows,
        "column_info": col_list,
        "row_count": len(rows),
        "confidence": overall_conf,
    }


def parse_line_items(table_result: dict) -> list[InvoiceLineItem]:
    """
    Parse reconstructed table rows into InvoiceLineItem objects.

    table_result comes from reconstruct_table() output with "rows" containing "cells".

    For each row:
    - description: from description column text
    - quantity: from quantity column, parse as float
    - unit: from unit column text
    - unit_price: from unit_price column, parse as int via normalize_amount
    - tax_rate: from tax_rate column (normalize "10%対象" -> "10%", etc.)
    - amount_excluding_tax: from amount column, parse as int
    - Compute tax_amount and amount_including_tax if possible
    - confidence: from cell confidence values
    - needs_review: if confidence < 0.70 or required fields missing
    """
    rows = table_result.get("rows", [])
    items: list[InvoiceLineItem] = []

    for row_idx, row in enumerate(rows):
        cells = row.get("cells", {})
        is_discount = row.get("is_discount", False)

        # Extract raw text from each known column
        desc_cell = cells.get("description", {})
        qty_cell = cells.get("quantity", {})
        unit_cell = cells.get("unit", {})
        price_cell = cells.get("unit_price", {})
        rate_cell = cells.get("tax_rate", {})
        amt_cell = cells.get("amount", {})

        description = desc_cell.get("text") if desc_cell else None
        quantity_text = qty_cell.get("text") if qty_cell else None
        unit = unit_cell.get("text") if unit_cell else None
        unit_price_text = price_cell.get("text") if price_cell else None
        tax_rate_text = rate_cell.get("text") if rate_cell else None
        amount_text = amt_cell.get("text") if amt_cell else None

        # Parse fields
        quantity = _parse_quantity(quantity_text)
        unit_price = normalize_amount(unit_price_text)
        amount_excluding_tax = normalize_amount(amount_text)

        # Parse tax rate: extract the percentage, e.g. "10%対象" -> "10%"
        tax_rate = _parse_tax_rate(tax_rate_text)

        # Compute derived amounts
        tax_amount = None
        amount_including_tax = None

        if amount_excluding_tax is not None and tax_rate is not None:
            rate_value = _rate_to_float(tax_rate)
            if rate_value is not None:
                tax_amount = round(amount_excluding_tax * rate_value)
                amount_including_tax = amount_excluding_tax + tax_amount

        # Compute confidence from cell values
        conf_values = [
            c.get("confidence", 1.0)
            for c in cells.values()
            if isinstance(c, dict) and "confidence" in c
        ]
        confidence = round(sum(conf_values) / len(conf_values), 4) if conf_values else 1.0

        # Determine needs_review
        missing_required = description is None or (
            amount_excluding_tax is None and unit_price is None and quantity is None
        )
        needs_review = confidence < 0.70 or missing_required

        # Discount rows: amount may be negative, stored as discount field
        discount = None
        if is_discount and amount_excluding_tax is not None and amount_excluding_tax < 0:
            discount = -amount_excluding_tax
            amount_excluding_tax = None

        items.append(InvoiceLineItem(
            line_no=row_idx + 1,
            description=description,
            quantity=quantity,
            unit=unit,
            unit_price=abs(unit_price) if unit_price is not None else None,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
            amount_excluding_tax=amount_excluding_tax,
            amount_including_tax=amount_including_tax,
            discount=discount,
            confidence=confidence,
            needs_review=needs_review,
            source_cells=cells,
        ))

    return items


def _parse_quantity(text: str | None) -> float | None:
    """Parse a quantity string to float."""
    if not text:
        return None
    cleaned = text.strip().replace(",", "").replace("，", "")
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_tax_rate(text: str | None) -> str | None:
    """
    Normalize a tax rate string to one of: "8%", "10%", "non_taxable", "exempt", "unknown".

    Handles formats like "10%対象" -> "10%", "8%" -> "8%", "対象" -> "non_taxable", etc.
    """
    if not text:
        return None

    text = text.strip()

    # Check for explicit percentage
    pct_match = re.search(r"(\d{1,2})\s*%", text)
    if pct_match:
        rate = int(pct_match.group(1))
        if rate == 8:
            return "8%"
        elif rate == 10:
            return "10%"

    # Check for non-taxable indicators
    non_taxable_kw = ["非課税", "対象外", "非対象", "不課税"]
    for kw in non_taxable_kw:
        if kw in text:
            return "non_taxable"

    # Check for exempt
    if "免除" in text or "免税" in text:
        return "exempt"

    # If we got a percentage-like number but not with %, check
    num_match = re.search(r"(\d{1,2})", text)
    if num_match:
        rate = int(num_match.group(1))
        if rate == 8:
            return "8%"
        elif rate == 10:
            return "10%"

    return "unknown"


def _rate_to_float(rate_str: str | None) -> float | None:
    """Convert a tax rate string like '8%' to a decimal multiplier like 0.08."""
    if rate_str is None:
        return None
    pct_match = re.search(r"(\d{1,2})\s*%", rate_str)
    if pct_match:
        return int(pct_match.group(1)) / 100.0
    return None
