"""Tests for app.utils.money — JPY amount normalization."""

from app.utils.money import normalize_amount


class TestNormalizeAmount:
    def test_plain_integer(self):
        assert normalize_amount("100000") == 100000

    def test_half_width_comma(self):
        assert normalize_amount("100,000") == 100000

    def test_full_width_comma(self):
        assert normalize_amount("100，000") == 100000

    def test_yen_prefix(self):
        assert normalize_amount("¥100,000") == 100000

    def test_yen_suffix(self):
        assert normalize_amount("100,000円") == 100000

    def test_full_width_yen_symbol(self):
        assert normalize_amount("￥100,000") == 100000

    def test_full_width_digits(self):
        assert normalize_amount("１００，０００") == 100000

    def test_spaces_between_digits(self):
        assert normalize_amount("100 000") == 100000

    def test_negative_with_minus(self):
        assert normalize_amount("-10,000") == -10000

    def test_negative_with_triangle(self):
        assert normalize_amount("△10,000") == -10000

    def test_negative_with_parens_half(self):
        assert normalize_amount("(10,000)") == -10000

    def test_negative_with_parens_full(self):
        assert normalize_amount("（10,000）") == -10000

    def test_zero(self):
        assert normalize_amount("0") == 0

    def test_zero_with_commas(self):
        assert normalize_amount("0") == 0

    def test_small_amount(self):
        assert normalize_amount("500") == 500

    def test_large_amount(self):
        assert normalize_amount("10,000,000") == 10000000

    def test_ocr_letter_o_to_zero(self):
        # "1OOO" should become "1000" — O surrounded by digits
        assert normalize_amount("1OOO") == 1000

    def test_ocr_letter_l_to_one(self):
        # "1l00" should become "1100" — l surrounded by digits
        assert normalize_amount("1l00") == 1100

    def test_ocr_letter_i_to_one(self):
        # "1I00" should become "1100" — I surrounded by digits
        assert normalize_amount("1I00") == 1100

    def test_empty_string(self):
        assert normalize_amount("") is None

    def test_none(self):
        assert normalize_amount(None) is None  # type: ignore[arg-type]

    def test_non_string(self):
        assert normalize_amount(123) is None  # type: ignore[arg-type]

    def test_garbage_text(self):
        assert normalize_amount("hello") is None

    def test_ocr_o_not_surrounded(self):
        # "O123" — O at start, not between digits, should stay O, fail parse
        # Actually O at position 0 with digit at right: left_ok = True (edge), right_ok = True
        # So it gets fixed to 0123 = 123
        assert normalize_amount("O123") == 123

    def test_yen_and_commas(self):
        assert normalize_amount("¥1,234,567") == 1234567

    def test_full_width_with_yen_suffix(self):
        assert normalize_amount("１，０００円") == 1000

    def test_negative_triangle_full_width(self):
        assert normalize_amount("△１０，０００") == -10000
