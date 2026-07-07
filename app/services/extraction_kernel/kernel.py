"""Schema-driven extraction kernel that replaces hardcoded orchestrators."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.schemas.registry.schema_model import SchemaDefinition
from app.services.extraction_kernel.source_registry import SourceRegistry
from app.services.layout_analyzer import analyze_layout
from app.services.table_reconstructor import reconstruct_table, parse_line_items
from app.services.invoice_confidence import compute_field_confidence

logger = logging.getLogger(__name__)


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
            rows = self._extract_table(table_def, layout, lines, table_candidates)
            tables[table_def.id] = rows

        # 4. Run field validators
        errors, warnings = self._run_validators(schema, fields)

        # 5. Compute confidence
        evidence = self._build_evidence(fields)
        confidence_map = compute_field_confidence(evidence)
        per_field: dict[str, float] = {}
        for fname in fields:
            per_field[fname] = confidence_map.get(fname, 0.0)

        scored = [v for v in per_field.values() if v > 0]
        overall = round(sum(scored) / len(scored), 4) if scored else 0.0

        # 6. needs_review
        needs_review = overall < review_threshold or len(errors) > 0

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
    ) -> list[dict]:
        """Extract table rows using reconstruct_table + parse_line_items."""
        if not table_candidates:
            return []
        try:
            region = table_candidates[0]
            columns: dict = {"columns": []}
            table_result = reconstruct_table(layout, region, columns)
            return [item.model_dump() for item in parse_line_items(table_result)]
        except Exception:
            logger.debug("Table extraction failed for %s", table_def.id, exc_info=True)
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
            result = fields.get(field_def.name)
            if not result:
                continue

            for validator in field_def.validators:
                self._apply_validator(field_def, result, validator, errors, warnings)

            for cf in field_def.cross_field:
                self._apply_cross_field(field_def, result, cf, fields, errors, warnings)

        return errors, warnings

    @staticmethod
    def _apply_validator(
        field_def: Any,
        result: FieldResult,
        validator: Any,
        errors: list[dict],
        warnings: list[dict],
    ) -> None:
        """Apply a single field validator."""
        code = validator.code
        severity = validator.severity
        target = errors if severity == "error" else warnings

        if code == "reg001":
            import re
            if result.value and not re.match(r"^[TＴ]\d{13}$", str(result.value)):
                target.append({
                    "code": code,
                    "field": field_def.name,
                    "severity": severity,
                    "message": f"Invalid registration number format: {result.value}",
                })

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
            ref = fields.get(part)
            if ref is None or ref.value is None:
                all_found = False
                break
            total += float(ref.value)
        if all_found and result.value is not None:
            actual = float(result.value)
            if abs(total - actual) > 5:
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
