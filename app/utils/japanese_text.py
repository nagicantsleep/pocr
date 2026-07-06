"""Japanese text utilities for OCR post-processing."""

import re
import unicodedata


# Japanese character ranges (CJK Unified Ideographs, Hiragana, Katakana)
_CJK_RANGES = (
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs
    (0x3400, 0x4DBF),   # CJK Extension A
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x31F0, 0x31FF),   # Katakana Phonetic Extensions
    (0xFF65, 0xFF9F),   # Halfwidth Katakana
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
)


def is_japanese_char(ch: str) -> bool:
    """Check if a character is Japanese (CJK ideograph, hiragana, or katakana)."""
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def has_japanese(text: str) -> bool:
    """Check if text contains any Japanese characters."""
    return any(is_japanese_char(ch) for ch in text)


def classify_line(text: str) -> str:
    """
    Classify a line of text into a block type hint.

    Returns one of: "header", "recipient", "issuer", "totals_candidate",
    "table_candidate", or "text".
    """
    stripped = text.strip()

    # Totals / tax keywords
    totals_keywords = ("合計", "小計", "消費税", "税込", "税抜", "内税", "外税", "源泉", "額")
    if any(kw in stripped for kw in totals_keywords):
        return "totals_candidate"

    # Recipient indicators (can appear at start or end of line)
    recipient_keywords = ("御中", "様", "各位")
    if any(kw in stripped for kw in recipient_keywords) or stripped.endswith("へ"):
        return "recipient"
    # Also match if name + suffix anywhere
    if re.search(r"[株式会社]|(店|所|室|部)$", stripped) and "合計" not in stripped:
        # Could be issuer or just text -- use position-based heuristics later
        pass

    # Registration number pattern (T + 13 digits, or similar)
    if re.search(r"T\d{13}", stripped):
        return "issuer"
    # Invoice number pattern
    if re.search(r"(請求書|Invoice|invoice)\s*(番号|#|No\.?)", stripped, re.IGNORECASE):
        return "header"

    return "text"


def _x_overlap(a: dict, b: dict) -> float:
    """Calculate x-overlap between two bboxes. Returns overlap in px, 0 if none."""
    a_left = a["top_left"][0]
    a_right = a["bottom_right"][0]
    b_left = b["top_left"][0]
    b_right = b["bottom_right"][0]
    overlap_start = max(a_left, b_left)
    overlap_end = min(a_right, b_right)
    return max(0.0, overlap_end - overlap_start)


def _x_gap(a: dict, b: dict) -> float:
    """Calculate x-gap between two bboxes. Positive = gap, negative = overlap."""
    a_right = a["bottom_right"][0]
    b_left = b["top_left"][0]
    return b_left - a_right


def merge_fragments(lines: list[dict], x_gap_threshold: float = 20.0) -> list[dict]:
    """
    Merge fragmented lines that belong to the same visual line.

    Two lines are merged if they share y-overlap and the x-gap between them
    is less than x_gap_threshold. Within a merged group, lines are sorted
    left-to-right.
    """
    if not lines:
        return []

    # Sort by y-center, then x-left
    def _sort_key(line):
        bbox = line["bbox"]
        y_center = (bbox["top_left"][1] + bbox["bottom_right"][1]) / 2
        return (y_center, bbox["top_left"][0])

    sorted_lines = sorted(lines, key=_sort_key)

    merged: list[dict] = []
    current_group: list[dict] = [sorted_lines[0]]

    for line in sorted_lines[1:]:
        prev = current_group[-1]
        prev_bbox = prev["bbox"]
        cur_bbox = line["bbox"]

        # Check y-overlap
        prev_y_top = prev_bbox["top_left"][1]
        prev_y_bot = prev_bbox["bottom_right"][1]
        cur_y_top = cur_bbox["top_left"][1]
        cur_y_bot = cur_bbox["bottom_right"][1]

        y_overlap = (
            min(prev_y_bot, cur_y_bot) - max(prev_y_top, cur_y_top)
        )

        # Lines are on the same row if they have y-overlap or are very close
        prev_height = prev_y_bot - prev_y_top
        cur_height = cur_y_bot - cur_y_top
        avg_height = (prev_height + cur_height) / 2 if (prev_height + cur_height) > 0 else 10.0

        same_row = y_overlap > -avg_height * 0.3  # allow small y-jitter

        if same_row and _x_gap(prev_bbox, cur_bbox) < x_gap_threshold:
            current_group.append(line)
        else:
            merged.append(_merge_group(current_group))
            current_group = [line]

    merged.append(_merge_group(current_group))
    return merged


def _merge_group(group: list[dict]) -> dict:
    """Merge a group of lines into one. Sort left-to-right, concatenate text."""
    if len(group) == 1:
        return {
            "text": group[0]["text"],
            "confidence": group[0]["confidence"],
            "bbox": group[0]["bbox"],
        }

    # Sort left-to-right within group
    group_sorted = sorted(group, key=lambda l: l["bbox"]["top_left"][0])

    text = "".join(g["text"] for g in group_sorted)
    avg_conf = sum(g["confidence"] for g in group_sorted) / len(group_sorted)

    # Union bbox
    all_left = min(g["bbox"]["top_left"][0] for g in group_sorted)
    all_top = min(g["bbox"]["top_left"][1] for g in group_sorted)
    all_right = max(g["bbox"]["bottom_right"][0] for g in group_sorted)
    all_bottom = max(g["bbox"]["bottom_right"][1] for g in group_sorted)

    return {
        "text": text,
        "confidence": round(avg_conf, 4),
        "bbox": {"top_left": [all_left, all_top], "bottom_right": [all_right, all_bottom]},
    }
