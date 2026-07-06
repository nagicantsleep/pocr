"""Tests for app.services.invoice_confidence — field-level confidence scoring."""

from app.schemas.invoice import InvoiceValidationResult, ValidationIssue
from app.services.invoice_confidence import compute_field_confidence


class TestComputeFieldConfidence:
    def test_high_confidence_extraction(self):
        """All fields found with strong evidence -> scores > 0.8."""
        evidence = {
            "issuer_registration_number": {
                "ocr_confidence": 0.97,
                "method": "labeled",
            },
            "total_amount": {
                "ocr_confidence": 0.96,
                "has_total_keyword": True,
            },
            "transaction_date": {
                "ocr_confidence": 0.96,
                "has_date_label": True,
            },
        }
        result = compute_field_confidence(evidence)
        assert result["issuer_registration_number"] > 0.80
        assert result["total_amount"] > 0.80
        assert result["transaction_date"] > 0.80

    def test_missing_fields_omitted(self):
        """Fields with no evidence are not in the result."""
        result = compute_field_confidence({})
        assert result == {}

    def test_low_ocr_confidence(self):
        """Low OCR confidence produces low field confidence."""
        evidence = {
            "total_amount": {
                "ocr_confidence": 0.30,
                "has_total_keyword": True,
            },
        }
        result = compute_field_confidence(evidence)
        assert result["total_amount"] < 0.60

    def test_validation_errors_lower_confidence(self):
        """Validation errors targeting a field should lower its score."""
        evidence = {
            "issuer_registration_number": {
                "ocr_confidence": 0.97,
                "method": "labeled",
            },
        }
        validation = InvoiceValidationResult(
            is_valid=False,
            errors=[
                ValidationIssue(
                    code="REG001",
                    severity="error",
                    message="Registration number not found",
                    field="issuer_registration_number",
                ),
            ],
        )
        result_with = compute_field_confidence(evidence, validation)
        result_without = compute_field_confidence(evidence)
        assert result_with["issuer_registration_number"] < result_without["issuer_registration_number"]

    def test_validation_warnings_partial_penalty(self):
        """Validation warnings reduce confidence but less than errors."""
        evidence = {
            "total_amount": {
                "ocr_confidence": 0.96,
                "has_total_keyword": True,
            },
        }
        validation = InvoiceValidationResult(
            is_valid=True,
            warnings=[
                ValidationIssue(
                    code="AMT002",
                    severity="warning",
                    message="Subtotal + tax mismatch",
                    field="total_amount",
                ),
            ],
        )
        result = compute_field_confidence(evidence, validation)
        # Still decent because only the validation component is halved
        assert result["total_amount"] > 0.70

    def test_no_validation_neutral(self):
        """When no validation is provided, use neutral 0.50 for validation component."""
        evidence = {
            "issuer_registration_number": {
                "ocr_confidence": 0.90,
                "method": "isolated",
            },
        }
        result = compute_field_confidence(evidence, validation=None)
        assert 0.60 <= result["issuer_registration_number"] <= 0.85

    def test_registration_labeled_vs_isolated(self):
        """Labeled registration number scores higher than isolated."""
        ev_labeled = {
            "issuer_registration_number": {
                "ocr_confidence": 0.90,
                "method": "labeled",
            },
        }
        ev_isolated = {
            "issuer_registration_number": {
                "ocr_confidence": 0.90,
                "method": "isolated",
            },
        }
        labeled_score = compute_field_confidence(ev_labeled)["issuer_registration_number"]
        isolated_score = compute_field_confidence(ev_isolated)["issuer_registration_number"]
        assert labeled_score > isolated_score

    def test_deterministic_output(self):
        """Same input produces exactly the same output."""
        evidence = {
            "total_amount": {
                "ocr_confidence": 0.96,
                "has_total_keyword": True,
            },
            "transaction_date": {
                "ocr_confidence": 0.95,
                "has_date_label": False,
            },
        }
        r1 = compute_field_confidence(evidence)
        r2 = compute_field_confidence(evidence)
        assert r1 == r2

    def test_issuer_name_confidence(self):
        """Issuer name with near_registration_number and bottom position."""
        evidence = {
            "issuer_name": {
                "ocr_confidence": 0.90,
                "near_registration_number": True,
                "position": "bottom",
            },
        }
        result = compute_field_confidence(evidence)
        assert result["issuer_name"] > 0.70

    def test_recipient_name_near_onchu(self):
        """Recipient near 御中."""
        evidence = {
            "recipient_name": {
                "ocr_confidence": 0.95,
                "near_onchu": True,
            },
        }
        result = compute_field_confidence(evidence)
        assert result["recipient_name"] > 0.75

    def test_score_clamped_zero_to_one(self):
        """Confidence scores are clamped to [0.0, 1.0]."""
        evidence = {
            "total_amount": {
                "ocr_confidence": 2.0,
                "has_total_keyword": True,
            },
        }
        result = compute_field_confidence(evidence)
        assert result["total_amount"] <= 1.0

        evidence_low = {
            "total_amount": {
                "ocr_confidence": -1.0,
                "has_total_keyword": False,
            },
        }
        result_low = compute_field_confidence(evidence_low)
        assert result_low["total_amount"] >= 0.0
