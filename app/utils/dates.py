"""Japanese date normalization utilities."""

import re


# Reiwa era: Reiwa 1 = 2019
_REIWA_OFFSET = 2018

# Era name → offset (year - era_year = offset)
_ERA_OFFSETS = {
    "令和": _REIWA_OFFSET,  # 令和1年 = 2019
    "平成": 1988,  # 平成1年 = 1989
}

# Compiled patterns
_WESTERN_YMD = re.compile(
    r"(\d{4})\s*[/\-年]\s*(\d{1,2})\s*[/\-月]\s*(\d{1,2})\s*日?"
)
_ERA_YMD = re.compile(
    r"(令和|平成)\s*(\d{1,2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?"
)


def normalize_japanese_date(value: str) -> str | None:
    """
    Parse a Japanese date string into ISO format (YYYY-MM-DD).

    Handles:
    - 2026年6月25日 → 2026-06-25
    - 2026/06/25 → 2026-06-25
    - 2026-06-25 → 2026-06-25
    - 令和8年6月25日 → 2026-06-25
    - Single-digit months/days without leading zeros

    Returns None for unparseable input.
    """
    if not value or not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    # Try Reiwa/Heisei era format first (search, not match — dates can have label prefix)
    era_match = _ERA_YMD.search(s)
    if era_match:
        era_name = era_match.group(1)
        era_year = int(era_match.group(2))
        month = int(era_match.group(3))
        day = int(era_match.group(4))
        offset = _ERA_OFFSETS.get(era_name)
        if offset is None:
            return None
        year = offset + era_year
    else:
        # Try Western YYYY/MM/DD or YYYY-MM-DD or YYYY年M月D日
        west_match = _WESTERN_YMD.search(s)
        if not west_match:
            return None
        year = int(west_match.group(1))
        month = int(west_match.group(2))
        day = int(west_match.group(3))

    # Validate ranges
    if not (1 <= month <= 12):
        return None
    if not (1 <= day <= 31):
        return None

    return f"{year:04d}-{month:02d}-{day:02d}"
