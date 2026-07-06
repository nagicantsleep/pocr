"""Invoice validation engine.

Rules implemented:
  REG001      Registration number matches ^[TＴ]\\d{13}$
  DATE001     Transaction date parseable
  AMT001      Total amount exists
  AMT002      Subtotal + tax = total within tolerance
  TAX001      8% tax is reasonable
  TAX002      10% tax is reasonable
  RECIPIENT001 Recipient exists for qualified invoice
  LINE001     Sum of line items matches subtotal (stub -- no items yet)
"""

import re
from typing import Optional

from app.schemas.invoice import InvoiceData, InvoiceLineItem, InvoiceValidationResult, ValidationIssue
from app.utils.tax import expected_tax

_REG_NO_PATTERN = re.compile(r"^[TＴ]\d{13}$")
_AMT002_TOLERANCE = 5


def validate_invoice(
    invoice_data: InvoiceData,
    evidence: Optional[dict] = None,
) -> InvoiceValidationResult:
    """Validate extracted invoice data.

    Args:
        invoice_data: Extracted invoice fields.
        evidence: Optional field evidence dict (reserved for future use,
                  e.g. duplicate detection).

    Returns:
        InvoiceValidationResult with is_valid, errors, warnings.
    """
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    _check_reg001(invoice_data, errors)
    _check_date001(invoice_data, errors)
    _check_amt001(invoice_data, errors)
    _check_amt002(invoice_data, warnings)
    _check_tax_rate(invoice_data, "8%", "TAX001", warnings)
    _check_tax_rate(invoice_data, "10%", "TAX002", warnings)
    _check_recipient001(invoice_data, warnings)

    return InvoiceValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------


def _check_reg001(invoice_data: InvoiceData, errors: list[ValidationIssue]) -> None:
    """REG001: Registration number must be present and match format."""
    reg_no = invoice_data.issuer_registration_number
    if reg_no is None:
        errors.append(ValidationIssue(
            code="REG001",
            severity="error",
            message="Registration number not found",
            field="issuer_registration_number",
        ))
    elif not _REG_NO_PATTERN.match(reg_no):
        errors.append(ValidationIssue(
            code="REG001",
            severity="error",
            message=f"Registration number format invalid: {reg_no}",
            field="issuer_registration_number",
        ))


def _check_date001(invoice_data: InvoiceData, errors: list[ValidationIssue]) -> None:
    """DATE001: Transaction date must be present."""
    if invoice_data.transaction_date is None:
        errors.append(ValidationIssue(
            code="DATE001",
            severity="error",
            message="Transaction date not found",
            field="transaction_date",
        ))


def _check_amt001(invoice_data: InvoiceData, errors: list[ValidationIssue]) -> None:
    """AMT001: Total amount must be present."""
    if invoice_data.total_amount is None:
        errors.append(ValidationIssue(
            code="AMT001",
            severity="error",
            message="Total amount not found",
            field="total_amount",
        ))


def _check_amt002(invoice_data: InvoiceData, warnings: list[ValidationIssue]) -> None:
    """AMT002: Subtotal + tax should approximately equal total."""
    total = invoice_data.total_amount
    if total is None:
        return

    subtotal_dict = invoice_data.subtotal_by_tax_rate or {}
    tax_dict = invoice_data.consumption_tax_by_rate or {}

    subtotal_sum = sum(v for v in subtotal_dict.values() if v is not None)
    tax_sum = sum(v for v in tax_dict.values() if v is not None)

    if subtotal_sum > 0 and tax_sum > 0:
        expected_total = subtotal_sum + tax_sum
        diff = abs(expected_total - total)
        if diff > _AMT002_TOLERANCE:
            warnings.append(ValidationIssue(
                code="AMT002",
                severity="warning",
                message=(
                    f"Subtotal ({subtotal_sum}) + tax ({tax_sum}) = {expected_total}, "
                    f"but total is {total} (diff: {diff})"
                ),
                field="total_amount",
            ))


def _check_tax_rate(
    invoice_data: InvoiceData,
    rate_key: str,
    code: str,
    warnings: list[ValidationIssue],
) -> None:
    """TAX001/TAX002: Tax amount for a given rate should be reasonable."""
    subtotal_dict = invoice_data.subtotal_by_tax_rate or {}
    tax_dict = invoice_data.consumption_tax_by_rate or {}

    subtotal = subtotal_dict.get(rate_key)
    tax_amount = tax_dict.get(rate_key)

    if subtotal is not None and tax_amount is not None and subtotal > 0 and tax_amount > 0:
        expected_range = expected_tax(subtotal, rate_key)
        if expected_range:
            if all(abs(tax_amount - exp) > 5 for exp in expected_range):
                warnings.append(ValidationIssue(
                    code=code,
                    severity="warning",
                    message=(
                        f"{rate_key} tax amount {tax_amount} does not match "
                        f"expected range {expected_range} for subtotal {subtotal}"
                    ),
                    field="total_amount",
                ))


