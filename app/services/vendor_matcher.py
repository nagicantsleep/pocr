"""Match extracted invoice issuer against a known vendor database."""

import re
import unicodedata


def normalize_issuer_name(name: str) -> str:
    """Normalize a Japanese company name for comparison.

    Normalizations:
      - Full-width alphanumerics → half-width
      - 株式会社 → (株), 有限会社 → (有), 合同会社 → (LLC)
      - ㈱ → (株), ㈲ → (有)
      - Collapse and strip whitespace
    """
    # Full-width → half-width for alphanumerics and common punctuation
    result = []
    for ch in name:
        cp = ord(ch)
        # Full-width ASCII (FF01-FF5E) → half-width (0021-007E)
        if 0xFF01 <= cp <= 0xFF5E:
            result.append(chr(cp - 0xFEE0))
        # Full-width space (3000) → half-width
        elif cp == 0x3000:
            result.append(" ")
        else:
            result.append(ch)
    text = "".join(result)

    # Company type normalization (order matters: longer first)
    text = text.replace("株式会社", "(株)")
    text = text.replace("有限会社", "(有)")
    text = text.replace("合同会社", "(LLC)")
    text = text.replace("㈱", "(株)")
    text = text.replace("㈲", "(有)")

    # Collapse whitespace and strip
    text = re.sub(r"\s+", "", text)
    return text


def match_vendor(
    issuer_name: str | None,
    registration_number: str | None,
    vendor_db: list[dict] | None = None,
) -> dict:
    """Match extracted issuer against known vendors.

    Priority:
      1. Exact match on registration_number (highest confidence)
      2. Normalize issuer names then exact match
      3. Fuzzy name match (weak evidence, sets needs_review=true)

    Args:
        issuer_name: Extracted issuer name (may be None).
        registration_number: Extracted registration number (may be None).
        vendor_db: List of vendor dicts. Each should have keys like
                   "name", "registration_number", and optional metadata.

    Returns:
        {"matched": bool, "vendor": dict|None, "match_method": str,
         "confidence": float, "needs_review": bool}
    """
    no_match = {"matched": False, "vendor": None, "match_method": "none", "confidence": 0.0, "needs_review": False}

    if not vendor_db:
        return no_match

    # 1. Registration number match (highest confidence)
    if registration_number:
        reg_upper = registration_number.upper().replace("Ｔ", "T")
        for vendor in vendor_db:
            v_reg = vendor.get("registration_number")
            if v_reg and v_reg.upper().replace("Ｔ", "T") == reg_upper:
                return {
                    "matched": True,
                    "vendor": vendor,
                    "match_method": "registration_number",
                    "confidence": 0.99,
                    "needs_review": False,
                }

    # 2. Normalized name match
    if issuer_name:
        normalized = normalize_issuer_name(issuer_name)
        for vendor in vendor_db:
            v_name = vendor.get("name", "")
            if normalize_issuer_name(v_name) == normalized:
                return {
                    "matched": True,
                    "vendor": vendor,
                    "match_method": "normalized_name",
                    "confidence": 0.85,
                    "needs_review": False,
                }

    # 3. Fuzzy name match (contains substring in either direction)
    if issuer_name:
        normalized = normalize_issuer_name(issuer_name)
        best_match: dict | None = None
        best_score = 0.0
        for vendor in vendor_db:
            v_name = vendor.get("name", "")
            v_normalized = normalize_issuer_name(v_name)
            if not v_normalized or not normalized:
                continue
            # Substring containment
            if normalized in v_normalized or v_normalized in normalized:
                # Longer overlap relative to the shorter string = higher score
                shorter = min(len(normalized), len(v_normalized))
                longer = max(len(normalized), len(v_normalized))
                score = shorter / longer if longer > 0 else 0.0
                if score > best_score:
                    best_score = score
                    best_match = vendor

        if best_match and best_score >= 0.3:
            return {
                "matched": True,
                "vendor": best_match,
                "match_method": "fuzzy_name",
                "confidence": round(0.5 + best_score * 0.2, 2),
                "needs_review": True,
            }

    return no_match
