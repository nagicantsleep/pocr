from __future__ import annotations

from app.services.classifier import classify_document


class TestClassifyDocument:
    def test_qualified_invoice_keyword(self):
        doc_type, confidence = classify_document("適格請求書 発行日 2024年1月 T1234567890123")
        assert doc_type == "qualified_invoice"
        assert confidence >= 0.90

    def test_qualified_invoice_reg_number(self):
        doc_type, confidence = classify_document("登録番号 T1234567890123 請求書")
        assert doc_type == "qualified_invoice"
        assert confidence >= 0.90

    def test_receipt_keyword(self):
        doc_type, confidence = classify_document("領収書 店舗名 イオン")
        assert doc_type == "receipt"
        assert confidence >= 0.85

    def test_receipt_resheeto(self):
        doc_type, confidence = classify_document("レシート 合計 ¥500 令和6年3月1日")
        assert doc_type == "receipt"
        assert confidence >= 0.90

    def test_unknown_english(self):
        doc_type, confidence = classify_document("Invoice for services rendered. Total $100.")
        assert doc_type == "unknown"
        assert confidence < 0.50

    def test_invoice_keyword_boost_jp_date(self):
        doc_type, confidence = classify_document("適格請求書 令和6年4月1日 T9876543210123")
        assert doc_type == "qualified_invoice"
        assert confidence >= 0.95

    def test_empty_text(self):
        doc_type, confidence = classify_document("")
        assert doc_type == "unknown"
        assert confidence == 0.30

    def test_locale_hint_boost(self):
        doc_type, confidence = classify_document("領収書 ¥1000", locale_hint="ja")
        assert doc_type == "receipt"
        assert confidence >= 0.90

    def test_invoice_is_keyword(self):
        doc_type, confidence = classify_document("インボイス制度について説明")
        assert doc_type == "qualified_invoice"
        assert confidence >= 0.95
