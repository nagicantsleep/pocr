"""Duplicate invoice detection via composite hashing."""

import hashlib


def _build_primary_key(invoice_data: dict) -> str | None:
    """Build primary dedup key from registration number + invoice number + date + total."""
    reg = (invoice_data.get("issuer_registration_number") or "").strip()
    inv_no = (invoice_data.get("invoice_number") or "").strip()
    date = (invoice_data.get("transaction_date") or "").strip()
    total = str(invoice_data.get("total_amount") or "")

    if not all([reg, inv_no, date, total]):
        return None
    return f"{reg}|{inv_no}|{date}|{total}"


def _build_fallback_key(invoice_data: dict) -> str | None:
    """Build fallback dedup key from issuer name + date + total."""
    name = (invoice_data.get("issuer_name") or "").strip()
    date = (invoice_data.get("transaction_date") or "").strip()
    total = str(invoice_data.get("total_amount") or "")

    if not all([name, date, total]):
        return None
    return f"{name}|{date}|{total}"


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def check_duplicate(
    invoice_data: dict,
    existing_invoices: list[dict] | None = None,
) -> dict:
    """Check for duplicate invoices.

    Primary key: hash(issuer_registration_number + invoice_number + transaction_date + total_amount)
    Fallback key: hash(issuer_name + transaction_date + total_amount)

    Args:
        invoice_data: Extracted invoice fields as a plain dict.
        existing_invoices: List of existing invoice dicts to check against.

    Returns:
        {"is_duplicate": bool, "duplicate_of": dict|None,
         "confidence": float, "needs_review": bool}
    """
    no_dup = {"is_duplicate": False, "duplicate_of": None, "confidence": 0.0, "needs_review": False}

    if not existing_invoices:
        return no_dup

    primary_key = _build_primary_key(invoice_data)
    fallback_key = _build_fallback_key(invoice_data)

    primary_hash = _hash_key(primary_key) if primary_key else None
    fallback_hash = _hash_key(fallback_key) if fallback_key else None

    for existing in existing_invoices:
        # Primary key match (highest confidence)
        if primary_hash:
            e_primary = _build_primary_key(existing)
            if e_primary and _hash_key(e_primary) == primary_hash:
                return {
                    "is_duplicate": True,
                    "duplicate_of": existing,
                    "confidence": 0.99,
                    "needs_review": False,
                }

    # Fallback: only when primary key couldn't be built (missing fields)
    if fallback_hash and not primary_hash:
        for existing in existing_invoices:
            e_fallback = _build_fallback_key(existing)
            if e_fallback and _hash_key(e_fallback) == fallback_hash:
                return {
                    "is_duplicate": True,
                    "duplicate_of": existing,
                    "confidence": 0.80,
                    "needs_review": True,
                }

    return no_dup
