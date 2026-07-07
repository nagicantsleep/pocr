from __future__ import annotations

import pytest

from app.services.lang_detect import LanguageDetection, detect_language


class TestDetectLanguage:
    def test_japanese_hiragana(self):
        result = detect_language("これはテストです")
        assert result.language == "ja"
        assert result.confidence >= 0.8
        assert result.script == "japanese"

    def test_japanese_katakana(self):
        result = detect_language("テスト用ドキュメント")
        assert result.language == "ja"
        assert result.confidence >= 0.8
        assert result.script == "japanese"

    def test_english_text(self):
        result = detect_language("This is a test document")
        assert result.language == "en"
        assert result.confidence >= 0.7
        assert result.script == "latin"

    def test_mixed_japanese_english(self):
        result = detect_language("Invoice No. 12345 請求書")
        assert result.language in ("ja", "mixed")
        assert result.confidence >= 0.5

    def test_empty_string(self):
        result = detect_language("")
        assert result.language == "unknown"
        assert result.confidence == 0.0

    def test_locale_hint_boosts_japanese(self):
        """locale_hint='ja' should boost Japanese score for ambiguous text."""
        # Text with some kanji but no kana
        result_no_hint = detect_language("請求書")
        result_with_hint = detect_language("請求書", locale_hint="ja")
        assert result_with_hint.confidence >= result_no_hint.confidence

    def test_chinese_text_no_kana(self):
        """Pure CJK without hiragana/katakana should detect as Chinese."""
        result = detect_language("这是一份测试文件")
        assert result.language == "zh"
        assert result.confidence >= 0.5

    def test_result_is_language_detection(self):
        result = detect_language("hello world")
        assert isinstance(result, LanguageDetection)
        assert hasattr(result, "language")
        assert hasattr(result, "confidence")
        assert hasattr(result, "script")
