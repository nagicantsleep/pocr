"""Tests for app.utils.tax — Japanese invoice tax rounding."""

import math
from app.utils.tax import expected_tax


class TestExpectedTax:
    def test_10_percent_round(self):
        result = expected_tax(100000, "10%", "round")
        assert result == [10000]

    def test_10_percent_floor(self):
        result = expected_tax(100000, "10%", "floor")
        assert result == [10000]

    def test_10_percent_ceil(self):
        result = expected_tax(100000, "10%", "ceil")
        assert result == [10000]

    def test_8_percent_round(self):
        result = expected_tax(100000, "8%", "round")
        assert result == [8000]

    def test_8_percent_floor(self):
        result = expected_tax(100000, "8%", "floor")
        assert result == [8000]

    def test_8_percent_ceil(self):
        result = expected_tax(100000, "8%", "ceil")
        assert result == [8000]

    def test_unknown_returns_three_values(self):
        result = expected_tax(100000, "10%", "unknown")
        assert result == [10000]

    def test_unknown_with_fractional_tax(self):
        # 1000 * 0.08 = 80.0, all roundings same
        result = expected_tax(1000, "8%", "unknown")
        assert result == [80]

    def test_unknown_different_roundings(self):
        # 333 * 0.10 = 33.3 → floor=33, ceil=34, round=33
        result = expected_tax(333, "10%", "unknown")
        assert sorted(result) == [33, 34]

    def test_unknown_deduplicates(self):
        # 500 * 0.10 = 50.0, all same → deduplicated to [50]
        result = expected_tax(500, "10%", "unknown")
        assert result == [50]

    def test_invalid_rate(self):
        result = expected_tax(100000, "5%", "round")
        assert result == []

    def test_zero_subtotal(self):
        result = expected_tax(0, "10%", "round")
        assert result == [0]

    def test_zero_subtotal_unknown(self):
        result = expected_tax(0, "10%", "unknown")
        assert result == [0]
