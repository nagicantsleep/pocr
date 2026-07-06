"""Tests for app.services.vendor_matcher — vendor matching and name normalization."""

from app.services.vendor_matcher import match_vendor, normalize_issuer_name


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

class TestNormalizeIssuerName:
    def test_kabushikigaisha(self):
        assert normalize_issuer_name("株式会社ABC") == "(株)ABC"

    def test_yuugen(self):
        assert normalize_issuer_name("有限会社XYZ") == "(有)XYZ"

    def test_goudou(self):
        assert normalize_issuer_name("合同会社ABC") == "(LLC)ABC"

    def test_short_kabu(self):
        assert normalize_issuer_name("㈱ABC") == "(株)ABC"

    def test_short_yuu(self):
        assert normalize_issuer_name("㈲ABC") == "(有)ABC"

    def test_fullwidth_alnum(self):
        # ABC → ABC
        assert normalize_issuer_name("ＡＢＣ") == "ABC"

    def test_whitespace_stripped(self):
        assert normalize_issuer_name(" 株式会社 ABC ") == "(株)ABC"

    def test_mixed_normalizations(self):
        assert normalize_issuer_name("  株式会社ＡＢＣ  ") == "(株)ABC"

    def test_already_normalized(self):
        assert normalize_issuer_name("(株)ABC") == "(株)ABC"


# ---------------------------------------------------------------------------
# Vendor matching
# ---------------------------------------------------------------------------

_VENDOR_DB = [
    {"name": "株式会社 ABC", "registration_number": "T1234567890123"},
    {"name": "有限会社XYZ", "registration_number": "T9999999999999"},
    {"name": "合同会社 DEF", "registration_number": "T5555555555555"},
]


class TestMatchVendor:
    def test_exact_registration_match(self):
        result = match_vendor("anything", "T1234567890123", _VENDOR_DB)
        assert result["matched"] is True
        assert result["match_method"] == "registration_number"
        assert result["confidence"] >= 0.95
        assert result["needs_review"] is False
        assert result["vendor"]["name"] == "株式会社 ABC"

    def test_normalized_name_match(self):
        # Input uses full form; DB also has full form → normalized match
        result = match_vendor("株式会社 ABC", None, _VENDOR_DB)
        assert result["matched"] is True
        assert result["match_method"] == "normalized_name"
        assert result["confidence"] >= 0.80
        assert result["needs_review"] is False

    def test_normalized_name_match_short_form(self):
        # Input uses shorthand ㈱; DB has full form
        vendor_db = [{"name": "株式会社ABC", "registration_number": "T1111111111111"}]
        result = match_vendor("㈱ABC", None, vendor_db)
        assert result["matched"] is True
        assert result["match_method"] == "normalized_name"

    def test_fuzzy_name_match(self):
        # Partial overlap should match via fuzzy
        vendor_db = [{"name": "株式会社ABC Corporation", "registration_number": "T2222222222222"}]
        result = match_vendor("株式会社ABC", None, vendor_db)
        assert result["matched"] is True
        assert result["match_method"] == "fuzzy_name"
        assert result["needs_review"] is True

    def test_no_match(self):
        result = match_vendor("Totally Unknown Corp", None, _VENDOR_DB)
        assert result["matched"] is False
        assert result["match_method"] == "none"
        assert result["confidence"] == 0.0

    def test_empty_vendor_db(self):
        result = match_vendor("株式会社 ABC", "T1234567890123", [])
        assert result["matched"] is False

    def test_none_vendor_db(self):
        result = match_vendor("株式会社 ABC", "T1234567890123", None)
        assert result["matched"] is False

    def test_none_inputs_handled(self):
        result = match_vendor(None, None, _VENDOR_DB)
        assert result["matched"] is False

    def test_registration_beats_name(self):
        # If both reg and name match different vendors, registration wins
        result = match_vendor("有限会社XYZ", "T1234567890123", _VENDOR_DB)
        assert result["matched"] is True
        assert result["match_method"] == "registration_number"
        assert result["vendor"]["name"] == "株式会社 ABC"

    def test_fullwidth_registration_match(self):
        db = [{"name": "Test Co", "registration_number": "T1234567890123"}]
        result = match_vendor("Test Co", "Ｔ1234567890123", db)
        assert result["matched"] is True
        assert result["match_method"] == "registration_number"
