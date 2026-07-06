"""Tests for app.services.invoice_rules — Japanese regex extraction."""

from app.services.invoice_rules import (
    find_registration_number,
    find_total_amount,
    find_tax_amounts,
    find_dates,
    find_invoice_number,
    find_issuer_name,
    find_recipient_name,
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


class TestFindRegistrationNumber:
    def test_labeled_pattern(self):
        candidates = find_registration_number(
            "適格請求書発行事業者登録番号:T1234567890123"
        )
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "T1234567890123"
        assert candidates[0]["method"] == "labeled"

    def test_shorter_label(self):
        candidates = find_registration_number(
            "登録番号 T9876543210987"
        )
        assert len(candidates) >= 1
        assert candidates[0]["value"] == "T9876543210987"

    def test_isolated_fallback(self):
        candidates = find_registration_number(
            "登録番号は T1111111111111 です"
        )
        assert len(candidates) >= 1

    def test_no_match(self):
        candidates = find_registration_number("これはテストです")
        assert candidates == []

    def test_invalid_format(self):
        candidates = find_registration_number("T12345")
        assert candidates == []

    def test_full_width_t(self):
        # Full-width Ｔ should be normalized
        candidates = find_registration_number("登録番号:Ｔ1234567890123")
        assert candidates[0]["value"] == "T1234567890123"


class TestFindTotalAmount:
    def test_total_keyword(self):
        lines = [_make_line("合計金額 ¥110,000")]
        candidates = find_total_amount(lines)
        assert len(candidates) >= 1
        assert candidates[0]["value"] == 110000

    def test_gokyuu(self):
        lines = [_make_line("ご請求金額 110,000")]
        candidates = find_total_amount(lines)
        assert candidates[0]["value"] == 110000

    def test_tax_included(self):
        lines = [_make_line("税込合計 ￥110,000")]
        candidates = find_total_amount(lines)
        assert candidates[0]["value"] == 110000

    def test_multiple_lines_picks_first(self):
        lines = [
            _make_line("小計 100,000"),
            _make_line("合計 110,000"),
        ]
        candidates = find_total_amount(lines)
        assert len(candidates) >= 1

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        assert find_total_amount(lines) == []


class TestFindTaxAmounts:
    def test_8_percent(self):
        lines = [_make_line("消費税 8% 8,000")]
        result = find_tax_amounts(lines)
        assert len(result["8%"]) == 1
        assert result["8%"][0]["value"] == 8000

    def test_10_percent(self):
        lines = [_make_line("消費税 10% 10,000")]
        result = find_tax_amounts(lines)
        assert len(result["10%"]) == 1
        assert result["10%"][0]["value"] == 10000

    def test_full_width_percent(self):
        lines = [_make_line("消費税 １０％ 10,000")]
        result = find_tax_amounts(lines)
        assert len(result["10%"]) == 1

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        result = find_tax_amounts(lines)
        assert result["8%"] == []
        assert result["10%"] == []


class TestFindDates:
    def test_western_slash(self):
        lines = [_make_line("請求日 2026/06/25")]
        candidates = find_dates(lines)
        assert candidates[0]["value"] == "2026-06-25"

    def test_western_japanese_format(self):
        lines = [_make_line("発行日 2026年6月25日")]
        candidates = find_dates(lines)
        assert candidates[0]["value"] == "2026-06-25"

    def test_reiwa(self):
        lines = [_make_line("発行日 令和8年6月25日")]
        candidates = find_dates(lines)
        assert candidates[0]["value"] == "2026-06-25"

    def test_payment_due(self):
        lines = [_make_line("支払期日 2026/07/31")]
        candidates = find_dates(lines)
        assert candidates[0]["value"] == "2026-07-31"

    def test_fallback_any_date(self):
        lines = [_make_line("何らかの日付 2026/06/25")]
        candidates = find_dates(lines)
        # Falls back because "日付" is in _DATE_LABELS
        assert candidates[0]["value"] == "2026-06-25"

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        assert find_dates(lines) == []


class TestFindInvoiceNumber:
    def test_japanese_label(self):
        lines = [_make_line("請求書番号 INV-2026-001")]
        candidates = find_invoice_number(lines)
        assert candidates[0]["value"] == "INV-2026-001"

    def test_with_colon(self):
        lines = [_make_line("請求No.: 001234")]
        candidates = find_invoice_number(lines)
        assert candidates[0]["value"] == "001234"

    def test_english_label(self):
        lines = [_make_line("Invoice No. 2026-001")]
        candidates = find_invoice_number(lines)
        assert candidates[0]["value"] == "2026-001"

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        assert find_invoice_number(lines) == []


class TestFindIssuerName:
    def test_kabushiki(self):
        lines = [_make_line("株式会社 ABC")]
        candidates = find_issuer_name(lines)
        assert len(candidates) >= 1
        assert "株式会社" in candidates[0]["value"]

    def test_godo(self):
        lines = [_make_line("合同会社 XYZ")]
        candidates = find_issuer_name(lines)
        assert len(candidates) >= 1

    def test_excludes_recipient_keyword(self):
        lines = [_make_line("株式会社 ABC 御中")]
        candidates = find_issuer_name(lines)
        # Should filter out lines with 御中
        assert len(candidates) == 0

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        assert find_issuer_name(lines) == []


class TestFindRecipientName:
    def test_onchu(self):
        lines = [_make_line("株式会社 XYZ 御中")]
        candidates = find_recipient_name(lines)
        assert len(candidates) >= 1
        assert "株式会社 XYZ" in candidates[0]["value"]

    def test_sama(self):
        lines = [_make_line("山田商事 様")]
        candidates = find_recipient_name(lines)
        assert candidates[0]["value"] == "山田商事"

    def test_no_match(self):
        lines = [_make_line("これはテストです")]
        assert find_recipient_name(lines) == []
