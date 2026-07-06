"""Layout analyzer: sort, merge, classify OCR results into structured blocks."""

import logging
from typing import Optional

from app.utils.japanese_text import classify_line, merge_fragments

logger = logging.getLogger(__name__)


def analyze_layout(
    ocr_results: list[dict],
    y_tolerance: float = 5.0,
    image_height: Optional[int] = None,
) -> dict:
    """
    Analyze spatial layout of OCR results.

    Steps:
    1. Sort lines top-to-bottom (y), grouping by y_tolerance into rows.
    2. Within each row, sort left-to-right (x).
    3. Merge fragmented lines (close x-proximity).
    4. Generate plain_text in reading order.
    5. Classify line groups into blocks.
    6. Detect table candidates.

    Args:
        ocr_results: List of OCR result dicts (text, confidence, bbox, etc.)
        y_tolerance: Max y-difference to consider lines in the same row.
        image_height: Image height for percentage-based classification.

    Returns:
        Dict with plain_text, lines, blocks, table_candidates.
    """
    if not ocr_results:
        return {
            "plain_text": "",
            "lines": [],
            "blocks": [],
            "table_candidates": [],
        }

    # Step 1+2: Sort into rows by y-coordinate, then left-to-right
    rows = _group_into_rows(ocr_results, y_tolerance)

    # Step 3: Merge fragments within each row
    merged_rows = []
    for row in rows:
        merged = merge_fragments(row)
        merged_rows.append(merged)

    # Build flat list of merged lines with line numbers
    all_lines = []
    line_no = 1
    for row in merged_rows:
        # Sort row left-to-right after merge
        row.sort(key=lambda l: l["bbox"]["top_left"][0])
        for line in row:
            all_lines.append({
                "text": line["text"],
                "confidence": line["confidence"],
                "bbox": line["bbox"],
                "line_no": line_no,
            })
            line_no += 1

    # Step 4: Plain text
    plain_text = "\n".join(l["text"] for l in all_lines)

    # Determine image_height if not provided
    if image_height is None and all_lines:
        image_height = max(l["bbox"]["bottom_right"][1] for l in all_lines)

    # Step 5: Classify blocks
    blocks = _classify_blocks(all_lines, image_height or 1000)

    # Step 6: Detect table candidates
    table_candidates = _detect_table_candidates(all_lines)

    return {
        "plain_text": plain_text,
        "lines": all_lines,
        "blocks": blocks,
        "table_candidates": table_candidates,
    }


def _group_into_rows(lines: list[dict], y_tolerance: float) -> list[list[dict]]:
    """Group lines into rows based on y-coordinate proximity."""
    if not lines:
        return []

    # Sort by y-center
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
            rows.append(current_row)
            current_row = [line]
            current_y = ly

    rows.append(current_row)
    return rows


def _classify_blocks(lines: list[dict], image_height: int) -> list[dict]:
    """Classify lines into block types based on text content and position."""
    blocks = []
    for line in lines:
        block_type = classify_line(line["text"])
        # Position-based overrides
        y_center = (line["bbox"]["top_left"][1] + line["bbox"]["bottom_right"][1]) / 2
        y_pct = y_center / image_height if image_height > 0 else 0.5

        if block_type == "text":
            if y_pct < 0.15:
                block_type = "header"
            elif y_pct > 0.80:
                # Near bottom — could be issuer area
                block_type = "issuer"

        blocks.append({
            "type": block_type,
            "text": line["text"],
            "bbox": line["bbox"],
            "line_no": line["line_no"],
        })

    return blocks


def _detect_table_candidates(lines: list[dict]) -> list[dict]:
    """
    Detect lines that likely belong to a table.

    A table candidate is a group of consecutive lines that share y-overlap
    and have numeric content.
    """
    import re

    candidates = []
    current_group: list[dict] = []

    for line in lines:
        text = line["text"]
        has_numeric = bool(re.search(r"\d{2,}", text))

        if has_numeric:
            if current_group and _y_close(current_group[-1]["bbox"], line["bbox"], threshold=8.0):
                current_group.append(line)
            else:
                if len(current_group) >= 2:
                    candidates.append(_build_table_candidate(current_group))
                current_group = [line]
        else:
            if len(current_group) >= 2:
                candidates.append(_build_table_candidate(current_group))
            current_group = []

    if len(current_group) >= 2:
        candidates.append(_build_table_candidate(current_group))

    return candidates


def _y_close(a: dict, b: dict, threshold: float = 8.0) -> bool:
    """Check if two bboxes have y-overlap or are close vertically."""
    a_y_center = (a["top_left"][1] + a["bottom_right"][1]) / 2
    b_y_center = (b["top_left"][1] + b["bottom_right"][1]) / 2
    return abs(a_y_center - b_y_center) <= threshold


def _build_table_candidate(group: list[dict]) -> dict:
    """Build a table candidate dict from a group of lines."""
    all_left = min(l["bbox"]["top_left"][0] for l in group)
    all_top = min(l["bbox"]["top_left"][1] for l in group)
    all_right = max(l["bbox"]["bottom_right"][0] for l in group)
    all_bottom = max(l["bbox"]["bottom_right"][1] for l in group)

    return {
        "header_line_nos": [group[0]["line_no"]],
        "row_line_nos": [l["line_no"] for l in group[1:]],
        "text": "\n".join(l["text"] for l in group),
        "bbox": {"top_left": [all_left, all_top], "bottom_right": [all_right, all_bottom]},
    }
