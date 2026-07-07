"""Schema-driven validator for invoice extraction.

Uses SchemaDefinition / FieldDefinition from the registry to determine
which validation rules to run.  Validation functions are registered by code
so the YAML validator list drives execution.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from app.schemas.invoice import ValidationIssue
from app.schemas.registry.schema_model import FieldDefinition, SchemaDefinition
from app.utils.tax import expected_tax

_REG_NO_PATTERN = re.compile(r"^[TＴ]\d{13}$")
_AMT002_TOLERANCE = 5


class SchemaValidator:
    """Validator driven by schema field definitions."""

    _validators: dict[str, Callable[..., list[ValidationIssue]]] = {}

    @classmethod
    def register(cls, code: str, func: Callable[..., list[ValidationIssue]]) -> None:
        """Register a validation function for a code."""
        cls._validators[code] = func

    def validate_field(
        self, field_def: FieldDefinition, value: Any
    ) -> list[ValidationIssue]:
        """Validate a single field value against its schema validators."""
        issues: list[ValidationIssue] = []
        for validator in field_def.validators:
            func = self._validators.get(validator.code)
            if func is None:
                continue
            result = func(
                field_name=field_def.name,
                value=value,
                severity=validator.severity,
            )
            issues.extend(result)
        return issues

    def validate_cross_field(
        self, schema: SchemaDefinition, extracted: dict
    ) -> list[ValidationIssue]:
        """Validate cross-field constraints from schema."""
        issues: list[ValidationIssue] = []
        for field_def in schema.fields:
            for constraint in field_def.cross_field:
                eq_expr = constraint.get("eq")
                if eq_expr is None:
                    continue
                result = _evaluate_eq_constraint(
                    field_name=field_def.name,
                    eq_expr=eq_expr,
                    extracted=extracted,
                )
                issues.extend(result)
        return issues

    def validate_all(
        self, schema: SchemaDefinition, extracted: dict
    ) -> list[ValidationIssue]:
        """Run all field + cross-field validations."""
        issues: list[ValidationIssue] = []
        for field_def in schema.fields:
            value = extracted.get(field_def.name)
            issues.extend(self.validate_field(field_def, value))
        issues.extend(self.validate_cross_field(schema, extracted))
        return issues


# ---------------------------------------------------------------------------
# Built-in validator registrations
# ---------------------------------------------------------------------------


def _validate_reg001(
    field_name: str, value: Any, severity: str
) -> list[ValidationIssue]:
    """REG001: Registration number must match ^[TＴ]\\d{13}$."""
    if value is None:
        return [
            ValidationIssue(
                code="reg001",
                severity=severity,
                message="Registration number not found",
                field=field_name,
            )
        ]
    if not _REG_NO_PATTERN.match(str(value)):
        return [
            ValidationIssue(
                code="reg001",
                severity=severity,
                message=f"Registration number format invalid: {value}",
                field=field_name,
            )
        ]
    return []


def _validate_date001(
    field_name: str, value: Any, severity: str
) -> list[ValidationIssue]:
    """DATE001: Transaction date must be present and parseable."""
    if value is None:
        return [
            ValidationIssue(
                code="date001",
                severity=severity,
                message="Transaction date not found",
                field=field_name,
            )
        ]
    return []


def _validate_amt001(
    field_name: str, value: Any, severity: str
) -> list[ValidationIssue]:
    """AMT001: Total amount must exist and be > 0."""
    if value is None or value == 0:
        return [
            ValidationIssue(
                code="amt001",
                severity=severity,
                message="Total amount not found or zero",
                field=field_name,
            )
        ]
    return []


def _validate_tax001(
    field_name: str, value: Any, severity: str
) -> list[ValidationIssue]:
    """TAX001: 8% tax amount should be reasonable.

    Expects the extracted dict to be passed as the ``value`` so it can
    look up subtotal/tax breakdowns.  This is a no-op when the relevant
    data is absent.
    """
    if not isinstance(value, dict):
        return []
    subtotal = value.get("subtotal_8pct")
    tax_amount = value.get("tax_8pct")
    if subtotal is None or tax_amount is None or subtotal == 0 or tax_amount == 0:
        return []
    expected_range = expected_tax(subtotal, "8%")
    if expected_range and all(abs(tax_amount - exp) > 5 for exp in expected_range):
        return [
            ValidationIssue(
                code="tax001",
                severity=severity,
                message=(
                    f"8% tax amount {tax_amount} does not match "
                    f"expected range {expected_range} for subtotal {subtotal}"
                ),
                field=field_name,
            )
        ]
    return []


def _validate_tax002(
    field_name: str, value: Any, severity: str
) -> list[ValidationIssue]:
    """TAX002: 10% tax amount should be reasonable."""
    if not isinstance(value, dict):
        return []
    subtotal = value.get("subtotal_10pct")
    tax_amount = value.get("tax_10pct")
    if subtotal is None or tax_amount is None or subtotal == 0 or tax_amount == 0:
        return []
    expected_range = expected_tax(subtotal, "10%")
    if expected_range and all(abs(tax_amount - exp) > 5 for exp in expected_range):
        return [
            ValidationIssue(
                code="tax002",
                severity=severity,
                message=(
                    f"10% tax amount {tax_amount} does not match "
                    f"expected range {expected_range} for subtotal {subtotal}"
                ),
                field=field_name,
            )
        ]
    return []


# Register all built-in validators
SchemaValidator.register("reg001", _validate_reg001)
SchemaValidator.register("date001", _validate_date001)
SchemaValidator.register("amt001", _validate_amt001)
SchemaValidator.register("tax001", _validate_tax001)
SchemaValidator.register("tax002", _validate_tax002)


# ---------------------------------------------------------------------------
# Cross-field helpers
# ---------------------------------------------------------------------------


def _evaluate_eq_constraint(
    field_name: str,
    eq_expr: str,
    extracted: dict,
) -> list[ValidationIssue]:
    """Evaluate an ``eq`` cross-field constraint.

    Format: ``term1 + term2 + ...`` where each term is a key in *extracted*.
    The sum of all terms is compared to the value of *field_name* in *extracted*.
    """
    total = extracted.get(field_name)
    if total is None:
        return []

    terms = [t.strip() for t in eq_expr.split("+")]
    term_sum = 0
    all_present = True
    for term in terms:
        val = extracted.get(term)
        if val is None:
            all_present = False
            break
        term_sum += val

    if not all_present:
        return []

    diff = abs(term_sum - total)
    if diff > _AMT002_TOLERANCE:
        return [
            ValidationIssue(
                code="amt002",
                severity="warning",
                message=(
                    f"Cross-field: {eq_expr} = {term_sum}, "
                    f"but {field_name} is {total} (diff: {diff})"
                ),
                field=field_name,
            )
        ]
    return []
