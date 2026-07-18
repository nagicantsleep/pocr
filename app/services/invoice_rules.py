"""Japanese invoice regex rules and candidate extraction."""

import re
from app.utils.money import normalize_amount
from app.utils.dates import normalize_japanese_date


# Registration number: T + 13 digits (half or full width)
_REG_NO_PATTERN = re.compile(
    r"(?:登録番号|適格請求書発行事業者登録番号)[:：\s]*"
    r"([TＴ]\d{13})"
)
_REG_NO_ISOLATED = re.compile(r"[TＴ]\d{13}")

# Total amount keywords
_TOTAL_KEYWORDS = {
    "合計金額", "ご請求金額", "請求金額", "税込合計",
    "合計", "総合計", "お支払合計", "お支払い合計",
}
_OCR_TOTAL_LABEL = re.compile(r"合[計言][計十]")

# Tax rate labels
_TAX_LABELS_8 = {"8%", "８%", "8％", "８％", "8"}
_TAX_LABELS_10 = {"10%", "１０%", "10％", "１０％", "10"}

# Date labels
_DATE_LABELS = {"請求日", "発行日", "取引日", "支払期日", "支払期限", "お支払期限", "日付"}

# Invoice number labels
_INVOICE_LABELS = {"請求書番号", "請求No.", "請求No", "Invoice No.", "Invoice No", "No.", "No"}

# Recipient indicators
_RECIPIENT_KW = {"御中", "様", "各位"}

# Amount pattern: number with optional commas inside text
_AMOUNT_INLINE = re.compile(r"(?:合計|合計金額|ご請求金額|小計|消費税)\s*[:：]?\s*(?:[¥￥]?\s*[\d,０-９，\s]+)")


def find_registration_number(plain_text: str) -> list[dict]:
    """
    Find qualified invoice registration number candidates.

    Returns list of dicts with keys: value, source_text, bbox, confidence, rank.
    """
    candidates = []

    # Labeled pattern first (higher confidence)
    for m in _REG_NO_PATTERN.finditer(plain_text):
        raw = m.group(1)
        normalized = raw.upper().replace("Ｔ", "T")
        candidates.append({
            "value": normalized,
            "source_text": m.group(0),
            "method": "labeled",
            "rank": len(candidates) + 1,
        })

    # Isolated pattern fallback
    for m in _REG_NO_ISOLATED.finditer(plain_text):
        raw = m.group(0)
        normalized = raw.upper().replace("Ｔ", "T")
        is_dup = any(c["value"] == normalized for c in candidates)
        if not is_dup:
            candidates.append({
                "value": normalized,
                "source_text": raw,
                "method": "isolated",
                "rank": len(candidates) + 1,
            })

    return candidates


def find_total_amount(lines: list[dict]) -> list[dict]:
    """
    Find total amount candidates near total keywords.

    Args:
        lines: List of layout lines dicts (text, bbox, confidence, line_no).

    Returns:
        List of candidate dicts with value (int), source_text, bbox, confidence.
    """
    candidates = []
    for index, line in enumerate(lines):
        text = line["text"].strip()
        has_kw = any(kw in text for kw in _TOTAL_KEYWORDS) or bool(_OCR_TOTAL_LABEL.search(text))
        if not has_kw:
            continue

        # Extract the first amount-like token after the keyword
        for kw in sorted(_TOTAL_KEYWORDS, key=len, reverse=True):
            if kw in text:
                # Split on the keyword and take the right side
                parts = text.split(kw, 1)
                if len(parts) == 2:
                    rest = parts[1]
                else:
                    rest = text
                break
        else:
            rest = text

        amount = normalize_amount(rest)
        if amount is not None and amount > 0:
            candidates.append({
                "value": amount,
                "source_text": text,
                "bbox": line["bbox"],
                "confidence": line["confidence"],
                "rank": len(candidates) + 1,
            })
            continue

        # Try full line if split didn't yield clean number
        amount = normalize_amount(text)
        if amount is not None and amount > 0:
            candidates.append({
                "value": amount,
                "source_text": text,
                "bbox": line["bbox"],
                "confidence": line["confidence"],
                "rank": len(candidates) + 1,
            })
            continue

        nearby = _find_nearby_total_amount(lines, index)
        if nearby is not None:
            amount_line, amount = nearby
            candidates.append({
                "value": amount,
                "source_text": f"{text} | {amount_line['text'].strip()}",
                "bbox": amount_line["bbox"],
                "confidence": min(line["confidence"], amount_line["confidence"]),
                "rank": len(candidates) + 1,
            })

    return candidates

def _find_nearby_total_amount(lines: list[dict], label_index: int) -> tuple[dict, int] | None:
    """Match an OCR-split total label to a nearby, right-aligned currency value."""
    label = lines[label_index]
    label_top_left = label.get("bbox", {}).get("top_left", [0, 0])
    label_x = label_top_left[0] if label_top_left else 0
    label_y = label_top_left[1] if len(label_top_left) > 1 else 0
    candidates: list[tuple[float, dict, int]] = []

    for line in lines:
        text = line.get("text", "").strip()
        if not text or not any(symbol in text for symbol in ("¥", "￥")):
            continue
        amount = normalize_amount(text)
        if amount is None or amount <= 0:
            continue
        top_left = line.get("bbox", {}).get("top_left", [0, 0])
        line_x = top_left[0] if top_left else 0
        line_y = top_left[1] if len(top_left) > 1 else 0
        vertical_distance = abs(line_y - label_y)
        if line_x <= label_x or vertical_distance > 100:
            continue
        candidates.append((vertical_distance, line, amount))

    if not candidates:
        return None
    _, amount_line, amount = min(candidates, key=lambda candidate: candidate[0])
    return amount_line, amount


