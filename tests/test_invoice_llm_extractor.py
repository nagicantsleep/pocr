"""Tests for invoice LLM extractor."""

import json
from unittest.mock import patch, MagicMock

import httpx
import pytest

from app.services.invoice_llm_extractor import (
    extract_with_llm,
    validate_llm_output,
)


# ---------------------------------------------------------------------------
# extract_with_llm tests
# ---------------------------------------------------------------------------

class TestExtractWithLLmDisabled:
    """extract_with_llm returns None when disabled."""

    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_disabled_returns_none(self, mock_settings):
        mock_settings.return_value.INVOICE_ENABLE_LLM_EXTRACTOR = False
        assert extract_with_llm({}) is None

    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_no_provider_returns_none(self, mock_settings):
        mock_settings.return_value.INVOICE_ENABLE_LLM_EXTRACTOR = True
        mock_settings.return_value.INVOICE_LLM_PROVIDER = ""
        mock_settings.return_value.INVOICE_LLM_MODEL = ""
        assert extract_with_llm({}) is None

    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_no_api_key_returns_none(self, mock_settings):
        mock_settings.return_value.INVOICE_ENABLE_LLM_EXTRACTOR = True
        mock_settings.return_value.INVOICE_LLM_PROVIDER = "openai"
        mock_settings.return_value.INVOICE_LLM_MODEL = "gpt-4o"
        mock_settings.return_value.INVOICE_LLM_MODEL = "gpt-4o"
        mock_settings.return_value.STANDARDIZER_API_KEY = None
        assert extract_with_llm({}) is None


def _mock_settings(provider="openai", model="gpt-4o", api_key="sk-test"):
    m = MagicMock()
    m.INVOICE_ENABLE_LLM_EXTRACTOR = True
    m.INVOICE_LLM_PROVIDER = provider
    m.INVOICE_LLM_MODEL = model
    m.STANDARDIZER_API_KEY = api_key
    return m


def _build_llm_response(content: dict | str):
    """Build a mock httpx response for chat completions."""
    body = content if isinstance(content, str) else json.dumps(content)
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"content": body}}],
    }
    return resp


class TestExtractWithLLmSuccess:
    """extract_with_llm with valid provider response."""

    @patch("app.services.invoice_llm_extractor.httpx.Client")
    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_valid_response(self, mock_settings, mock_client_cls):
        mock_settings.return_value = _mock_settings()
        expected = {
            "issuer_name": "テスト株式会社",
            "issuer_registration_number": "T1234567890123",
            "total_amount": 110000,
            "line_items": [],
        }
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _build_llm_response(expected)

        result = extract_with_llm({}, ocr_text="テスト", plain_text="テスト")
        assert result is not None
        assert result["total_amount"] == 110000

    @patch("app.services.invoice_llm_extractor.httpx.Client")
    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_invalid_json_returns_none(self, mock_settings, mock_client_cls):
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _build_llm_response("not json {{{")

        assert extract_with_llm({}) is None

    @patch("app.services.invoice_llm_extractor.httpx.Client")
    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_missing_fields_returns_partial(self, mock_settings, mock_client_cls):
        mock_settings.return_value = _mock_settings()
        partial = {"issuer_name": "テスト"}
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = _build_llm_response(partial)

        result = extract_with_llm({})
        assert result is not None
        assert result["issuer_name"] == "テスト"
        assert "total_amount" not in result

    @patch("app.services.invoice_llm_extractor.httpx.Client")
    @patch("app.services.invoice_llm_extractor.get_settings")
    def test_network_error_returns_none(self, mock_settings, mock_client_cls):
        mock_settings.return_value = _mock_settings()
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = httpx.ConnectError("connection refused")

        assert extract_with_llm({}) is None


# ---------------------------------------------------------------------------
# validate_llm_output tests
# ---------------------------------------------------------------------------

class TestValidateLlmOutput:

    def test_valid_input(self):
        output = {
            "issuer_registration_number": "T1234567890123",
            "transaction_date": "2025-01-15",
            "total_amount": 110000,
            "line_items": [
                {"description": "Item A", "amount_excluding_tax": 50000},
            ],
        }
        assert validate_llm_output(output) is True

    def test_bad_registration_number(self):
        output = {"issuer_registration_number": "XYZ123"}
        assert validate_llm_output(output) is False

    def test_bad_date(self):
        output = {"transaction_date": "15/01/2025"}
        assert validate_llm_output(output) is False

    def test_non_numeric_amount(self):
        output = {"total_amount": "abc"}
        assert validate_llm_output(output) is False

    def test_line_item_missing_description(self):
        output = {
            "line_items": [{"quantity": 1}],
        }
        assert validate_llm_output(output) is False

    def test_null_fields_ok(self):
        output = {
            "issuer_registration_number": None,
            "transaction_date": None,
            "total_amount": None,
        }
        assert validate_llm_output(output) is True

    def test_empty_line_items(self):
        output = {"line_items": []}
        assert validate_llm_output(output) is True

    def test_line_items_not_list(self):
        output = {"line_items": "bad"}
        assert validate_llm_output(output) is False

    def test_reg_number_too_short(self):
        output = {"issuer_registration_number": "T12345"}
        assert validate_llm_output(output) is False

    def test_payment_due_date_bad_format(self):
        output = {"payment_due_date": "2025/01/15"}
        assert validate_llm_output(output) is False
