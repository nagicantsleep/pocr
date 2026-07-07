"""Tests for app.services.schema_confidence — schema-driven confidence scoring."""

import pytest

from app.schemas.registry.schema_model import FieldDefinition, FieldValidator, SchemaDefinition
from app.services.schema_confidence import SchemaConfidenceScorer


@pytest.fixture
def scorer():
    return SchemaConfidenceScorer()


@pytest.fixture
def invoice_jp_schema():
    return SchemaDefinition(
        id="invoice-jp",
        version="1.0.0",
        document_type="qualified_invoice",
        locale="ja-JP",
        currency="JPY",
        review_threshold=0.85,
        fields=[
            FieldDefinition(name="issuer_name", type="string", required=True),
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
            ),
            FieldDefinition(name="invoice_number", type="string", required=False),
        ],
    )


class TestScoreField:
    def test_good_evidence_high_confidence(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {
            "ocr_confidence": 0.96,
            "has_total_keyword": True,
        }
        score = scorer.score_field(field_def, evidence)
        assert score > 0.80

    def test_no_evidence_required_returns_zero(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        score = scorer.score_field(field_def, {})
        assert score == 0.0

    def test_no_evidence_optional_returns_zero(self, scorer):
        field_def = FieldDefinition(name="invoice_number", type="string", required=False)
        score = scorer.score_field(field_def, {})
        assert score == 0.0

    def test_validation_error_reduces_confidence(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": 0.96, "has_total_keyword": True}
        issues_no_error = []
        issues_with_error = [
            {"field": "total_amount", "severity": "error", "code": "amt001", "message": "missing"}
        ]
        score_no = scorer.score_field(field_def, evidence, issues_no_error)
        score_yes = scorer.score_field(field_def, evidence, issues_with_error)
        assert score_yes < score_no
        # Penalty of 0.20 applied to validation component
        assert score_no - score_yes == pytest.approx(0.20 * 0.15, abs=1e-4)

    def test_validation_warning_reduces_less_than_error(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": 0.96, "has_total_keyword": True}
        base = scorer.score_field(field_def, evidence, [])
        with_warn = scorer.score_field(
            field_def, evidence,
            [{"field": "total_amount", "severity": "warning", "code": "x", "message": "x"}],
        )
        with_err = scorer.score_field(
            field_def, evidence,
            [{"field": "total_amount", "severity": "error", "code": "x", "message": "x"}],
        )
        assert base > with_warn > with_err

    def test_score_clamped_to_one(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": 2.0, "has_total_keyword": True}
        score = scorer.score_field(field_def, evidence)
        assert score <= 1.0

    def test_score_clamped_to_zero(self, scorer):
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": -1.0}
        issues = [{"field": "total_amount", "severity": "error", "code": "x", "message": "x"}]
        score = scorer.score_field(field_def, evidence, issues)
        assert score >= 0.0

    def test_labeled_registration_scores_higher(self, scorer):
        field_def = FieldDefinition(name="issuer_registration_number", type="string", required=True)
        labeled = {"ocr_confidence": 0.90, "method": "labeled"}
        isolated = {"ocr_confidence": 0.90, "method": "isolated"}
        assert scorer.score_field(field_def, labeled) > scorer.score_field(field_def, isolated)


class TestScoreAll:
    def test_scores_all_fields_with_evidence(self, scorer, invoice_jp_schema):
        evidence = {
            "issuer_name": {"ocr_confidence": 0.90, "near_registration_number": True, "position": "bottom"},
            "issuer_registration_number": {"ocr_confidence": 0.97, "method": "labeled"},
            "transaction_date": {"ocr_confidence": 0.96, "has_date_label": True},
            "total_amount": {"ocr_confidence": 0.96, "has_total_keyword": True},
        }
        scores = scorer.score_all(invoice_jp_schema, evidence)
        assert "issuer_name" in scores
        assert "issuer_registration_number" in scores
        assert "transaction_date" in scores
        assert "total_amount" in scores
        # Optional field with no evidence is omitted
        assert "invoice_number" not in scores

    def test_empty_evidence_required_fields_zero(self, scorer, invoice_jp_schema):
        scores = scorer.score_all(invoice_jp_schema, {})
        # Required fields present with 0.0
        assert scores.get("issuer_registration_number") == 0.0
        assert scores.get("transaction_date") == 0.0
        assert scores.get("total_amount") == 0.0

    def test_optional_field_omitted_when_no_evidence(self, scorer, invoice_jp_schema):
        scores = scorer.score_all(invoice_jp_schema, {})
        assert "invoice_number" not in scores

    def test_with_validation_issues(self, scorer, invoice_jp_schema):
        evidence = {
            "total_amount": {"ocr_confidence": 0.96, "has_total_keyword": True},
        }
        issues = [{"field": "total_amount", "severity": "error", "code": "amt001", "message": "missing"}]
        scores = scorer.score_all(invoice_jp_schema, evidence, issues)
        assert scores["total_amount"] < 1.0


class TestOverallConfidence:
    def test_average_of_field_scores(self, scorer):
        scores = {"field_a": 0.80, "field_b": 0.90, "field_c": 0.70}
        assert scorer.overall_confidence(scores) == pytest.approx(0.80, abs=1e-4)

    def test_empty_scores_returns_zero(self, scorer):
        assert scorer.overall_confidence({}) == 0.0

    def test_single_field(self, scorer):
        assert scorer.overall_confidence({"x": 0.75}) == pytest.approx(0.75, abs=1e-4)


class TestCustomWeights:
    def test_custom_weights_override_defaults(self):
        custom = SchemaConfidenceScorer(weights={"ocr": 0.40, "regex": 0.30, "layout": 0.20, "validation": 0.10})
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": 0.96, "has_total_keyword": True}
        score_custom = custom.score_field(field_def, evidence)
        score_default = SchemaConfidenceScorer().score_field(field_def, evidence)
        # Different weights → different score
        assert score_custom != score_default

    def test_validation_penalty_uses_custom_validation_weight(self):
        custom = SchemaConfidenceScorer(weights={"ocr": 0.50, "regex": 0.20, "layout": 0.15, "validation": 0.15})
        field_def = FieldDefinition(name="total_amount", type="money", required=True)
        evidence = {"ocr_confidence": 0.96, "has_total_keyword": True}
        issues = [{"field": "total_amount", "severity": "error", "code": "x", "message": "x"}]
        base = custom.score_field(field_def, evidence, [])
        penalized = custom.score_field(field_def, evidence, issues)
        assert base - penalized == pytest.approx(0.20 * 0.15, abs=1e-4)
