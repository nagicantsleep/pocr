"""Tests for app.utils.dates — Japanese date normalization."""

from app.utils.dates import normalize_japanese_date


class TestNormalizeJapaneseDate:
    def test_western_slash(self):
        assert normalize_japanese_date("2026/06/25") == "2026-06-25"

    def test_western_dash(self):
        assert normalize_japanese_date("2026-06-25") == "2026-06-25"

    def test_western_japanese(self):
        assert normalize_japanese_date("2026年6月25日") == "2026-06-25"

    def test_reiwa(self):
        assert normalize_japanese_date("令和8年6月25日") == "2026-06-25"

    def test_reiwa_year_one(self):
        # 令和元年 = 令和1年 = 2019
        assert normalize_japanese_date("令和元年6月25日") is None

    def test_reiwa_one_explicit(self):
        assert normalize_japanese_date("令和1年6月25日") == "2019-06-25"

    def test_reiwa_jan_first(self):
        assert normalize_japanese_date("令和1年1月1日") == "2019-01-01"

    def test_heisei(self):
        # 平成1年 = 1989
        assert normalize_japanese_date("平成1年1月8日") == "1989-01-08"

    def test_western_single_digit_month_day(self):
        assert normalize_japanese_date("2026/1/5") == "2026-01-05"

    def test_western_no_separator(self):
        # "20260625" won't match — no separator
        assert normalize_japanese_date("20260625") is None

    def test_western_year_only(self):
        assert normalize_japanese_date("2026年") is None

    def test_empty_string(self):
        assert normalize_japanese_date("") is None

    def test_none(self):
        assert normalize_japanese_date(None) is None  # type: ignore[arg-type]

    def test_garbage(self):
        assert normalize_japanese_date("not a date") is None

    def test_invalid_month(self):
        assert normalize_japanese_date("2026/13/01") is None

    def test_invalid_day(self):
        assert normalize_japanese_date("2026/06/32") is None

    def test_reiwa_with_slash_not_japanese(self):
        # Era format only matches 年月日 separators, not slashes
        assert normalize_japanese_date("令和8/6/25") is None

    def test_western_with_trailing_text(self):
        # Regex anchors at start, so trailing text is ignored if it doesn't break the match
        assert normalize_japanese_date("2026年6月25日(水)") == "2026-06-25"

    def test_leading_trailing_whitespace(self):
        assert normalize_japanese_date("  2026/06/25  ") == "2026-06-25"

    def test_reiwa_large_year(self):
        # 令和99年 = 2117
        assert normalize_japanese_date("令和99年1月1日") == "2117-01-01"
