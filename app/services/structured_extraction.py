import re
from datetime import date
from typing import Any

from app.schemas.responses import (
    OCRMeta,
    OCRResult,
    StructuredInputCostImage,
    StructuredInputCostItem,
    StructuredOCRData,
    StructuredOCRResponse,
    StructuredTax,
)

INPUT_COST_TYPE_MAP = {
    "invoice": 1,
    "delivery slip": 2,
    "sale slip": 3,
    "receipt": 4,
    "other": 5,
}

PAYMENT_METHOD_MAP = {
    "cash": 1,
    "credit": 1,
    "invoice": 3,
    "bank transfer": 3,
    "振込": 3,
    "請求": 3,
    "lease": 7,
    "rental": 5,
}

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})"),
    re.compile(r"(20\d{2})年(\d{1,2})月(\d{1,2})日"),
]

AMOUNT_PATTERN = re.compile(r"([0-9][0-9,]*)")
TAX_RATE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")
QUANTITY_PATTERN = re.compile(r"数量[:：]?\s*([0-9]+(?:\.[0-9]+)?)")
PRICE_PATTERN = re.compile(r"単価[:：]?\s*([0-9][0-9,]*)")
AMOUNT_LABEL_PATTERN = re.compile(r"(?:金額|金額合計|金額税込|amount)[:：]?\s*([0-9][0-9,]*)", re.IGNORECASE)
ITEM_CODE_PATTERN = re.compile(r"([A-Z]{2,}[\-_]?[0-9]{2,})")
VENDOR_CODE_PATTERN = re.compile(r"\bV-[0-9]{3,}\b")
UUID_PATTERN = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")


def build_structured_response(
    raw_result: dict[str, Any],
    raw_ocr_results: list[OCRResult],
    request_id: str,
    image_url: str | None = None,
    presigned_image_url: str | None = None,
) -> StructuredOCRResponse:
    meta = OCRMeta(**raw_result.get("meta", {}))
    lines = [result.text.strip() for result in raw_ocr_results if result.text.strip()]
    data = extract_structured_data(lines, image_url=image_url, presigned_image_url=presigned_image_url)
    return StructuredOCRResponse(
        request_id=request_id,
        status="success",
        meta=meta,
        data=data,
        raw_results=raw_ocr_results,
    )


def extract_structured_data(
    lines: list[str],
    image_url: str | None = None,
    presigned_image_url: str | None = None,
) -> StructuredOCRData:
    title = lines[0] if lines else None
    original_number = _find_first(lines, [r"(?:請求書番号|伝票番号|No\.?|番号)[:：]?\s*(.+)"])
    issue_date = _find_date_after_label(lines, ["発行日", "請求日", "取引日"])
    payment_date = _find_date_after_label(lines, ["支払日", "支払期限", "支払期日"])
    vendor_id = _find_first_regex(lines, UUID_PATTERN)
    vendor_code = _find_first_regex(lines, VENDOR_CODE_PATTERN)
    vendor_name = _find_vendor_name(lines)
    description = _find_first(lines, [r"(?:備考|摘要|説明|請求条件)[:：]?\s*(.+)"])
    total_amount = _find_amount_after_label(lines, ["合計", "総合計", "請求金額", "税込合計"])
    input_cost_type = _detect_input_cost_type(lines)
    payment_method = _detect_payment_method(lines)
    taxes = _extract_taxes(lines, total_amount)
    input_cost_items = _extract_items(lines)
    input_cost_images = []
    if image_url:
        input_cost_images.append(
            StructuredInputCostImage(
                image_url=image_url,
                presigned_image_url=presigned_image_url,
            )
        )

    return StructuredOCRData(
        title=title,
        original_number=original_number,
        input_cost_type=input_cost_type,
        issue_date=issue_date,
        payment_date=payment_date,
        vendor_id=vendor_id,
        vendor_code=vendor_code,
        vendor_name=vendor_name,
        payment_method=payment_method,
        description=description,
        total_amount=total_amount,
        taxes=taxes,
        input_cost_images=input_cost_images,
        input_cost_items=input_cost_items,
    )


def _find_first(lines: list[str], patterns: list[str]) -> str | None:
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
    return None


def _find_first_regex(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0)
    return None


def _find_date_after_label(lines: list[str], labels: list[str]) -> date | None:
    for line in lines:
        if any(label in line for label in labels):
            parsed = _extract_date(line)
            if parsed:
                return parsed
    for line in lines:
        parsed = _extract_date(line)
        if parsed:
            return parsed
    return None


def _extract_date(text: str) -> date | None:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            year, month, day = (int(part) for part in match.groups())
            return date(year, month, day)
    return None


