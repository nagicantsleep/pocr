import json
import re
import urllib.error
import urllib.request
from datetime import date
from typing import Any, Protocol

from app.config import get_settings
from app.schemas.responses import (
    OCRMeta,
    OCRResult,
    StructuredInputCostItem,
    StructuredOCRData,
    StructuredOCRResponse,
    StructuredTax,
)

INPUT_COST_TYPE_MAP = {
    "invoice": "1. invoice",
    "delivery slip": "2. delivery slip",
    "sale slip": "3. sale slip",
    "receipt": "4. receipt",
    "other": "5. other",
}

PAYMENT_METHOD_MAP = {
    "cash": "1. Purchase (Cash/Credit Card - One-time)",
    "credit": "1. Purchase (Cash/Credit Card - One-time)",
    "invoice": "3. Purchase (Invoice - One-time)",
    "bank transfer": "3. Purchase (Invoice - One-time)",
    "振込": "3. Purchase (Invoice - One-time)",
    "請求": "3. Purchase (Invoice - One-time)",
    "lease": "7. Lease (Invoice)",
    "rental": "5. Rental (Invoice)",
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
HEADER_LABEL_PATTERN = re.compile(r"(?:請求書番号|伝票番号|No\.?|番号|請求日|発行日|支払期日|支払期限|請求条件)[:：]?", re.IGNORECASE)
ITEM_CODE_PATTERN = re.compile(r"([A-Z]{2,}[\-_]?[0-9]{2,})")
VENDOR_CODE_PATTERN = re.compile(r"\bV-[0-9]{3,}\b")
UUID_PATTERN = re.compile(  r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

class StandardizerError(RuntimeError):
    """Raised when structured standardization fails."""


class StructuredStandardizer(Protocol):
    def standardize(self, raw_ocr_results: list[OCRResult]) -> StructuredOCRData:
        """Convert OCR evidence into the downstream structured schema."""


class HeuristicStandardizer:
    def standardize(self, raw_ocr_results: list[OCRResult]) -> StructuredOCRData:
        lines = [result.text.strip() for result in raw_ocr_results if result.text.strip()]
        return extract_structured_data(lines)


class OpenAICompatibleStandardizer:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        site_url: str | None = None,
        app_name: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.site_url = site_url
        self.app_name = app_name

    def standardize(self, raw_ocr_results: list[OCRResult]) -> StructuredOCRData:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": _standardizer_system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "schema_name": "StructuredOCRData",
                            "ocr_evidence": [
                                result.model_dump(by_alias=True, mode="json")
                                for result in raw_ocr_results
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_ocr_data",
                    "strict": False,
                    "schema": StructuredOCRData.model_json_schema(by_alias=True),
                },
            },
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.app_name:
            headers["X-Title"] = self.app_name

        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise StandardizerError(f"standardizer_http_error: {e.code} {detail}") from e
        except Exception as e:
            raise StandardizerError(f"standardizer_failed: {e}") from e

        return StructuredOCRData.model_validate(_extract_chat_completion_json(response_data))


class OpenAIResponsesStandardizer:
    def __init__(self, api_key: str, model: str, base_url: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def standardize(self, raw_ocr_results: list[OCRResult]) -> StructuredOCRData:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": _standardizer_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "schema_name": "StructuredOCRData",
                            "ocr_evidence": [
                                result.model_dump(by_alias=True, mode="json")
                                for result in raw_ocr_results
                            ],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "structured_ocr_data",
                    "strict": False,
                    "schema": StructuredOCRData.model_json_schema(by_alias=True),
                }
            },
        }
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise StandardizerError(f"standardizer_http_error: {e.code} {detail}") from e
        except Exception as e:
            raise StandardizerError(f"standardizer_failed: {e}") from e

        return StructuredOCRData.model_validate(_extract_response_json(response_data))


def get_standardizer() -> StructuredStandardizer:
    settings = get_settings()
    provider = settings.STANDARDIZER_PROVIDER.strip().lower()
    if provider in ("", "heuristic", "mock", "none"):
        return HeuristicStandardizer()
    if provider in ("openrouter", "openai-compatible", "chat-completions"):
        api_key = settings.STANDARDIZER_API_KEY
        if not api_key:
            raise StandardizerError(
                f"STANDARDIZER_API_KEY is required when STANDARDIZER_PROVIDER={settings.STANDARDIZER_PROVIDER}"
            )
        return OpenAICompatibleStandardizer(
            api_key=api_key,
            model=settings.STANDARDIZER_MODEL,
            base_url=settings.STANDARDIZER_BASE_URL,
            site_url=settings.STANDARDIZER_SITE_URL,
            app_name=settings.STANDARDIZER_APP_NAME,
        )
    if provider in ("openai", "responses"):
        api_key = settings.STANDARDIZER_API_KEY
        if not api_key:
            raise StandardizerError("STANDARDIZER_API_KEY is required when STANDARDIZER_PROVIDER=openai")
        return OpenAIResponsesStandardizer(
            api_key=api_key,
            model=settings.STANDARDIZER_MODEL,
            base_url=settings.STANDARDIZER_BASE_URL,
        )
    raise StandardizerError(f"unsupported standardizer provider: {settings.STANDARDIZER_PROVIDER}")


