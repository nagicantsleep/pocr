"""Schema-driven extraction kernel that replaces hardcoded orchestrators."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.registry.schema_model import SchemaDefinition
from app.services.extraction_kernel.source_registry import SourceRegistry
from app.services.layout_analyzer import analyze_layout
from app.services.table_reconstructor import reconstruct_table, parse_line_items
from app.services.invoice_confidence import compute_field_confidence

logger = logging.getLogger(__name__)


_REG_NO_RE = re.compile(r"^[TＴ]\s?\d{13}$")
_VALIDATOR_HANDLERS: dict[str, Any] = {
    "reg001": lambda value: bool(_REG_NO_RE.match(str(value))) if value else True,
}

# Date/number format notation tokens (YYYY, MM, DD, HH, mm, ss)
_FORMAT_TOKEN_RE = re.compile(r"^(YYYY|YY|MM|DD|HH|mm|ss|[-/T :.Z]+)+$")


def _is_format_notation(pattern: str) -> bool:
    """Return True if *pattern* is a date/time format notation (not a regex)."""
    return bool(_FORMAT_TOKEN_RE.match(pattern))


def _match_format_pattern(pattern: str, value: str) -> bool:
    """Validate *value* against a date/time format notation like YYYY-MM-DD."""
    # Build a regex from the format notation
    regex = "^"
    i = 0
    while i < len(pattern):
        if pattern[i:i+4] == "YYYY":
            regex += r"\d{4}"; i += 4
        elif pattern[i:i+2] == "YY":
            regex += r"\d{2}"; i += 2
        elif pattern[i:i+2] in ("MM", "DD", "HH", "mm", "ss"):
            regex += r"\d{2}"; i += 2
        elif pattern[i] in "-/T :.Z":
            regex += re.escape(pattern[i]); i += 1
        else:
            regex += re.escape(pattern[i]); i += 1
    regex += "$"
    return bool(re.match(regex, value))


def register_validator_handler(code: str, handler) -> None:
    """Register a validator handler for a given code."""
    _VALIDATOR_HANDLERS[code] = handler


def unregister_validator_handler(code: str) -> None:
    """Unregister a validator handler."""
    _VALIDATOR_HANDLERS.pop(code, None)


def _resolve_nested_value(path: str, fields: dict[str, FieldResult]) -> float | None:
    """Resolve a dotted field path like 'tax_breakdown.rate_10pct.subtotal' to a numeric value."""
    parts = path.split(".")
    result = fields.get(parts[0])
    if result is None:
        return None

    value = result.value
    for key in parts[1:]:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(key)
        elif hasattr(value, key):
            value = getattr(value, key)
        else:
            return None

    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _table_region_to_dicts(table_region) -> list[dict]:
    """Convert a TableRegion to a list of row dicts for ExtractionResult."""
    rows = []
    for row_cells in table_region.rows:
        row_dict = {}
        for cell in row_cells:
            col_name = cell.col if hasattr(cell, "col") else f"col_{cell.column}"
            row_dict[col_name] = {
                "text": cell.text,
                "confidence": cell.confidence,
                "bbox": cell.bbox,
            }
        rows.append(row_dict)
    return rows


@dataclass
class FieldResult:
    """Result of extracting a single field."""

    value: Any = None
    source_used: str = ""
    candidates: list[dict] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class ExtractionResult:
    """Result of schema-driven extraction."""

    schema_id: str
    document_type: str
    fields: dict[str, FieldResult] = field(default_factory=dict)
    tables: dict[str, list[dict]] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    overall_confidence: float = 0.0
    needs_review: bool = False
    validation_errors: list[dict] = field(default_factory=list)
    validation_warnings: list[dict] = field(default_factory=list)


class ExtractionKernel:
    """Schema-driven extraction kernel.

    Reads field definitions from a SchemaDefinition and dispatches
    extraction to registered source functions via a SourceRegistry.
    """

    def __init__(self, source_registry: SourceRegistry) -> None:
        self._source_registry = source_registry

    def extract(
        self,
        schema: SchemaDefinition,
        ocr_results: list[dict],
        image_bytes: bytes | None = None,
    ) -> ExtractionResult:
        """Run the full extraction pipeline using the schema definition.

        Steps:
          1. Layout analysis (reuse analyze_layout)
          2. For each field: try sources, pick best candidate
          3. For each table: run table extraction
          4. Run field validators from schema
          5. Compute per-field and overall confidence
          6. Determine needs_review
        """
        review_threshold = schema.review_threshold or 0.85

        # 1. Layout analysis
        layout = analyze_layout(ocr_results)
        plain_text: str = layout["plain_text"]
        lines: list[dict] = layout["lines"]
        table_candidates = layout["table_candidates"]

        # 2. Extract each field
        fields: dict[str, FieldResult] = {}
        for field_def in schema.fields:
            fields[field_def.name] = self._extract_field(field_def, plain_text, lines)

        # 3. Extract tables
        tables: dict[str, list[dict]] = {}
        for table_def in schema.tables:
            rows = self._extract_table(table_def, layout, lines, table_candidates, image_bytes)
            tables[table_def.id] = rows

        # 4. Run field validators
        errors, warnings = self._run_validators(schema, fields)

        # 5. Compute confidence
        evidence = self._build_evidence(fields)
        confidence_map = compute_field_confidence(evidence)
        per_field: dict[str, float] = {}
        for fname in fields:
            per_field[fname] = confidence_map.get(fname, 0.0)

        all_scores = list(per_field.values())
        overall = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.0

        # 6. needs_review
        required_fields = {f.name for f in schema.fields if f.required}
        missing_required = [
            n for n in required_fields if fields.get(n) is None or fields[n].value is None
        ]
        needs_review = (
            overall < review_threshold or len(errors) > 0 or len(missing_required) > 0
        )

        return ExtractionResult(
            schema_id=schema.id,
            document_type=schema.document_type,
            fields=fields,
            tables=tables,
            confidence=per_field,
            overall_confidence=overall,
            needs_review=needs_review,
            validation_errors=errors,
            validation_warnings=warnings,
        )

    # -- internal ---------------------------------------------------------------

    def _extract_field(
        self,
        field_def: Any,
        plain_text: str,
        lines: list[dict],
    ) -> FieldResult:
        """Extract a single field by trying each source and picking the best."""
        all_candidates: list[dict] = []

        for source_name in field_def.sources:
            func = self._source_registry.get(source_name)
            if func is None:
                continue
            try:
                input_data = self._resolve_source_input(source_name, plain_text, lines)
                result = func(input_data)
                if isinstance(result, list):
                    for c in result:
                        all_candidates.append({**c, "_source": source_name})
                elif isinstance(result, dict):
                    all_candidates.append({**result, "_source": source_name})
            except Exception:
                logger.debug("Source %s failed for field %s", source_name, field_def.name, exc_info=True)

        if not all_candidates:
            return FieldResult()

        all_candidates.sort(key=lambda c: -(c.get("confidence") or 0.0))
        best = all_candidates[0]

        return FieldResult(
            value=best.get("value"),
            source_used=best.get("_source", ""),
            candidates=all_candidates,
            confidence=best.get("confidence") or 0.0,
        )

    def _resolve_source_input(
        self,
        source_name: str,
        plain_text: str,
        lines: list[dict],
    ) -> str | list[dict]:
        """Determine input for a source based on its registered input_type."""
        if self._source_registry.get_input_type(source_name) == "plain_text":
            return plain_text
        return lines

    def _extract_table(
        self,
        table_def: Any,
        layout: dict,
        lines: list[dict],
        table_candidates: list[dict],
        image_bytes: bytes | None = None,
    ) -> list[dict]:
        """Extract table rows based on the table_def.source setting."""
        if table_def.source == "table_visual" and image_bytes is not None:
            return self._extract_table_visual(table_def, image_bytes, lines)
        # Fallback: text-based extraction
        return self._extract_table_text(table_def, layout, table_candidates)

    def _extract_table_visual(
        self,
        table_def: Any,
        image_bytes: bytes,
        lines: list[dict],
    ) -> list[dict]:
        """Extract table rows using the visual table detector."""
        try:
            from app.services.table_visual.detector import VisualTableDetector
        except ImportError:
            logger.debug("VisualTableDetector not available, skipping visual table extraction")
            return []
        try:
            detector = VisualTableDetector()
            visual_tables = detector.detect(image_bytes, lines, page_no=0)
            if visual_tables:
                return _table_region_to_dicts(visual_tables[0])
        except Exception:
            logger.debug("Visual table detection failed for %s", table_def.id, exc_info=True)
        return []

    @staticmethod
    def _extract_table_text(
        table_def: Any,
        layout: dict,
        table_candidates: list[dict],
    ) -> list[dict]:
        """Extract table rows using text-based reconstruct_table + parse_line_items."""
        if not table_candidates:
            return []
        try:
            region = table_candidates[0]
            columns: dict = {"columns": []}
            table_result = reconstruct_table(layout, region, columns)
            return [item.model_dump() for item in parse_line_items(table_result)]
        except Exception:
            logger.debug("Text table extraction failed for %s", table_def.id, exc_info=True)
            return []

    def _run_validators(
        self,
        schema: SchemaDefinition,
        fields: dict[str, FieldResult],
    ) -> tuple[list[dict], list[dict]]:
        """Run field validators defined in the schema."""
        errors: list[dict] = []
        warnings: list[dict] = []

        for field_def in schema.fields:
            if field_def.required:
                result = fields.get(field_def.name)
                if result is None or result.value is None:
                    errors.append({
                        "code": "required",
                        "field": field_def.name,
                        "severity": "error",
                        "message": f"Required field {field_def.name} is missing",
                    })

        for field_def in schema.fields:
            result = fields.get(field_def.name)
            if not result:
                continue

            for validator in field_def.validators:
                self._apply_validator(field_def, result, validator, errors, warnings)

            for cf in field_def.cross_field:
                self._apply_cross_field(field_def, result, cf, fields, errors, warnings)

            if field_def.pattern and result.value is not None:
                pattern = field_def.pattern
                value_str = str(result.value)
                try:
                    # Detect date/number format notation (e.g. YYYY-MM-DD) vs regex
                    if _is_format_notation(pattern):
                        matched = _match_format_pattern(pattern, value_str)
                    else:
                        matched = bool(re.match(pattern, value_str))
                    if not matched:
                        warnings.append({
                            "code": "pattern_mismatch",
                            "field": field_def.name,
                            "severity": "warning",
                            "message": f"Field {field_def.name} value '{result.value}' does not match pattern {pattern}",
                        })
                except re.error:
                    logger.debug("Invalid regex pattern for %s: %s", field_def.name, pattern)

        return errors, warnings

    @staticmethod
    def _apply_validator(
        field_def: Any,
        result: FieldResult,
        validator: Any,
        errors: list[dict],
        warnings: list[dict],
    ) -> None:
        """Apply a single field validator using the handler registry."""
        code = validator.code
        severity = validator.severity
        target = errors if severity == "error" else warnings

        handler = _VALIDATOR_HANDLERS.get(code)
        if handler is not None:
            if result.value is not None and not handler(result.value):
                target.append({
                    "code": code,
                    "field": field_def.name,
                    "severity": severity,
                    "message": f"Validation {code} failed for {field_def.name}: {result.value}",
                })
        else:
            logger.debug("Unknown validator code: %s (no handler registered)", code)

    @staticmethod
    def _apply_cross_field(
        field_def: Any,
        result: FieldResult,
        cf: dict,
        fields: dict[str, FieldResult],
        errors: list[dict],
        warnings: list[dict],
    ) -> None:
        """Apply a cross-field validator."""
        if "eq" not in cf:
            return
        expr = cf["eq"]
        parts = [p.strip() for p in expr.split("+")]
        total = 0.0
        all_found = True
        for part in parts:
            val = _resolve_nested_value(part, fields)
            if val is None:
                all_found = False
                break
            total += val
        if all_found and result.value is not None:
            actual = float(result.value)
            tolerance = getattr(field_def, "cross_field_tolerance", None) or 5
            if abs(total - actual) > tolerance:
                errors.append({
                    "code": "cross_field_eq",
                    "field": field_def.name,
                    "severity": "error",
                    "message": f"Cross-field check failed: {expr} = {total} != {actual}",
                })

    @staticmethod
    def _build_evidence(fields: dict[str, FieldResult]) -> dict[str, dict]:
        """Build evidence dict for compute_field_confidence."""
        evidence: dict[str, dict] = {}
        for fname, result in fields.items():
            if result.value is None:
                continue
            evidence[fname] = {
                "ocr_confidence": result.confidence,
                "method": result.source_used,
            }
        return evidence
