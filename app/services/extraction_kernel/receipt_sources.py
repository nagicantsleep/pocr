"""Additional source functions for receipt-jp document processing."""

from __future__ import annotations

import re

from app.utils.money import normalize_amount


_PHONE_PATTERN = re.compile(
    r"(?:TEL[:：\s]*|電話[:：\s]*)?(\d{2,4}-\d{2,4}-\d{3,4})"
)

_PAYMENT_KEYWORDS = {
    "現金": "現金",
    "カード": "カード",
    "クレジットカード": "クレジットカード",
    "クレジット": "クレジットカード",
    "デビットカード": "デビットカード",
    "電子マネー": "電子マネー",
    "PayPay": "PayPay",
    "paypay": "PayPay",
    "Suica": "Suica",
    "PASMO": "PASMO",
    "ID": "iD",
    "QUICPay": "QUICPay",
    "楽天ペイ": "楽天ペイ",
    "LINE Pay": "LINE Pay",
    "d払い": "d払い",
    "au PAY": "au PAY",
    "WAON": "WAON",
    "nanaco": "nanaco",
}

_PAYMENT_LABEL_KEYWORDS = {"お支払い方法", "お支払方法", "支払い方法", "支払方法", "決済方法", "お支払い"}

_CHANGE_KEYWORDS = {"お釣り", "釣銭", "おつり", "お釣"}

_TAX_KEYWORDS = {"消費税", "税", "内税", "外税", "消費税額"}

_SUBTOTAL_KEYWORDS = {"小計", "税抜合計", "税抜"}


def find_store_phone(plain_text: str) -> list[dict]:
    """Find phone number candidates in text."""
    candidates: list[dict] = []
    for m in _PHONE_PATTERN.finditer(plain_text):
        phone = m.group(1)
        candidates.append({
            "value": phone,
            "source_text": m.group(0).strip(),
            "method": "regex",
            "rank": len(candidates) + 1,
        })
    return candidates


def find_payment_method(plain_text: str) -> list[dict]:
    """Find payment method candidates."""
    candidates: list[dict] = []

    for label in _PAYMENT_LABEL_KEYWORDS:
        if label not in plain_text:
            continue
        for kw, canonical in _PAYMENT_KEYWORDS.items():
            idx = plain_text.find(kw)
            if idx >= 0:
                candidates.append({
                    "value": canonical,
                    "source_text": plain_text[max(0, idx - 5):idx + len(kw) + 5].strip(),
                    "method": "labeled",
                    "rank": len(candidates) + 1,
                })
                break

    if not candidates:
        for kw, canonical in sorted(_PAYMENT_KEYWORDS.items(), key=lambda x: -len(x[0])):
            if kw in plain_text:
                candidates.append({
                    "value": canonical,
                    "source_text": kw,
                    "method": "keyword",
                    "rank": len(candidates) + 1,
                })
                break

    return candidates


def _extract_amount_after_keyword(plain_text: str, keywords: set[str]) -> list[dict]:
    """Extract amount candidates that appear after a keyword in the text.

    Same pattern as invoice_rules.find_total_amount: split on the keyword
    and parse the right side.
    """
    candidates: list[dict] = []
    for kw in sorted(keywords, key=len, reverse=True):
        if kw not in plain_text:
            continue
        parts = plain_text.split(kw, 1)
        rest = parts[1] if len(parts) == 2 else plain_text
        amount = normalize_amount(rest[:20])
        if amount is not None:
            source = f"{kw} {rest[:20]}".strip()
            candidates.append({
                "value": amount,
                "source_text": source,
                "method": "regex",
                "rank": len(candidates) + 1,
            })
    return candidates


def find_change_amount(plain_text: str) -> list[dict]:
    """Find change amount candidates."""
    return [
        {**c}
        for c in _extract_amount_after_keyword(plain_text, _CHANGE_KEYWORDS)
        if c["value"] >= 0
    ]


def find_tax_amount(plain_text: str) -> list[dict]:
    """Find tax amount candidates."""
    return [
        {**c}
        for c in _extract_amount_after_keyword(plain_text, _TAX_KEYWORDS)
        if c["value"] > 0
    ]


def find_subtotal(plain_text: str) -> list[dict]:
    """Find subtotal candidates."""
    return [
        {**c}
        for c in _extract_amount_after_keyword(plain_text, _SUBTOTAL_KEYWORDS)
        if c["value"] > 0
    ]


def find_store_address(lines: list[dict]) -> list[dict]:
    """Find store address candidates from labeled layout lines."""
    candidates: list[dict] = []
    _ADDR_LABELS = {"住所", "所在地", "店舗住所"}
    for line in lines:
        text = line.get("text", "").strip()
        for label in _ADDR_LABELS:
            if label not in text:
                continue
            rest = text.split(label, 1)[1].lstrip(":：").strip()
            if rest:
                candidates.append({
                    "value": rest,
                    "source_text": text,
                    "method": "labeled",
                    "rank": len(candidates) + 1,
                })
    return candidates