_AMOUNT_EXTRACT = re.compile(r"[\d,０-９，]+")


def find_tax_amounts(lines: list[dict]) -> dict:
    """
    Find 8% and 10% consumption tax amounts.

    Args:
        lines: Layout lines.

    Returns:
        Dict with keys "8%" and "10%", each a list of candidate dicts.
    """
    result: dict = {"8%": [], "10%": []}

    for line in lines:
        text = line["text"].strip()

        # Must have tax keyword
        if not ("消費税" in text or "内税" in text or "消費税額" in text):
            continue

        # Check which rate
        for rate_key, rate_set in [("8%", _TAX_LABELS_8), ("10%", _TAX_LABELS_10)]:
            has_rate = any(r in text for r in rate_set)
            if not has_rate:
                continue

            # Extract first numeric chunk that isn't the rate label itself
            for m in _AMOUNT_EXTRACT.finditer(text):
                chunk = m.group(0)
                # Skip if this chunk is within 3 chars of a % sign and is short
                # (i.e. it's the rate "8" or "10" not the amount "8,000" / "10,000")
                near_pct = any(
                    0 <= pos < len(text) and text[pos] in ("%", "％")
                    for pos in range(m.start() - 2, m.end() + 1)
                )
                if near_pct and len(chunk) <= 2:
                    continue
                amount = normalize_amount(chunk)
                if amount is not None and amount > 0:
                    result[rate_key].append({
                        "value": amount,
                        "source_text": text,
                        "bbox": line["bbox"],
                        "confidence": line["confidence"],
                        "rank": len(result[rate_key]) + 1,
                    })
                    break

    return result


def find_dates(lines: list[dict]) -> list[dict]:
    """
    Find transaction/payment dates with labels.

    Args:
        lines: Layout lines.

    Returns:
        List of candidate dicts with value (ISO date str), source_text, etc.
    """
    candidates = []
    for line in lines:
        text = line["text"].strip()
        has_label = any(label in text for label in _DATE_LABELS)
        if not has_label:
            continue

        iso = normalize_japanese_date(text)
        if iso:
            candidates.append({
                "value": iso,
                "source_text": text,
                "bbox": line["bbox"],
                "confidence": line["confidence"],
                "rank": len(candidates) + 1,
            })

    if not candidates:
        # Fallback: find any date in the text
        for line in lines:
            iso = normalize_japanese_date(line["text"])
            if iso:
                candidates.append({
                    "value": iso,
                    "source_text": line["text"],
                    "bbox": line["bbox"],
                    "confidence": line["confidence"] * 0.8,  # lower confidence without label
                    "rank": len(candidates) + 1,
                })

    return candidates


def find_invoice_number(lines: list[dict]) -> list[dict]:
    """
    Find invoice number candidates.

    Args:
        lines: Layout lines.

    Returns:
        List of candidate dicts.
    """
    candidates = []
    for line in lines:
        text = line["text"].strip()
        has_label = any(label in text for label in _INVOICE_LABELS)
        if not has_label:
            continue

        # Extract value after label
        for label in sorted(_INVOICE_LABELS, key=len, reverse=True):
            if label in text:
                parts = text.split(label, 1)
                if len(parts) == 2:
                    value = parts[1].strip().lstrip(":：").strip()
                    if value:
                        candidates.append({
                            "value": value,
                            "source_text": text,
                            "bbox": line["bbox"],
                            "confidence": line["confidence"],
                            "rank": len(candidates) + 1,
                        })
                break

    return candidates


def find_issuer_name(lines: list[dict], blocks: list[dict] | None = None) -> list[dict]:
    """
    Find issuer (vendor) name candidates.

    Strategy:
    1. Lines near a registration number.
    2. Lines in the issuer block (bottom of document).
    3. Lines containing "株式会社" that aren't the recipient.

    Args:
        lines: Layout lines.
        blocks: Layout blocks (optional, for position hints).

    Returns:
        List of candidate dicts.
    """
    candidates = []
    issuer_blocks_coords: list[float] = []

    if blocks:
        for b in blocks:
            if b["type"] == "issuer":
                issuer_blocks_coords.append(b["bbox"]["top_left"][1])

    # Lines containing company-indicating patterns
    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        # Must have Japanese company indicators
        has_company = ("株式会社" in text or "合同会社" in text or
                       "有限会社" in text or re.search(r"[（(]株[）)]", text))

        # Exclude recipient lines
        if any(kw in text for kw in _RECIPIENT_KW):
            continue

        y_center = (line["bbox"]["top_left"][1] + line["bbox"]["bottom_right"][1]) / 2

        if has_company:
            candidates.append({
                "value": text,
                "source_text": text,
                "bbox": line["bbox"],
                "confidence": line["confidence"],
                "position": "top" if y_center < 500 else "bottom",
                "rank": len(candidates) + 1,
            })

    return candidates


def find_recipient_name(lines: list[dict]) -> list[dict]:
    """
    Find recipient (customer) name candidates.

    Strategy: lines containing "御中", "様", or company names near those.

    Args:
        lines: Layout lines.

    Returns:
        List of candidate dicts.
    """
    candidates = []

    for line in lines:
        text = line["text"].strip()
        if not text:
            continue

        found_kw = None
        for kw in _RECIPIENT_KW:
            if kw in text:
                found_kw = kw
                break

        if found_kw:
            name = text.replace(found_kw, "").strip()
            if name:
                candidates.append({
                    "value": name,
                    "source_text": line["text"].strip(),
                    "bbox": line["bbox"],
                    "confidence": line["confidence"],
                    "rank": len(candidates) + 1,
                })

    return candidates
