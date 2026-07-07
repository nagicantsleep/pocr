"""Tests for app.services.schema_validator — schema-driven validation."""

import pytest

from app.schemas.registry.schema_model import FieldDefinition, FieldValidator, SchemaDefinition
from app.services.schema_validator import SchemaValidator


@pytest.fixture
def validator():
    return SchemaValidator()


@pytest.fixture
def invoice_jp_schema():
    """Minimal schema mirroring invoice-jp for testing."""
    return SchemaDefinition(
        id="invoice-jp",
        version="1.0.0",
        document_type="qualified_invoice",
        locale="ja-JP",
        currency="JPY",
        review_threshold=0.85,
        fields=[
            FieldDefinition(
                name="issuer_name",
                type="string",
                required=True,
            ),
            FieldDefinition(
                name="issuer_registration_number",
                type="string",
                pattern=r"^T\d{13}$",
                required=True,
                validators=[FieldValidator(code="reg001", severity="error")],
            ),
            FieldDefinition(
                name="transaction_date",
                type="date",
                required=True,
                validators=[FieldValidator(code="date001", severity="error")],
            ),
            FieldDefinition(
                name="total_amount",
                type="money",
                required=True,
                validators=[FieldValidator(code="amt001", severity="error")],
                cross_field=[
                    {"eq": "subtotal_8pct + subtotal_10pct + tax_8pct + tax_10pct"}
                ],
            ),
        ],
    )


class TestReg001:
    def test_valid_registration(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[1]
        issues = validator.validate_field(field_def, "T1234567890123")
        assert issues == []

    def test_invalid_registration(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[1]
        issues = validator.validate_field(field_def, "X123")
        assert len(issues) == 1
        assert issues[0].code == "reg001"
        assert issues[0].severity == "error"

    def test_missing_registration(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[1]
        issues = validator.validate_field(field_def, None)
        assert len(issues) == 1
        assert issues[0].code == "reg001"
        assert "not found" in issues[0].message

    def test_full_width_t(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[1]
        issues = validator.validate_field(field_def, "Ｔ1234567890123")
        assert issues == []


class TestAmt001:
    def test_valid_amount(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[3]
        issues = validator.validate_field(field_def, 110000)
        assert issues == []

    def test_none_amount(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[3]
        issues = validator.validate_field(field_def, None)
        assert len(issues) == 1
        assert issues[0].code == "amt001"

    def test_zero_amount(self, validator, invoice_jp_schema):
        field_def = invoice_jp_schema.fields[3]
        issues = validator.validate_field(field_def, 0)
        assert len(issues) == 1
        assert issues[0].code == "amt001"


class TestCrossField:
    def test_matching_subtotal_plus_tax(self, validator, invoice_jp_schema):
        extracted = {
            "subtotal_8pct": 100000,
            "subtotal_10pct": 0,
            "tax_8pct": 8000,
            "tax_10pct": 0,
            "total_amount": 108000,
        }
        issues = validator.validate_cross_field(invoice_jp_schema, extracted)
        assert issues == []

    def test_mismatched_subtotal_plus_tax(self, validator, invoice_jp_schema):
        extracted = {
            "subtotal_8pct": 100000,
            "subtotal_10pct": 0,
            "tax_8pct": 8000,
            "tax_10pct": 0,
            "total_amount": 115000,
        }
        issues = validator.validate_cross_field(invoice_jp_schema, extracted)
        assert len(issues) == 1
        assert issues[0].code == "amt002"
        assert issues[0].severity == "warning"

    def test_missing_total_skips(self, validator, invoice_jp_schema):
        extracted = {
            "subtotal_8pct": 100000,
            "subtotal_10pct": 0,
            "tax_8pct": 8000,
            "tax_10pct": 0,
        }
        issues = validator.validate_cross_field(invoice_jp_schema, extracted)
        assert issues == []

    def test_missing_term_skips(self, validator, invoice_jp_schema):
        extracted = {
            "subtotal_8pct": 100000,
            "total_amount": 108000,
        }
        issues = validator.validate_cross_field(invoice_jp_schema, extracted)
        assert issues == []


class TestValidateAll:
    def test_happy_path(self, validator, invoice_jp_schema):
        extracted = {
            "issuer_name": "Test Corp",
            "issuer_registration_number": "T1234567890123",
            "transaction_date": "2026-06-25",
            "subtotal_8pct": 100000,
            "subtotal_10pct": 0,
            "tax_8pct": 8000,
            "tax_10pct": 0,
            "total_amount": 108000,
        }
        issues = validator.validate_all(invoice_jp_schema, extracted)
        assert issues == []

    def test_empty_extracted_all_required_errors(self, validator, invoice_jp_schema):
        issues = validator.validate_all(invoice_jp_schema, {})
        codes = {i.code for i in issues}
        assert "reg001" in codes
        assert "date001" in codes
        assert "amt001" in codes

    def test_multiple_errors(self, validator, invoice_jp_schema):
        extracted = {
            "issuer_name": "Test Corp",
            "issuer_registration_number": "X123",
            "transaction_date": None,
            "total_amount": None,
        }
        issues = validator.validate_all(invoice_jp_schema, extracted)
        codes = [i.code for i in issues]
        assert "reg001" in codes
        assert "date001" in codes
        assert "amt001" in codes

    def test_warning_severity(self, validator):
        schema = SchemaDefinition(
            id="test",
            version="1.0.0",
            document_type="test",
            fields=[
                FieldDefinition(
                    name="issuer_registration_number",
                    type="string",
                    validators=[FieldValidator(code="reg001", severity="warning")],
                ),
            ],
        )
        extracted = {"issuer_registration_number": "X123"}
        issues = validator.validate_all(schema, extracted)
        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].code == "reg001"


class TestRegistration:
    def test_custom_validator_registered(self):
        def my_validator(field_name, value, severity):
            if value == "bad":
                from app.schemas.invoice import ValidationIssue
                return [ValidationIssue(code="custom001", severity=severity, message="bad value", field=field_name)]
            return []

        SchemaValidator.register("custom001", my_validator)
        try:
            schema = SchemaDefinition(
                id="test",
                version="1.0.0",
                document_type="test",
                fields=[
                    FieldDefinition(
                        name="myfield",
                        type="string",
                        validators=[FieldValidator(code="custom001", severity="error")],
                    ),
                ],
            )
            sv = SchemaValidator()
            issues = sv.validate_field(schema.fields[0], "bad")
            assert len(issues) == 1
            assert issues[0].code == "custom001"
        finally:
            del SchemaValidator._validators["custom001"]