def _check_recipient001(invoice_data: InvoiceData, warnings: list[ValidationIssue]) -> None:
    """RECIPIENT001: Qualified invoices should have a recipient."""
    if invoice_data.issuer_registration_number is not None and invoice_data.recipient_name is None:
        warnings.append(ValidationIssue(
            code="RECIPIENT001",
            severity="warning",
            message="Recipient not found for qualified invoice",
            field="recipient_name",
        ))


# ---------------------------------------------------------------------------
# Line item validation rules
# ---------------------------------------------------------------------------

_ITEM001_TOLERANCE = 1  # JPY tolerance for quantity * unit_price vs amount

_VALID_TAX_RATES = {"8%", "10%", "non_taxable", "exempt", "unknown", None}


def validate_line_items(
    line_items: list[InvoiceLineItem],
    invoice_data: Optional[InvoiceData] = None,
) -> list[ValidationIssue]:
    """Validate line items against invoice totals and internal consistency.

    Rules:
      ITEM001: quantity * unit_price approximately equals item amount
      ITEM002: sum of line item amounts approximately equals subtotal by tax rate
      ITEM003: sum of including-tax amounts approximately equals total
      ITEM004: each item has description (warning)
      ITEM005: each item has at least one amount field (warning)
      ITEM006: tax rate is valid enum value
      ITEM007: discount rows may be negative (no error)
      ITEM008: any mismatch sets needs_review=true (handled by caller)
    """
    issues: list[ValidationIssue] = []

    for item in line_items:
        # ITEM001: quantity * unit_price ~ amount
        if item.quantity is not None and item.unit_price is not None and item.amount_excluding_tax is not None:
            expected = item.quantity * item.unit_price
            diff = abs(expected - item.amount_excluding_tax)
            if diff > _ITEM001_TOLERANCE:
                issues.append(ValidationIssue(
                    code="ITEM001",
                    severity="warning",
                    message=(
                        f"Line {item.line_no}: qty({item.quantity}) * "
                        f"unit_price({item.unit_price}) = {expected}, "
                        f"but amount is {item.amount_excluding_tax} (diff: {diff:.0f})"
                    ),
                    field=f"line_items[{item.line_no}]",
                ))

        # ITEM004: missing description
        if not item.description:
            issues.append(ValidationIssue(
                code="ITEM004",
                severity="warning",
                message=f"Line {item.line_no}: missing description",
                field=f"line_items[{item.line_no}]",
            ))

        # ITEM005: at least one amount field
        has_amount = any(v is not None for v in [
            item.amount_excluding_tax, item.amount_including_tax,
            item.unit_price, item.discount,
        ])
        if not has_amount:
            issues.append(ValidationIssue(
                code="ITEM005",
                severity="warning",
                message=f"Line {item.line_no}: no amount fields present",
                field=f"line_items[{item.line_no}]",
            ))

        # ITEM006: tax rate validity
        if item.tax_rate not in _VALID_TAX_RATES:
            issues.append(ValidationIssue(
                code="ITEM006",
                severity="warning",
                message=f"Line {item.line_no}: invalid tax rate '{item.tax_rate}'",
                field=f"line_items[{item.line_no}]",
            ))

    # Cross-item validation requires invoice_data
    if invoice_data is not None:
        # ITEM002: sum of amounts vs subtotal by tax rate
        subtotal_by_rate = invoice_data.subtotal_by_tax_rate or {}
        for rate_key, expected_subtotal in subtotal_by_rate.items():
            if expected_subtotal is None:
                continue
            item_sum = sum(
                i.amount_excluding_tax for i in line_items
                if i.amount_excluding_tax is not None and _tax_rate_matches(i.tax_rate, rate_key)
            )
            if item_sum > 0:
                diff = abs(item_sum - expected_subtotal)
                if diff > _AMT002_TOLERANCE:
                    issues.append(ValidationIssue(
                        code="ITEM002",
                        severity="warning",
                        message=(
                            f"Sum of {rate_key} line amounts ({item_sum}) "
                            f"differs from subtotal ({expected_subtotal}) by {diff}"
                        ),
                        field="subtotal_by_tax_rate",
                    ))

        # ITEM003: sum of including-tax amounts vs total
        total = invoice_data.total_amount
        if total is not None:
            sum_including = sum(
                i.amount_including_tax for i in line_items
                if i.amount_including_tax is not None
            )
            if sum_including > 0:
                diff = abs(sum_including - total)
                if diff > _AMT002_TOLERANCE:
                    issues.append(ValidationIssue(
                        code="ITEM003",
                        severity="warning",
                        message=(
                            f"Sum of line item including-tax amounts ({sum_including}) "
                            f"differs from total ({total}) by {diff}"
                        ),
                        field="total_amount",
                    ))

    return issues


def _tax_rate_matches(item_rate: Optional[str], rate_key: str) -> bool:
    """Check if a line item's tax_rate matches a rate key from subtotal_by_tax_rate."""
    if item_rate is None:
        return False
    # rate_key is like "8%" or "10%"
    return item_rate == rate_key
