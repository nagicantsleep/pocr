"""Field-level confidence scoring for invoice extraction.

Formula per field:
  confidence = OCR_confidence * weight_ocr
             + regex_strength * weight_regex
             + layout_position * weight_layout
             + validation * weight_validation

Default weights: OCR 0.50, regex 0.20, layout 0.15, validation 0.15

Field-specific signals are computed based on evidence dict keys.
"""

from typing import Optional

from app.schemas.invoice import InvoiceLineItem, InvoiceValidationResult

# Weight constants
_W_OCR = 0.50
_W_REGEX = 0.20
_W_LAYOUT = 0.15
_W_VALIDATION = 0.15


def compute_field_confidence(
    evidence: dict,
    validation: Optional[InvoiceValidationResult] = None,
) -> dict[str, float]:
    """Compute confidence score for each extracted field.

    Args:
        evidence: Dict mapping field name -> evidence sub-dict with keys:
            - ocr_confidence: float (0.0-1.0)
            - method: str ("labeled" | "isolated")
            - has_label: bool
            - position: str ("top" | "bottom")
            - line_count: int
            - (other field-specific signals)
        validation: Optional InvoiceValidationResult used to adjust scores.

    Returns:
        Dict mapping field name to float confidence score (0.0-1.0).
        Fields with no evidence are omitted.
    """
    result: dict[str, float] = {}

    for field_name, field_ev in evidence.items():
        score = _score_field(field_name, field_ev, validation)
        result[field_name] = round(score, 4)

    return result


# ---------------------------------------------------------------------------
# Scoring core
# ---------------------------------------------------------------------------


def _score_field(
    field_name: str,
    ev: dict,
    validation: Optional[InvoiceValidationResult],
) -> float:
    """Compute a single field's confidence."""
    ocr_conf = ev.get("ocr_confidence", 0.0)

    regex_str = _regex_strength(field_name, ev)
    layout_pos = _layout_score(field_name, ev)
    validation_score = _validation_effect(field_name, validation)

    raw = (
        ocr_conf * _W_OCR
        + regex_str * _W_REGEX
        + layout_pos * _W_LAYOUT
        + validation_score * _W_VALIDATION
    )

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, raw))


# ---------------------------------------------------------------------------
# Signal components per field
# ---------------------------------------------------------------------------


def _regex_strength(field: str, ev: dict) -> float:
    """Score how strong the regex/extraction method was."""
    method = ev.get("method", "isolated")

    if field == "issuer_registration_number":
        if method == "labeled":
            return 0.95
        elif method == "isolated":
            return 0.80
        return 0.50

    if field == "total_amount":
        # Near a known total keyword
        if ev.get("has_total_keyword"):
            return 0.90
        return 0.60

    if field == "transaction_date":
        if ev.get("has_date_label"):
            return 0.90
        return 0.60

    if field == "issuer_name":
        if ev.get("near_registration_number"):
            return 0.85
        return 0.70

    if field == "recipient_name":
        if ev.get("near_onchu"):
            return 0.90
        return 0.60

    # Fallback for unknown fields
    return 0.50


def _layout_score(field: str, ev: dict) -> float:
    """Score based on layout position and label proximity."""
    if field == "issuer_registration_number":
        # High if near a label
        if ev.get("method") == "labeled":
            return 0.90
        return 0.70

    if field == "total_amount":
        if ev.get("has_total_keyword"):
            return 0.90
        return 0.60

    if field == "transaction_date":
        if ev.get("has_date_label"):
            return 0.90
        return 0.60

    if field == "issuer_name":
        # In issuer block or header -> medium-high
        pos = ev.get("position", "unknown")
        if pos == "bottom":
            return 0.85  # issuer block
        elif pos == "top":
            return 0.75
        return 0.50

    if field == "recipient_name":
        if ev.get("near_onchu"):
            return 0.90
        return 0.50

    return 0.50


