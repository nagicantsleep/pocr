#!/usr/bin/env python3
"""Test that the evaluation script runs without errors."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.evaluate_invoice_extraction import (
    load_fixtures,
    run_evaluation,
    get_category,
    evaluate_field,
)


def test_load_fixtures():
    """Test that fixtures load correctly."""
    fixtures = load_fixtures()
    assert len(fixtures) >= 50, f"Expected at least 50 fixtures, got {len(fixtures)}"
    # Check structure
    for fix in fixtures:
        assert "name" in fix, f"Fixture missing 'name': {fix}"
        assert "ocr_lines" in fix, f"Fixture missing 'ocr_lines': {fix['name']}"
        assert "expected" in fix, f"Fixture missing 'expected': {fix['name']}"
        # Verify ocr_lines have required keys
        for line in fix["ocr_lines"]:
            assert "text" in line
            assert "confidence" in line
            assert "bbox" in line
    print(f"  OK: Loaded {len(fixtures)} fixtures all with valid structure")


def test_get_category():
    """Test category extraction from fixture names."""
    assert get_category("simple_001") == "simple"
    assert get_category("multiline_001") == "multiline"
    assert get_category("non_invoice_001") == "non_invoice"
    assert get_category("edge_no_table") == "edge"
    assert get_category("poor_quality_001") == "poor_quality"
    assert get_category("mixed_tax_001") == "mixed_tax"
    assert get_category("receipt_001") == "receipt"
    print("  OK: Categories map correctly")


def test_evaluate_field():
    """Test field evaluation logic."""
    assert evaluate_field(None, None) is True
    assert evaluate_field("test", "test") is True
    assert evaluate_field("test", None) is False
    assert evaluate_field(None, "test") is False
    assert evaluate_field(123, 123) is True
    assert evaluate_field(123, "123") is True
    assert evaluate_field("T123", "T456") is False
    print("  OK: Field evaluation logic works")


def test_evaluation_runs():
    """Test the full evaluation runs without errors."""
    run_evaluation()
    print("  OK: Full evaluation ran successfully")


if __name__ == "__main__":
    test_load_fixtures()
    test_get_category()
    test_evaluate_field()
    test_evaluation_runs()
    print("\nAll tests passed.")
