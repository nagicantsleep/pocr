from __future__ import annotations

from dataclasses import dataclass

from app.utils.japanese_text import is_japanese_char

# Unicode block definitions
_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_CJK = (0x4E00, 0x9FFF)
_HANGUL = (0xAC00, 0xD7AF)
_LATIN = (0x0020, 0x007F)

# Common Japanese function words for dictionary-based detection
_JP_COMMON = ("です", "ます", "の", "は", "が", "を", "に", "で", "と", "も")


def _in_range(ch: str, lo: int, hi: int) -> bool:
    return lo <= ord(ch) <= hi


def _count_chars(text: str, lo: int, hi: int) -> int:
    return sum(1 for ch in text if lo <= ord(ch) <= hi)


@dataclass
class LanguageDetection:
    """Language detection result."""

    language: str  # ISO 639-1 code: "ja", "en", "zh", "ko", etc.
    confidence: float  # 0.0 - 1.0
    script: str  # "japanese", "chinese", "korean", "latin", "mixed"


def detect_language(text: str, locale_hint: str | None = None) -> LanguageDetection:
    """Detect the primary language of OCR text.

    Methods:
    1. Script-based: count characters in Unicode ranges
    2. Dictionary: common Japanese words
    3. locale_hint: if provided, boost that language's score
    """
    if not text or not text.strip():
        return LanguageDetection(language="unknown", confidence=0.0, script="mixed")

    # Strip whitespace for counting
    content = text.strip()
    total = len(content)
    if total == 0:
        return LanguageDetection(language="unknown", confidence=0.0, script="mixed")

    hiragana_count = _count_chars(content, *_HIRAGANA)
    katakana_count = _count_chars(content, *_KATAKANA)
    cjk_count = _count_chars(content, *_CJK)
    hangul_count = _count_chars(content, *_HANGUL)
    latin_count = _count_chars(content, *_LATIN)

    jp_kana_count = hiragana_count + katakana_count

    # Scores for each language
    scores: dict[str, float] = {"ja": 0.0, "en": 0.0, "zh": 0.0, "ko": 0.0}

    # --- Script-based scoring ---
    if jp_kana_count > 0:
        # Hiragana/Katakana are definitive markers of Japanese
        scores["ja"] = min(jp_kana_count / max(total * 0.05, 1), 1.0)
        if cjk_count > 0:
            scores["ja"] = min(scores["ja"] + 0.3, 1.0)
    elif cjk_count > 0 and hangul_count == 0:
        # CJK without kana — could be Japanese or Chinese.
        # Mixed CJK+Latin is a common Japanese business-doc pattern (e.g. "Invoice No. 請求書"),
        # so boost Japanese over Chinese when Latin is also present.
        cjk_ratio = cjk_count / max(total * 0.1, 1)
        if latin_count > 0:
            scores["ja"] = min(cjk_ratio * 0.85, 0.7)
            scores["zh"] = min(cjk_ratio * 0.75, 0.6)
        else:
            scores["zh"] = min(cjk_ratio, 0.7)
            scores["ja"] = min(cjk_ratio * 0.7, 0.5)

    if hangul_count > 0:
        scores["ko"] = min(hangul_count / max(total * 0.1, 1), 1.0)

    if latin_count > 0 and jp_kana_count == 0 and cjk_count == 0 and hangul_count == 0:
        scores["en"] = min(latin_count / max(total * 0.3, 1), 1.0)
    elif latin_count > 0 and cjk_count > 0:
        # Mixed Latin + CJK: also give English a small score for mixed docs
        scores["en"] = min(latin_count / max(total * 0.5, 1) * 0.5, 0.4)

    # --- Dictionary-based boost for Japanese ---
    if scores["ja"] > 0:
        word_hits = sum(1 for w in _JP_COMMON if w in content)
        if word_hits > 0:
            scores["ja"] = min(scores["ja"] + word_hits * 0.05, 1.0)

    # --- locale_hint boost ---
    if locale_hint:
        hint_lower = locale_hint.lower()
        if hint_lower in scores:
            scores[hint_lower] = min(scores[hint_lower] + 0.15, 1.0)

    # --- Determine winner ---
    best_lang = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_lang]

    if best_score < 0.01:
        return LanguageDetection(language="unknown", confidence=0.0, script="mixed")

    # Determine script label.
    # Japanese family: hiragana, katakana, CJK are all "japanese" script.
    # "mixed" only when non-Japanese families coexist (e.g. CJK+Latin without kana).
    jp_family_count = jp_kana_count + cjk_count
    non_jp_scripts = (hangul_count > 0, latin_count > 0)
    has_mixed = jp_family_count > 0 and any(non_jp_scripts)

    if best_lang == "ja" and not has_mixed:
        script = "japanese"
    elif best_lang == "ja":
        script = "mixed"
    elif best_lang == "zh":
        script = "chinese"
    elif best_lang == "ko":
        script = "korean"
    elif best_lang == "en":
        script = "latin"
    else:
        script = "mixed"

    return LanguageDetection(
        language=best_lang,
        confidence=round(best_score, 2),
        script=script,
    )