def _validation_effect(
    field: str,
    validation: Optional[InvoiceValidationResult],
) -> float:
    """Validation effect: 1.0 if no error/warning for this field, lower otherwise."""
    if validation is None:
        return 0.50  # neutral when no validation available

    # Check for errors targeting this field
    for issue in validation.errors:
        if issue.field == field:
            return 0.0  # error -> zero confidence contribution

    # Check for warnings targeting this field
    for issue in validation.warnings:
        if issue.field == field:
            return 0.50  # warning -> half contribution

    return 1.0


# ---------------------------------------------------------------------------
# Line item confidence scoring
# ---------------------------------------------------------------------------

# Weights for line item confidence components
_W_CELL_OCR = 0.35
_W_COLUMN_ASSIGN = 0.20
_W_ROW_GROUPING = 0.15
_W_AMOUNT_PARSE = 0.15
_W_VALIDATION_LI = 0.15


def compute_line_item_confidence(line_items: list[InvoiceLineItem]) -> float:
    """Compute aggregate confidence for all line items.

    Per item:
      line_item_confidence = OCR cell confidence * 0.35
                           + column assignment confidence * 0.20
                           + row grouping confidence * 0.15
                           + amount parse confidence * 0.15
                           + validation confidence * 0.15

    Returns average across all items, or 0.0 if no items.
    """
    if not line_items:
        return 0.0

    total = 0.0
    for item in line_items:
        # OCR cell confidence: from source_cells
        cell_conf = _avg_cell_confidence(item)

        # Column assignment confidence: average of cell-level assignment conf
        col_assignment_conf = _column_assignment_confidence(item)

        # Row grouping confidence: based on having reasonable cell positions
        row_group_conf = _row_grouping_confidence(item)

        # Amount parse confidence: whether amounts parsed without issues
        amount_parse_conf = _amount_parse_confidence(item)

        # Validation confidence: based on needs_review flag
        validation_conf = 0.0 if item.needs_review else 1.0

        item_conf = (
            cell_conf * _W_CELL_OCR
            + col_assignment_conf * _W_COLUMN_ASSIGN
            + row_group_conf * _W_ROW_GROUPING
            + amount_parse_conf * _W_AMOUNT_PARSE
            + validation_conf * _W_VALIDATION_LI
        )

        total += max(0.0, min(1.0, item_conf))

    return round(total / len(line_items), 4)


def _avg_cell_confidence(item: InvoiceLineItem) -> float:
    """Average confidence from source_cells."""
    cells = item.source_cells or {}
    confs = [
        c.get("confidence", 1.0)
        for c in cells.values()
        if isinstance(c, dict) and "confidence" in c
    ]
    if not confs:
        return 0.5
    return sum(confs) / len(confs)


def _column_assignment_confidence(item: InvoiceLineItem) -> float:
    """Confidence in column assignment from cell values."""
    cells = item.source_cells or {}
    assigned = [c for c in cells.values() if isinstance(c, dict) and c.get("confidence", 0) > 0]
    if not assigned:
        return 0.0
    return 1.0


def _row_grouping_confidence(item: InvoiceLineItem) -> float:
    """Confidence in row grouping based on having well-structured cells."""
    cells = item.source_cells or {}
    # At least description and one amount field suggests good grouping
    has_desc = "description" in cells
    has_amount = any(k in cells for k in ("amount", "quantity", "unit_price"))
    if has_desc and has_amount:
        return 1.0
    return 0.5


def _amount_parse_confidence(item: InvoiceLineItem) -> float:
    """Confidence that amounts were parsed correctly."""
    # If we have valid parsed amounts, high confidence
    has_amount = item.amount_excluding_tax is not None or item.amount_including_tax is not None
    has_unit_price = item.unit_price is not None
    if has_amount or has_unit_price:
        return 1.0
    # If we have source cells but couldn't parse, lower confidence
    cells = item.source_cells or {}
    if cells:
        return 0.3
    return 0.0
