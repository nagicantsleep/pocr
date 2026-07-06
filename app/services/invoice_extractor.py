"""Invoice extraction orchestrator.

Pipeline:
  1. Run layout analysis on OCR results.
  2. Extract header/footer fields via rules.
  3. Extract totals and tax breakdown.
  4. Extract table / line items.
  5. Build field evidence.
  6. Validate.
  7. Score confidence.
  8. Compute needs_review.
"""

import logging
import uuid
from typing import Optional

from app.config import get_settings
from app.services.layout_analyzer import analyze_layout
from app.services.invoice_rules import (
    find_registration_number,
    find_total_amount,
    find_tax_amounts,
    find_dates,
    find_invoice_number,
    find_issuer_name,
    find_recipient_name,
)
from app.services.invoice_validator import validate_invoice, validate_line_items
from app.services.invoice_confidence import compute_field_confidence, compute_line_item_confidence
from app.services.invoice_llm_extractor import extract_with_llm, validate_llm_output
from app.services.table_reconstructor import reconstruct_table, parse_line_items
from app.services.column_inference import infer_columns_from_header
from app.services.vendor_matcher import match_vendor
from app.services.duplicate_detector import check_duplicate
from app.schemas.invoice import (
    InvoiceData,
    InvoiceExtractResponse,
    InvoiceValidationResult,
    ValidationIssue,
)

logger = logging.getLogger(__name__)


