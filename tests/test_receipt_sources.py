"""Tests for app.services.extraction_kernel.receipt_sources — receipt-jp source functions."""

from app.services.extraction_kernel.receipt_sources import (
    find_change_amount,
    find_payment_method,
    find_store_address,
    find_store_phone,
    find_subtotal,
    find_tax_amount,
)


def _make_line(text: str, line_no: int = 1, confidence: float = 0.95,
               x: float = 0, y: float = 100) -> dict:
    return {
        "text": text,
        "confidence": confidence,
        "bbox": {
            "top_left": [x, y],
            "bottom_right": [x + 200, y + 20],
        },
        "line_no": line_no,
    }


class TestFindStorePhone:
    def test_labeled_phone(self):
        candidates = find_store_phone("TEL: 03-1234-5678")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "03-1234-5678"

    def test_phone_with_prefix(self):
        candidates = find_store_phone("電話: 06-9876-5432")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "06-9876-5432"

    def test_no_match(self):
        candidates = find_store_phone("これはテストです")
        assert candidates == []

    def test_four_digit_area_code(self):
        candidates = find_store_phone("TEL: 0120-123-456")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "0120-123-456"


class TestFindPaymentMethod:
    def test_cash_with_label(self):
        candidates = find_payment_method("お支払い方法: 現金")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "現金"

    def test_credit_card_keyword(self):
        candidates = find_payment_method("クレジットカード")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "クレジットカード"

    def test_paypay(self):
        candidates = find_payment_method("お支払い: PayPay")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "PayPay"

    def test_no_match(self):
        candidates = find_payment_method("これはテストです")
        assert candidates == []


class TestFindChangeAmount:
    def test_basic_change(self):
        candidates = find_change_amount("お釣り ¥500")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 500

    def test_change_with_fullwidth(self):
        candidates = find_change_amount("釣銭 ￥1,000")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 1000

    def test_no_match(self):
        candidates = find_change_amount("これはテストです")
        assert candidates == []


class TestFindTaxAmount:
    def test_basic_tax(self):
        candidates = find_tax_amount("消費税 ¥1,000")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 1000

    def test_tax_with_label(self):
        candidates = find_tax_amount("内税 ¥500")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 500

    def test_no_match(self):
        candidates = find_tax_amount("これはテストです")
        assert candidates == []


class TestFindSubtotal:
    def test_basic_subtotal(self):
        candidates = find_subtotal("小計 ¥9,000")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 9000

    def test_subtotal_no_tax(self):
        candidates = find_subtotal("税抜合計 ¥10,000")
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 10000

    def test_no_match(self):
        candidates = find_subtotal("これはテストです")
        assert candidates == []


class TestFindStoreAddress:
    def test_labeled_address(self):
        lines = [_make_line("住所: 東京都渋谷区神宮前1-2-3")]
        candidates = find_store_address(lines)
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "東京都渋谷区神宮前1-2-3"

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        candidates = find_store_address(lines)
        assert candidates == []
