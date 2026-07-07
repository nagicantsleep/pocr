from __future__ import annotations

import re

# Registration number pattern: T followed by 13 digits
_REG_NUM_RE = re.compile(r"T\d{13}")
# Japanese era dates (令和, 平成, 昭和)
_JP_ERA_RE = re.compile(r"(令和|平成|昭和)\s*\d+\s*年")


def classify_document(
    ocr_text: str, locale_hint: str | None = None
) -> tuple[str, float]:
    """Classify a document from its OCR text.

    Returns (document_type, confidence).

    Supported types: ``qualified_invoice``, ``receipt``, ``unknown``
    """
    if not ocr_text:
        return ("unknown", 0.30)

    qi_score = 0.0
    receipt_score = 0.0

    # --- Qualified Invoice signals ---
    if "適格請求書" in ocr_text:
        qi_score = max(qi_score, 0.95)
    if "インボイス" in ocr_text:
        qi_score = max(qi_score, 0.95)
    if _REG_NUM_RE.search(ocr_text):
        qi_score = max(qi_score, 0.90)

    # --- Receipt signals ---
    if "領収書" in ocr_text:
        receipt_score = max(receipt_score, 0.90)
    if "レシート" in ocr_text:
        receipt_score = max(receipt_score, 0.90)

    # --- Japanese era date boost ---
    has_jp_date = bool(_JP_ERA_RE.search(ocr_text))
    if has_jp_date:
        if qi_score > 0:
            qi_score = min(qi_score + 0.03, 1.0)
        if receipt_score > 0:
            receipt_score = min(receipt_score + 0.03, 1.0)

    # Locale hint nudge
    if locale_hint and "ja" in locale_hint.lower():
        if qi_score > 0:
            qi_score = min(qi_score + 0.02, 1.0)
        if receipt_score > 0:
            receipt_score = min(receipt_score + 0.02, 1.0)

    # --- Pick winner ---
    if qi_score > receipt_score and qi_score >= 0.80:
        return ("qualified_invoice", round(qi_score, 2))
    if receipt_score > qi_score and receipt_score >= 0.80:
        return ("receipt", round(receipt_score, 2))

    # Neither threshold met
    best = max(qi_score, receipt_score)
    if best > 0:
        return ("unknown", round(best, 2))
    return ("unknown", 0.30)