def extract_invoice(
    ocr_results: list[dict],
    request_id: str | None = None,
    review_threshold: float = 0.85,
) -> InvoiceExtractResponse:
    """
    Main extraction entry point.

    Args:
        ocr_results: Raw OCR results from PaddleOCR.
        request_id: Optional request ID (generated if not provided).
        review_threshold: Confidence threshold below which needs_review=true.

    Returns:
        InvoiceExtractResponse with extracted data or empty invoice.
    """
    if request_id is None:
        request_id = str(uuid.uuid4())

    # 1. Layout analysis
    layout = analyze_layout(ocr_results)
    lines = layout["lines"]
    blocks = layout["blocks"]
    table_candidates = layout["table_candidates"]

    # 2. Extract fields
    plain_text = layout["plain_text"]

    # Registration number
    reg_candidates = find_registration_number(plain_text)
    registration_number = reg_candidates[0]["value"] if reg_candidates else None

    # Total amount
    total_candidates = find_total_amount(lines)
    total_amount = total_candidates[0]["value"] if total_candidates else None

    # Tax amounts by rate
    tax_candidates = find_tax_amounts(lines)
    subtotal_by_tax_rate: dict = {}
    consumption_tax_by_rate: dict = {}

    if tax_candidates.get("8%"):
        consumption_tax_by_rate["8%"] = tax_candidates["8%"][0]["value"]
    if tax_candidates.get("10%"):
        consumption_tax_by_rate["10%"] = tax_candidates["10%"][0]["value"]

    # Dates
    date_candidates = find_dates(lines)
    transaction_date = date_candidates[0]["value"] if date_candidates else None

    # Invoice number
    inv_candidates = find_invoice_number(lines)
    invoice_number = inv_candidates[0]["value"] if inv_candidates else None

    # Issuer
    issuer_candidates = find_issuer_name(lines, blocks)
    issuer_name = issuer_candidates[0]["value"] if issuer_candidates else None

    # Recipient
    recipient_candidates = find_recipient_name(lines)
    recipient_name = recipient_candidates[0]["value"] if recipient_candidates else None

    # 3. Build invoice data
    invoice_data = InvoiceData(
        issuer_name=issuer_name,
        issuer_registration_number=registration_number,
        recipient_name=recipient_name,
        invoice_number=invoice_number,
        transaction_date=transaction_date,
        subtotal_by_tax_rate=subtotal_by_tax_rate or None,
        consumption_tax_by_rate=consumption_tax_by_rate or None,
        total_amount=total_amount,
    )

    # 4. Build field evidence dict for confidence scoring
    evidence: dict[str, dict] = {}

    if registration_number:
        ocr_conf = reg_candidates[0].get("confidence", 0.9) or 0.9
        method = reg_candidates[0].get("method", "isolated")
        evidence["issuer_registration_number"] = {
            "ocr_confidence": ocr_conf,
            "method": method,
        }

    if total_amount:
        ocr_conf = total_candidates[0].get("confidence", 0.9) or 0.9
        evidence["total_amount"] = {
            "ocr_confidence": ocr_conf,
            "has_total_keyword": True,
        }

    if transaction_date:
        ocr_conf = date_candidates[0].get("confidence", 0.9) or 0.9
        has_label = date_candidates[0].get("source_text", "").startswith(
            tuple(["請求日", "発行日", "取引日", "支払期日", "支払期限", "お支払期限", "日付"])
        ) if date_candidates else False
        evidence["transaction_date"] = {
            "ocr_confidence": ocr_conf,
            "has_date_label": has_label,
        }

    if issuer_name:
        ocr_conf = issuer_candidates[0].get("confidence", 0.9) or 0.9
        pos = issuer_candidates[0].get("position", "unknown")
        evidence["issuer_name"] = {
            "ocr_confidence": ocr_conf,
            "near_registration_number": registration_number is not None,
            "position": pos,
        }

    if recipient_name:
        ocr_conf = recipient_candidates[0].get("confidence", 0.9) or 0.9
        evidence["recipient_name"] = {
            "ocr_confidence": ocr_conf,
            "near_onchu": True,
        }

    # 5. Table / line item extraction
    line_items = []
    line_items_status = "not_extracted"
    line_item_issues: list = []

    # Check if layout has table candidates
    if table_candidates:
        try:
            # Use first table candidate for now
            table_region = table_candidates[0]
            # Infer columns from the first header line
            header_lines = [l for l in lines if l["line_no"] in table_region.get("header_line_nos", [])]
            columns = {"columns": []}
            if header_lines:
                inferred = infer_columns_from_header(header_lines[0])
                if inferred:
                    columns = {"columns": inferred}

            table_result = reconstruct_table(layout, table_region, columns)
            line_items = parse_line_items(table_result)

            if line_items:
                line_item_issues = validate_line_items(line_items, invoice_data)
                # Set status based on item count vs expected
                line_items_status = "extracted"
        except Exception:
            logger.exception("Table extraction failed")
            line_items_status = "not_extracted"

    # Attach line items to invoice data
    if line_items:
        invoice_data.line_items = line_items

    # 6. Validate
    validation = validate_invoice(invoice_data)

    # Merge line item issues into validation
    for issue in line_item_issues:
        if issue.severity == "error":
            validation.errors.append(issue)
        else:
            validation.warnings.append(issue)

    if line_item_issues:
        validation.is_valid = validation.is_valid and not any(
            i.severity == "error" for i in line_item_issues
        )

    # 7. Score confidence
    confidence_map = compute_field_confidence(evidence, validation)

    # Add line item confidence to the map
    if line_items:
        li_conf = compute_line_item_confidence(line_items)
        if li_conf > 0:
            confidence_map["line_items"] = li_conf

    # 7b. LLM fallback — attempt when any key field confidence is low
    llm_fields: set[str] = set()
    try:
        low_confidence_fields = [
            k for k, v in confidence_map.items()
            if v < 0.70 and k != "line_items"
        ]
        if low_confidence_fields:
            llm_result = extract_with_llm(
                layout,
                ocr_text="\n".join(l["text"] for l in lines),
                plain_text=plain_text,
            )
            if llm_result and validate_llm_output(llm_result):
                # Merge LLM values into low-confidence fields only
                field_map = {
                    "issuer_name": "issuer_name",
                    "issuer_registration_number": "issuer_registration_number",
                    "recipient_name": "recipient_name",
                    "invoice_number": "invoice_number",
                    "transaction_date": "transaction_date",
                    "payment_due_date": "payment_due_date",
                    "total_amount": "total_amount",
                }
                for llm_key, data_key in field_map.items():
                    if llm_key in low_confidence_fields and llm_result.get(llm_key):
                        setattr(invoice_data, data_key, llm_result[llm_key])
                        llm_fields.add(data_key)

                # Mark LLM-derived fields with needs_review warning
                for field in llm_fields:
                    validation.warnings.append(
                        ValidationIssue(
                            code="llm_fallback_used",
                            severity="warning",
                            message=f"Field '{field}' set by LLM fallback — requires OCR evidence verification",
                            field=field,
                        )
                    )
    except Exception:
        logger.debug("LLM fallback failed, using rule-based output")

    # 8. Vendor matching and duplicate detection (if enabled)
    settings = get_settings()
    vendor_result = None
    duplicate_result = None

    if settings.INVOICE_ENABLE_VENDOR_MATCHING:
        vendor_result = match_vendor(
            issuer_name=invoice_data.issuer_name,
            registration_number=invoice_data.issuer_registration_number,
        )

    if settings.INVOICE_ENABLE_DUPLICATE_CHECK:
        duplicate_result = check_duplicate(invoice_data.model_dump())

    # 9. Determine needs_review
    needs_review = _compute_needs_review(confidence_map, validation, review_threshold)

    # Factor in vendor matching and duplicate detection
    if vendor_result and vendor_result.get("needs_review"):
        needs_review = True
    if duplicate_result and duplicate_result.get("needs_review"):
        needs_review = True

    # Also set needs_review on line items that failed validation
    if line_items:
        item_issue_line_nos = set()
        for issue in line_item_issues:
            if issue.field and issue.field.startswith("line_items["):
                item_issue_line_nos.add(issue.field)
        for item in line_items:
            if f"line_items[{item.line_no}]" in item_issue_line_nos:
                item.needs_review = True

    # OCR summary
    ocr_summary = _build_ocr_summary(ocr_results)

    return InvoiceExtractResponse(
        request_id=request_id,
        status="success",
        document_type="qualified_invoice" if registration_number else None,
        invoice=invoice_data,
        confidence=confidence_map or None,
        line_items_status=line_items_status,
        validation=validation,
        needs_review=needs_review,
        ocr=ocr_summary,
    )


def _compute_needs_review(
    confidence: dict[str, float],
    validation: InvoiceValidationResult,
    threshold: float,
) -> bool:
    """Determine whether the extraction needs human review."""
    if not validation.is_valid:
        return True

    if confidence.get("total_amount", 1.0) < threshold:
        return True

    if confidence.get("issuer_registration_number", 1.0) < threshold:
        return True

    if confidence.get("transaction_date", 1.0) < 0.80:
        return True

    return False


def _build_ocr_summary(ocr_results: list[dict]) -> dict:
    """Build OCR summary from raw results."""
    total_lines = len(ocr_results)
    if total_lines == 0:
        return {"summary": {"total_lines": 0, "avg_confidence": 0.0}}

    avg_conf = sum(
        r.get("confidence", 0) for r in ocr_results
    ) / total_lines

    return {
        "summary": {
            "total_lines": total_lines,
            "avg_confidence": round(avg_conf, 4),
        }
    }
