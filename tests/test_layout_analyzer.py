"""Tests for layout analyzer and Japanese text utilities."""

import json
import os

import pytest

from app.services.layout_analyzer import analyze_layout
from app.utils.japanese_text import (
    classify_line,
    is_japanese_char,
    merge_fragments,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "ocr_outputs")


def _load_fixture(name: str) -> list[dict]:
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


# --- Japanese text utilities ---


class TestIsJapaneseChar:
    def test_hiragana(self):
        assert is_japanese_char("あ")
        assert is_japanese_char("の")

    def test_katakana(self):
        assert is_japanese_char("ア")
        assert is_japanese_char("ン")

    def test_cjk(self):
        assert is_japanese_char("漢")
        assert is_japanese_char("字")

    def test_latin(self):
        assert not is_japanese_char("A")
        assert not is_japanese_char("1")

    def test_punctuation(self):
        # CJK Symbols and Punctuation
        assert is_japanese_char("、")
        assert is_japanese_char("。")


class TestClassifyLine:
    def test_totals_keyword(self):
        assert classify_line("合計 110,000") == "totals_candidate"
        assert classify_line("小計 100,000") == "totals_candidate"
        assert classify_line("消費税 10% 10,000") == "totals_candidate"
        assert classify_line("税込金額") == "totals_candidate"

    def test_recipient(self):
        assert classify_line("株式会社テスト御中") == "recipient"
        assert classify_line("田中様") == "recipient"

    def test_issuer_registration(self):
        assert classify_line("登録番号 T1234567890123") == "issuer"

    def test_header(self):
        assert classify_line("請求書 番号 #12345") == "header"

    def test_plain_text(self):
        assert classify_line(">Hello World") == "text"


class TestMergeFragments:
    def test_close_fragments_merge(self):
        lines = [
            {"text": "登録", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "番号", "confidence": 0.94, "bbox": {"top_left": [55, 10], "bottom_right": [95, 30]}},
        ]
        result = merge_fragments(lines)
        assert len(result) == 1
        assert result[0]["text"] == "登録番号"

    def test_distant_fragments_stay_separate(self):
        lines = [
            {"text": "Hello", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "World", "confidence": 0.94, "bbox": {"top_left": [200, 10], "bottom_right": [250, 30]}},
        ]
        result = merge_fragments(lines)
        assert len(result) == 2

    def test_different_rows_stay_separate(self):
        lines = [
            {"text": "Line1", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "Line2", "confidence": 0.94, "bbox": {"top_left": [10, 100], "bottom_right": [50, 120]}},
        ]
        result = merge_fragments(lines)
        assert len(result) == 2

    def test_empty_input(self):
        assert merge_fragments([]) == []


# --- Layout analyzer ---


class TestLayoutAnalyzer:
    def test_sorting_order(self):
        """Lines should be sorted top-to-bottom, left-to-right."""
        ocr_results = [
            {"text": "B", "confidence": 0.95, "bbox": {"top_left": [200, 10], "bottom_right": [250, 30]}},
            {"text": "A", "confidence": 0.95, "bbox": {"top_left": [50, 10], "bottom_right": [100, 30]}},
            {"text": "C", "confidence": 0.95, "bbox": {"top_left": [50, 50], "bottom_right": [100, 70]}},
        ]
        result = analyze_layout(ocr_results)
        texts = [l["text"] for l in result["lines"]]
        assert texts == ["A", "B", "C"]

    def test_line_numbers_sequential(self):
        ocr_results = [
            {"text": "X", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "Y", "confidence": 0.95, "bbox": {"top_left": [10, 50], "bottom_right": [50, 70]}},
        ]
        result = analyze_layout(ocr_results)
        line_nos = [l["line_no"] for l in result["lines"]]
        assert line_nos == [1, 2]

    def test_plain_text_multiline(self):
        ocr_results = [
            {"text": "Hello", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "World", "confidence": 0.95, "bbox": {"top_left": [10, 50], "bottom_right": [50, 70]}},
        ]
        result = analyze_layout(ocr_results)
        assert result["plain_text"] == "Hello\nWorld"

    def test_fragment_merge_in_layout(self):
        """Close fragments should be merged into a single line."""
        ocr_results = [
            {"text": "登録", "confidence": 0.95, "bbox": {"top_left": [10, 10], "bottom_right": [50, 30]}},
            {"text": "番号", "confidence": 0.94, "bbox": {"top_left": [55, 10], "bottom_right": [95, 30]}},
        ]
        result = analyze_layout(ocr_results)
        assert len(result["lines"]) == 1
        assert result["lines"][0]["text"] == "登録番号"

    def test_block_classification_simple_invoice(self):
        """Simple invoice fixture should classify blocks correctly."""
        ocr_results = _load_fixture("simple_invoice.json")
        result = analyze_layout(ocr_results)

        block_types = [b["type"] for b in result["blocks"]]
        assert "header" in block_types  # "請求書" at top
        assert "recipient" in block_types  # "御中" line
        assert "totals_candidate" in block_types  # "合計", "小計", etc.

    def test_table_candidates_detected(self):
        """Lines with numeric content should be detected as table candidates."""
        ocr_results = _load_fixture("simple_invoice.json")
        result = analyze_layout(ocr_results)

        assert len(result["table_candidates"]) > 0
        # Table candidates should have row_line_nos
        for tc in result["table_candidates"]:
            assert "header_line_nos" in tc
            assert "row_line_nos" in tc
            assert len(tc["row_line_nos"]) >= 1

    def test_no_table_invoice(self):
        """Invoice without line items should have no or minimal table candidates."""
        ocr_results = _load_fixture("no_table_invoice.json")
        result = analyze_layout(ocr_results)
        # Should still parse without error
        assert result["plain_text"]
        assert len(result["lines"]) == 5

    def test_non_invoice(self):
        """Non-invoice document should still produce valid layout."""
        ocr_results = _load_fixture("non_invoice.json")
        result = analyze_layout(ocr_results)
        assert result["plain_text"]
        assert len(result["lines"]) == 5
        # No totals keywords in this document
        block_types = [b["type"] for b in result["blocks"]]
        assert "totals_candidate" not in block_types

    def test_empty_input(self):
        result = analyze_layout([])
        assert result == {"plain_text": "", "lines": [], "blocks": [], "table_candidates": []}