def _standardizer_system_prompt() -> str:
    return (
        "Convert OCR evidence into the StructuredOCRData JSON schema. "
        "Use only information present in the OCR text or its layout evidence. "
        "Do not infer internal IDs or missing business facts. "
        "If a field is not present in the image evidence, return null for scalar fields "
        "and [] for arrays. Return JSON only."
    )


def _extract_response_json(response_data: dict[str, Any]) -> dict[str, Any]:
    output_text = response_data.get("output_text")
    if output_text:
        return json.loads(output_text)

    for item in response_data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                return json.loads(content.get("text", "{}"))

    raise StandardizerError("standardizer returned no JSON text")


def _extract_chat_completion_json(response_data: dict[str, Any]) -> dict[str, Any]:
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise StandardizerError("standardizer returned no chat completion content") from e
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict) and "text" in part:
                text_parts.append(part["text"])
        content = "".join(text_parts)
    if not isinstance(content, str) or not content.strip():
        raise StandardizerError("standardizer returned empty chat completion content")
    return json.loads(content)


def build_structured_response(
    raw_result: dict[str, Any],
    raw_ocr_results: list[OCRResult],
    request_id: str,
    image_url: str | None = None,
    presigned_image_url: str | None = None,
) -> StructuredOCRResponse:
    meta = OCRMeta(**raw_result.get("meta", {}))
    data = get_standardizer().standardize(raw_ocr_results)
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
    vendor_name = _find_vendor_name(lines)
    description = _find_first(lines, [r"(?:備考|摘要|説明|請求条件)[:：]?\s*(.+)"])
    total_amount = _find_amount_after_label(lines, ["合計", "総合計", "請求金額", "税込合計"])
    input_cost_type = _detect_input_cost_type(lines)
    payment_method = _detect_payment_method(lines)
    taxes = _extract_taxes(lines, total_amount)
    input_cost_items = _extract_items(lines)
    return StructuredOCRData(
        title=title,
        original_number=original_number,
        input_cost_type=input_cost_type,
        issue_date=issue_date,
        payment_date=payment_date,
        vendor_name=vendor_name,
        payment_method=payment_method,
        description=description,
        total_amount=total_amount,
        taxes=taxes,
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


def _detect_input_cost_type(lines: list[str]) -> str:
    combined = " ".join(lines).lower()
    if "請求" in combined or "invoice" in combined:
        return INPUT_COST_TYPE_MAP["invoice"]
    if "納品" in combined:
        return INPUT_COST_TYPE_MAP["delivery slip"]
    if "領収" in combined or "receipt" in combined:
        return INPUT_COST_TYPE_MAP["receipt"]
    return INPUT_COST_TYPE_MAP["other"]


def _detect_payment_method(lines: list[str]) -> str | None:
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
        amount = _extract_amount_after_rate(line) or _extract_amount(line)
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
        if HEADER_LABEL_PATTERN.search(line):
            continue
        if not any(keyword in line for keyword in ["数量", "単価", "金額"]):
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

def _extract_amount_after_rate(text: str) -> int | None:
    rate_match = TAX_RATE_PATTERN.search(text)
    if not rate_match:
        return None
    amounts = AMOUNT_PATTERN.findall(text[rate_match.end():])
    if not amounts:
        return None
    return int(amounts[-1].replace(",", ""))


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
    cleaned = ITEM_CODE_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"数量[:：]?\s*[0-9]+(?:\.[0-9]+)?", "", cleaned)
    cleaned = re.sub(r"単価[:：]?\s*[0-9][0-9,]*", "", cleaned)
    cleaned = re.sub(r"金額[:：]?\s*[0-9][0-9,]*", "", cleaned)
    cleaned = re.sub(r"\d+(?:\.\d+)?\s*%", "", cleaned)
    cleaned = re.sub(r"[0-9][0-9,]*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:：")
    return cleaned or None


def _extract_unit(text: str) -> str | None:
    for unit in ["式", "個", "台", "本", "枚", "巻", "箱"]:
        if unit in text:
            return unit
    return None
