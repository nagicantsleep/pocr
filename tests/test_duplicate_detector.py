"""Tests for app.services.duplicate_detector — duplicate invoice detection."""

import hashlib

from app.services.duplicate_detector import check_duplicate, _hash_key, _build_primary_key, _build_fallback_key


_INV1 = {
    "issuer_name": "株式会社 ABC",
    "issuer_registration_number": "T1234567890123",
    "invoice_number": "INV-001",
    "transaction_date": "2026-06-25",
    "total_amount": 110000,
}


class TestCheckDuplicate:
    def test_exact_duplicate(self):
        result = check_duplicate(_INV1, [_INV1])
        assert result["is_duplicate"] is True
        assert result["confidence"] >= 0.95
        assert result["needs_review"] is False
        assert result["duplicate_of"] is _INV1

    def test_different_invoice_not_duplicate(self):
        inv2 = {**_INV1, "invoice_number": "INV-002"}
        result = check_duplicate(_INV1, [inv2])
        assert result["is_duplicate"] is False

    def test_same_amounts_different_date(self):
        inv2 = {**_INV1, "transaction_date": "2025-01-01"}
        result = check_duplicate(_INV1, [inv2])
        assert result["is_duplicate"] is False

    def test_fallback_key_match(self):
        # Same name + date + total, but different invoice_number and no reg number
        inv_a = {
            "issuer_name": "株式会社 ABC",
            "issuer_registration_number": None,
            "invoice_number": "INV-001",
            "transaction_date": "2026-06-25",
            "total_amount": 110000,
        }
        inv_b = {
            "issuer_name": "株式会社 ABC",
            "issuer_registration_number": None,
            "invoice_number": "INV-999",
            "transaction_date": "2026-06-25",
            "total_amount": 110000,
        }
        result = check_duplicate(inv_a, [inv_b])
        assert result["is_duplicate"] is True
        assert result["confidence"] < 0.95  # fallback is lower confidence
        assert result["needs_review"] is True

    def test_none_existing_invoices(self):
        result = check_duplicate(_INV1, None)
        assert result["is_duplicate"] is False

    def test_empty_existing_invoices(self):
        result = check_duplicate(_INV1, [])
        assert result["is_duplicate"] is False

    def test_hash_determinism(self):
        key = _build_primary_key(_INV1)
        h1 = _hash_key(key)
        h2 = _hash_key(key)
        assert h1 == h2
        # Verify it's actually sha256
        expected = hashlib.sha256(key.encode("utf-8")).hexdigest()
        assert h1 == expected

    def test_primary_key_requires_all_fields(self):
        # Missing invoice_number → no primary key
        partial = {**_INV1, "invoice_number": None}
        assert _build_primary_key(partial) is None

    def test_fallback_key_requires_name(self):
        no_name = {**_INV1, "issuer_name": None}
        assert _build_fallback_key(no_name) is None
