"""Optional LLM/VLM fallback for invoice extraction.

Used when rule-based confidence is low. Disabled by default via
INVOICE_ENABLE_LLM_EXTRACTOR. Falls back gracefully to rule-based
output on any provider failure.
"""

import json
import re
import httpx

from app.config import get_settings
from app.schemas.invoice import InvoiceData

PROVIDER_ENDPOINTS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
}

EXTRACTION_PROMPT = """Extract Japanese invoice fields from the following OCR text.
Return ONLY valid JSON matching this schema:
{{
    "issuer_name": string|null,
    "issuer_registration_number": "T13digits"|null,
    "recipient_name": string|null,
    "invoice_number": string|null,
    "transaction_date": "YYYY-MM-DD"|null,
    "payment_due_date": "YYYY-MM-DD"|null,
    "total_amount": number|null,
    "tax_by_rate": {{"8%": number|null, "10%": number|null}},
    "line_items": [
        {{
            "description": string,
            "quantity": number|null,
            "unit": string|null,
            "unit_price": number|null,
            "tax_rate": "8%"|"10%"|"non_taxable"|null,
            "amount_excluding_tax": number|null
        }}
    ]
}}

Rules:
- Return null for fields you cannot find with confidence
- Do NOT guess registration numbers — only return if clearly visible
- Do NOT invent line items — return empty array if no table visible
- Registration number MUST match format T followed by 13 digits

OCR text:
{ocr_text}

Plain text:
{plain_text}
"""

_REG_NO_RE = re.compile(r"^T\d{13}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def extract_with_llm(
    layout_doc: dict,
    ocr_text: str = "",
    plain_text: str = "",
) -> dict | None:
    """Attempt extraction using LLM provider.

    Returns parsed dict matching InvoiceData fields, or None on failure.
    """
    settings = get_settings()
    if not settings.INVOICE_ENABLE_LLM_EXTRACTOR:
        return None
    if not settings.INVOICE_LLM_PROVIDER or not settings.INVOICE_LLM_MODEL:
        return None

    provider = settings.INVOICE_LLM_PROVIDER.lower()
    endpoint = PROVIDER_ENDPOINTS.get(provider)
    if not endpoint:
        return None

    api_key = settings.STANDARDIZER_API_KEY
    if not api_key:
        return None

    prompt = EXTRACTION_PROMPT.format(
        ocr_text=ocr_text or "",
        plain_text=plain_text or str(layout_doc.get("plain_text", "")),
    )

    payload = {
        "model": settings.INVOICE_LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Japanese invoice data extractor. "
                    "Return only valid JSON. Do not guess uncertain fields."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    # Extract content from chat completion response
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None

    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        content = "".join(parts)

    if not isinstance(content, str) or not content.strip():
        return None

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        return None

    return result if isinstance(result, dict) else None


def validate_llm_output(output: dict) -> bool:
    """Validate that LLM output matches expected schema constraints."""
    # Registration number format
    reg = output.get("issuer_registration_number")
    if reg is not None and not _REG_NO_RE.match(str(reg)):
        return False

    # Dates parseable
    for date_field in ("transaction_date", "payment_due_date"):
        val = output.get(date_field)
        if val is not None and not _DATE_RE.match(str(val)):
            return False

    # Total amount numeric
    total = output.get("total_amount")
    if total is not None and not isinstance(total, (int, float)):
        return False

    # Line items must be a list, each with at least description
    items = output.get("line_items")
    if items is not None:
        if not isinstance(items, list):
            return False
        for item in items:
            if not isinstance(item, dict):
                return False
            if not item.get("description"):
                return False

    return True
