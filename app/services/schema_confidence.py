"""Schema-driven confidence scoring for invoice extraction.

Uses SchemaDefinition / FieldDefinition from the registry so scoring is
aware of which fields exist, whether they are required, and what validation
issues apply.
"""

from __future__ import annotations

from typing import Any, Optional

from app.schemas.registry.schema_model import FieldDefinition, SchemaDefinition

# Default weights — same as the original invoice_confidence module
_DEFAULT_WEIGHTS: dict[str, float] = {
    "ocr": 0.50,
    "regex": 0.20,
    "layout": 0.15,
    "validation": 0.15,
}

# Validation severity → confidence penalty
_SEVERITY_PENALTY: dict[str, float] = {
    "error": 0.20,
    "warning": 0.10,
}


class SchemaConfidenceScorer:
    """Confidence scoring driven by schema definitions."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or dict(_DEFAULT_WEIGHTS)

    def score_field(
        self,
        field_def: FieldDefinition,
        evidence: dict,
        validation_issues: list[dict] | None = None,
    ) -> float:
        """Score confidence for a single field.

        Args:
            field_def: Schema definition for the field.
            evidence: Evidence sub-dict for this field (keys like
                      ocr_confidence, method, has_label, position, etc.).
            validation_issues: List of validation issue dicts with at least
                               ``severity`` and optionally ``field``.

        Returns:
            Confidence score clamped to [0.0, 1.0].
        """
        field_name = field_def.name

        # Required field with no evidence → 0.0
        if field_def.required and not evidence:
            return 0.0

        # Optional field with no evidence → skip (return 0.0 for caller to omit)
        if not field_def.required and not evidence:
            return 0.0

        ocr_conf = evidence.get("ocr_confidence", 0.0)
        regex_str = _regex_strength(field_name, evidence)
        layout_pos = _layout_score(field_name, evidence)
        validation_score = self._validation_effect(
            field_name, validation_issues
        )

        raw = (
            ocr_conf * self._weights["ocr"]
            + regex_str * self._weights["regex"]
            + layout_pos * self._weights["layout"]
            + validation_score * self._weights["validation"]
        )

        return max(0.0, min(1.0, round(raw, 4)))

    def score_all(
        self,
        schema: SchemaDefinition,
        evidence: dict,
        validation_issues: list[dict] | None = None,
    ) -> dict[str, float]:
        """Score all fields in a schema.

        Args:
            schema: Schema definition with field list.
            evidence: Dict mapping field name -> evidence sub-dict.
            validation_issues: Optional list of validation issue dicts.

        Returns:
            Dict mapping field name to confidence score.
            Optional fields with no evidence are omitted.
        """
        result: dict[str, float] = {}
        for field_def in schema.fields:
            field_ev = evidence.get(field_def.name, {})
            score = self.score_field(field_def, field_ev, validation_issues)
            # Omit optional fields with no evidence
            if not field_ev and not field_def.required:
                continue
            result[field_def.name] = score
        return result

    def overall_confidence(self, field_scores: dict[str, float]) -> float:
        """Compute overall confidence as average of field scores."""
        if not field_scores:
            return 0.0
        return round(sum(field_scores.values()) / len(field_scores), 4)

    def _validation_effect(
        self,
        field_name: str,
        validation_issues: list[dict] | None,
    ) -> float:
        """Compute the validation component of confidence for a field.

        Severity 'error' → -0.20 penalty, 'warning' → -0.10.
        Baseline is 1.0 (no issues).
        """
        if not validation_issues:
            return 1.0

        penalty = 0.0
        for issue in validation_issues:
            if issue.get("field") == field_name:
                severity = issue.get("severity", "warning")
                penalty += _SEVERITY_PENALTY.get(severity, 0.10)

        return max(0.0, 1.0 - penalty)


# ---------------------------------------------------------------------------
# Signal helpers (shared with original module logic)
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

    return 0.50


def _layout_score(field: str, ev: dict) -> float:
    """Score based on layout position and label proximity."""
    if field == "issuer_registration_number":
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
        pos = ev.get("position", "unknown")
        if pos == "bottom":
            return 0.85
        elif pos == "top":
            return 0.75
        return 0.50

    if field == "recipient_name":
        if ev.get("near_onchu"):
            return 0.90
        return 0.50

    return 0.50
