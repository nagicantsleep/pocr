"""Tests for app.services.invoice_validator — validation rules."""

from app.schemas.invoice import InvoiceData
from app.services.invoice_validator import validate_invoice


def _make_invoice(**kwargs) -> InvoiceData:
    """Helper to build InvoiceData with defaults for happy-path fields."""
    defaults = {
        "issuer_registration_number": "T1234567890123",
        "transaction_date": "2026-06-25",
        "total_amount": 110000,
        "subtotal_by_tax_rate": {"10%": 100000},
        "consumption_tax_by_rate": {"10%": 10000},
    }
    defaults.update(kwargs)
    return InvoiceData(**defaults)


class TestREG001:
    def test_missing_registration_number(self):
        invoice = _make_invoice(issuer_registration_number=None)
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "REG001" in codes
        assert any("not found" in e.message for e in result.errors if e.code == "REG001")

    def test_invalid_format_short(self):
        invoice = _make_invoice(issuer_registration_number="T12345")
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "REG001" in codes

    def test_invalid_format_wrong_prefix(self):
        invoice = _make_invoice(issuer_registration_number="X1234567890123")
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "REG001" in codes

    def test_valid_registration(self):
        invoice = _make_invoice(issuer_registration_number="T1234567890123")
        result = validate_invoice(invoice)
        codes = [e.code for e in result.errors]
        assert "REG001" not in codes

    def test_full_width_t(self):
        invoice = _make_invoice(issuer_registration_number="Ｔ1234567890123")
        result = validate_invoice(invoice)
        codes = [e.code for e in result.errors]
        assert "REG001" not in codes


class TestDATE001:
    def test_missing_transaction_date(self):
        invoice = _make_invoice(transaction_date=None)
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "DATE001" in codes

    def test_valid_date(self):
        invoice = _make_invoice(transaction_date="2026-06-25")
        result = validate_invoice(invoice)
        codes = [e.code for e in result.errors]
        assert "DATE001" not in codes


class TestAMT001:
    def test_missing_total_amount(self):
        invoice = _make_invoice(total_amount=None)
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "AMT001" in codes

    def test_valid_total_amount(self):
        invoice = _make_invoice(total_amount=110000)
        result = validate_invoice(invoice)
        codes = [e.code for e in result.errors]
        assert "AMT001" not in codes


class TestAMT002:
    def test_subtotal_plus_tax_matches_total(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 10000},
            total_amount=110000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "AMT002" not in codes

    def test_subtotal_plus_tax_mismatch(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 10000},
            total_amount=115000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "AMT002" in codes

    def test_missing_total_skips_check(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 10000},
            total_amount=None,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "AMT002" not in codes

    def test_small_tolerance_allowed(self):
        # 1 JPY difference is within tolerance
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 9999},
            total_amount=109999,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "AMT002" not in codes


class TestTAX001:
    def test_8_percent_tax_reasonable(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"8%": 100000},
            consumption_tax_by_rate={"8%": 8000},
            issuer_registration_number="T1111111111111",
            transaction_date="2026-01-01",
            total_amount=108000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "TAX001" not in codes

    def test_8_percent_tax_mismatch(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"8%": 100000},
            consumption_tax_by_rate={"8%": 5000},
            issuer_registration_number="T1111111111111",
            transaction_date="2026-01-01",
            total_amount=105000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "TAX001" in codes


class TestTAX002:
    def test_10_percent_tax_reasonable(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 10000},
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "TAX002" not in codes

    def test_10_percent_tax_mismatch(self):
        invoice = _make_invoice(
            subtotal_by_tax_rate={"10%": 100000},
            consumption_tax_by_rate={"10%": 20000},
            total_amount=120000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "TAX002" in codes


class TestRECIPIENT001:
    def test_qualified_invoice_has_recipient(self):
        invoice = _make_invoice(recipient_name="株式会社 XYZ")
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "RECIPIENT001" not in codes

    def test_qualified_invoice_missing_recipient(self):
        invoice = _make_invoice(recipient_name=None)
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "RECIPIENT001" in codes

    def test_non_qualified_invoice_no_recipient_warning(self):
        invoice = _make_invoice(
            issuer_registration_number=None,
            recipient_name=None,
            transaction_date="2026-06-25",
            total_amount=50000,
        )
        result = validate_invoice(invoice)
        codes = [w.code for w in result.warnings]
        assert "RECIPIENT001" not in codes


class TestValidateInvoice:
    def test_valid_invoice(self):
        invoice = _make_invoice(recipient_name="株式会社 XYZ")
        result = validate_invoice(invoice)
        assert result.is_valid
        assert result.errors == []
        assert result.warnings == []

    def test_multiple_errors(self):
        invoice = _make_invoice(
            issuer_registration_number=None,
            transaction_date=None,
            total_amount=None,
        )
        result = validate_invoice(invoice)
        assert not result.is_valid
        codes = [e.code for e in result.errors]
        assert "REG001" in codes
        assert "DATE001" in codes
        assert "AMT001" in codes
