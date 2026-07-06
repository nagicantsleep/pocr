"""Tests for app.services.invoice_extractor — full extraction pipeline."""

from app.services.invoice_extractor import extract_invoice


def _make_ocr_line(text: str, confidence: float = 0.95,
                   x: float = 0, y: float = 100) -> dict:
    return {
        "text": text,
        "confidence": confidence,
        "bbox": {
            "top_left": [x, y],
            "bottom_right": [x + 200, y + 20],
        },
        "type": "text",
        "polygon": [[x, y], [x + 200, y], [x + 200, y + 20], [x, y + 20]],
    }


class TestExtractInvoice:
    def test_extracts_simple_invoice(self):
        ocr_results = [
            _make_ocr_line("株式会社 ABC", y=50),
            _make_ocr_line("発行日 2026/06/25", y=80),
            _make_ocr_line("請求書番号 INV-001", y=110),
            _make_ocr_line("登録番号 T1234567890123", y=140),
            _make_ocr_line("ご請求金額 ¥110,000", y=400),
            _make_ocr_line("消費税 10% 10,000", y=430),
        ]
        response = extract_invoice(ocr_results)
        assert response.status == "success"
        assert response.invoice.issuer_registration_number == "T1234567890123"
        assert response.invoice.transaction_date == "2026-06-25"
        assert response.invoice.invoice_number == "INV-001"
        assert response.invoice.total_amount == 110000
        assert response.invoice.issuer_name == "株式会社 ABC"
        assert response.line_items_status == "not_extracted"
        assert response.document_type == "qualified_invoice"

    def test_empty_ocr(self):
        response = extract_invoice([])
        assert response.status == "success"
        assert response.invoice.issuer_registration_number is None
        assert response.invoice.total_amount is None
        assert response.invoice.issuer_name is None
        assert response.needs_review is True

    def test_missing_registration_number_sets_review(self):
        ocr_results = [
            _make_ocr_line("株式会社 ABC", y=50),
            _make_ocr_line("発行日 2026/06/25", y=80),
        ]
        response = extract_invoice(ocr_results)
        assert response.needs_review is True
        assert response.document_type is None

    def test_low_confidence_sets_review(self):
        ocr_results = [
            _make_ocr_line("株式会社 ABC", y=50),
            _make_ocr_line("発行日 2026/06/25", y=80),
            _make_ocr_line("登録番号 T1234567890123", confidence=0.70, y=110),
        ]
        response = extract_invoice(ocr_results, review_threshold=0.85)
        # registration number confidence computed from OCR + regex
        assert response.needs_review is True

    def test_custom_review_threshold(self):
        ocr_results = [
            _make_ocr_line("登録番号 T1234567890123", y=50),
            _make_ocr_line("発行日 2026/06/25", y=80),
            _make_ocr_line("ご請求金額 ¥110,000", y=400),
        ]
        response = extract_invoice(ocr_results, review_threshold=0.50)
        # With low threshold, and labeled reg no + date + total, should not need review
        assert response.needs_review is False

    def test_ocr_summary(self):
        ocr_results = [
            _make_ocr_line("テスト", confidence=0.95),
            _make_ocr_line("テスト2", confidence=0.85),
        ]
        response = extract_invoice(ocr_results)
        assert response.ocr is not None
        assert response.ocr["summary"]["total_lines"] == 2
        assert response.ocr["summary"]["avg_confidence"] == 0.90

    def test_request_id(self):
        ocr_results = [_make_ocr_line("テスト")]
        response = extract_invoice(ocr_results, request_id="custom-id")
        assert response.request_id == "custom-id"

    def test_request_id_generated(self):
        ocr_results = [_make_ocr_line("テスト")]
        response = extract_invoice(ocr_results)
        assert response.request_id is not None
        assert response.request_id != "custom-id"