def _find_amount_after_label(lines: list[str], labels: list[str]) -> int | None:
    for line in lines:
        if any(label in line for label in labels):
            amount = _extract_amount(line)
            if amount is not None:
                return amount
    amounts = [_extract_amount(line) for line in lines]
    amounts = [amount for amount in amounts if amount is not None]
    return max(amounts) if amounts else None


def _extract_amount(text: str) -> int | None:
    match = AMOUNT_LABEL_PATTERN.search(text) or AMOUNT_PATTERN.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _detect_input_cost_type(lines: list[str]) -> int:
    combined = " ".join(lines).lower()
    if "請求" in combined or "invoice" in combined:
        return INPUT_COST_TYPE_MAP["invoice"]
    if "納品" in combined:
        return INPUT_COST_TYPE_MAP["delivery slip"]
    if "領収" in combined or "receipt" in combined:
        return INPUT_COST_TYPE_MAP["receipt"]
    return INPUT_COST_TYPE_MAP["other"]


def _detect_payment_method(lines: list[str]) -> int | None:
    combined = " ".join(lines).lower()
    for key, value in PAYMENT_METHOD_MAP.items():
        if key.lower() in combined:
            return value
    return None


def _find_vendor_name(lines: list[str]) -> str | None:
    for line in lines:
        if "株式会社" in line or "有限会社" in line or "合同会社" in line:
            return line.strip()
    return None


def _extract_taxes(lines: list[str], total_amount: int | None) -> list[StructuredTax]:
    taxes: list[StructuredTax] = []
    for line in lines:
        if "税" not in line and "tax" not in line.lower():
            continue
        rate_match = TAX_RATE_PATTERN.search(line)
        amount = _extract_amount(line)
        if rate_match and amount is not None:
            rate = float(rate_match.group(1)) / 100
            taxable_amount = int(round(amount / rate)) if rate else total_amount or 0
            taxes.append(
                StructuredTax(
                    name=line.strip(),
                    tax_rate=rate,
                    taxable_amount=taxable_amount,
                    tax_amount=amount,
                )
            )
    return taxes


def _extract_items(lines: list[str]) -> list[StructuredInputCostItem]:
    items: list[StructuredInputCostItem] = []
    current_date = None
    for line in lines:
        parsed_date = _extract_date(line)
        if parsed_date is not None:
            current_date = parsed_date

        amount = _extract_amount(line)
        if amount is None:
            continue
        if any(keyword in line for keyword in ["合計", "総合計", "請求金額", "税"]):
            continue

        quantity = _extract_float(line, QUANTITY_PATTERN)
        price = _extract_amount_from_pattern(line, PRICE_PATTERN)
        tax_rate = _extract_tax_rate(line)
        item_code = _extract_item_code(line)
        item_name = _extract_item_name(line)
        if not item_name:
            continue
        items.append(
            StructuredInputCostItem(
                transaction_date=current_date,
                item_code=item_code,
                item_name=item_name,
                unit=_extract_unit(line),
                quantity=quantity,
                price=price,
                tax_rate=tax_rate,
                description=None,
                amount=amount,
            )
        )
    return items


def _extract_amount_from_pattern(text: str, pattern: re.Pattern[str]) -> int | None:
    match = pattern.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _extract_float(text: str, pattern: re.Pattern[str]) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    return float(match.group(1))


def _extract_tax_rate(text: str) -> float | None:
    match = TAX_RATE_PATTERN.search(text)
    if not match:
        return None
    return float(match.group(1)) / 100


def _extract_item_code(text: str) -> str | None:
    match = ITEM_CODE_PATTERN.search(text)
    if not match:
        return None
    return match.group(1)


def _extract_item_name(text: str) -> str | None:
    cleaned = re.sub(r"(20\d{2}[-/]\d{1,2}[-/]\d{1,2})", "", text)
    cleaned = re.sub(r"(20\d{2}年\d{1,2}月\d{1,2}日)", "", cleaned)
    cleaned = re.sub(r"数量[:：]?\s*[0-9]+(?:\.[0-9]+)?", "", cleaned)
    cleaned = re.sub(r"単価[:：]?\s*[0-9][0-9,]*", "", cleaned)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", cleaned)
    cleaned = re.sub(r"[0-9][0-9,]*", "", cleaned)
    cleaned = ITEM_CODE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:：")
    return cleaned or None


def _extract_unit(text: str) -> str | None:
    for unit in ["式", "個", "台", "本", "枚", "巻", "箱"]:
        if unit in text:
            return unit
    return None
