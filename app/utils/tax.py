"""Japanese invoice tax rounding utilities."""

import math


# Rate string → decimal
_RATE_DECIMALS = {
    "8%": 0.08,
    "10%": 0.10,
}


def expected_tax(
    subtotal: int,
    rate: str,
    rounding: str = "unknown",
) -> list[int]:
    """
    Calculate expected tax amount for a given subtotal and rate.

    Args:
        subtotal: Pre-tax amount in JPY
        rate: "8%" or "10%"
        rounding: "floor", "ceil", "round", or "unknown"

    Returns:
        List of possible tax amounts (deduplicated).
        When rounding is "unknown", returns [floor, ceil, round].
        When rounding is known, returns single-element list.
    """
    rate_decimal = _RATE_DECIMALS.get(rate)
    if rate_decimal is None:
        return []

    raw = subtotal * rate_decimal

    if rounding == "floor":
        return [math.floor(raw)]
    elif rounding == "ceil":
        return [math.ceil(raw)]
    elif rounding == "round":
        return [round(raw)]
    else:
        # unknown: return all three possibilities, deduplicated
        results = {math.floor(raw), math.ceil(raw), round(raw)}
        return sorted(results)
