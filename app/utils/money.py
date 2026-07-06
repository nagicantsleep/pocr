"""Japanese invoice amount normalization utilities."""

import re


def normalize_amount(value: str) -> int | None:
    """
    Parse a Japanese invoice amount string into an integer.

    Handles:
    - Currency symbols: ¥, ￥, 円
    - Full-width commas (，) and half-width commas as thousands separators
    - Full-width digits (０-９) → ASCII
    - Spaces between digits
    - Negative forms: -10,000 / △10,000 / （10,000）
    - OCR O/0 and l/1 correction in numeric contexts

    Returns None for unparseable input.
    """
    if not value or not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    # Detect negative forms before stripping symbols
    negative = False

    # Plain minus prefix
    if s.startswith("-"):
        negative = True
        s = s[1:].lstrip()

    # △ prefix = negative
    if s.startswith("△"):
        negative = True
        s = s[1:]

    # Parenthesized form: （10,000） or (10,000)
    paren_match = re.match(r"[（(]\s*(.+?)\s*[）)]$", s)
    if paren_match:
        negative = True
        s = paren_match.group(1)

    # Strip currency prefix/suffix
    s = re.sub(r"[¥￥円]", "", s)

    # Remove commas (half and full width) used as thousands separators
    s = s.replace(",", "").replace("，", "")

    # Remove spaces
    s = s.replace(" ", "").replace("　", "")

    # Full-width digits → ASCII
    fw = str.maketrans("０１２３４５６７８９", "0123456789")
    s = s.translate(fw)

    # OCR correction: O → 0, l → 1, but only when surrounded by digits
    # or at boundaries where a digit is expected
    s = _ocr_digit_fix(s)

    # Validate: must be digits only at this point
    if not s or not re.fullmatch(r"\d+", s):
        return None

    result = int(s)
    return -result if negative else result


def _ocr_digit_fix(s: str) -> str:
    """Fix common OCR digit misreads in numeric-only contexts.

    Treats O/o/l/I as potential digits for boundary checks so chains
    like 1OOO correctly resolve to 1000.
    """
    _maybe_digit = set("OolI")

    def _is_or_maybe(i: int) -> bool:
        return s[i].isdigit() or s[i] in _maybe_digit

    result = []
    for i, ch in enumerate(s):
        if ch in ("O", "o"):
            left_ok = i == 0 or _is_or_maybe(i - 1)
            right_ok = i == len(s) - 1 or _is_or_maybe(i + 1)
            if left_ok and right_ok:
                result.append("0")
                continue
        elif ch in ("l", "I"):
            left_ok = i == 0 or _is_or_maybe(i - 1)
            right_ok = i == len(s) - 1 or _is_or_maybe(i + 1)
            if left_ok and right_ok:
                result.append("1")
                continue
        result.append(ch)
    return "".join(result)
