"""
Testes de log_redaction.py — FASE 5
========================================
⚠️  Função pura: sem I/O, sem rede.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.logging_system.log_redaction import (
    REDACTED_PLACEHOLDER,
    redact_dict,
    redact_sensitive,
)


class TestRedactSensitiveBasic:

    def test_api_key_eq_redacted(self):
        result = redact_sensitive("api_key=ABC123 other=keep")
        assert "ABC123" not in result
        assert REDACTED_PLACEHOLDER in result
        assert "other=keep" in result

    def test_api_secret_eq_redacted(self):
        result = redact_sensitive("api_secret=topsecret999")
        assert "topsecret999" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_secret_eq_redacted(self):
        result = redact_sensitive("secret=mypassword123")
        assert "mypassword123" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_x_bapi_sign_redacted(self):
        result = redact_sensitive(
            "Headers: X-BAPI-SIGN: 6c7d8e9abc123def456789..."
        )
        assert "6c7d8e9abc123def456789" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_x_bapi_api_key_redacted(self):
        result = redact_sensitive(
            "X-BAPI-API-KEY: AKEY_abc_123"
        )
        assert "AKEY_abc_123" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_authorization_redacted(self):
        result = redact_sensitive("Authorization: Bearer eyJhbGc...")
        assert "eyJhbGc" not in result
        assert REDACTED_PLACEHOLDER in result


class TestRedactSensitiveCaseAndQuotes:

    def test_case_insensitive_api_key(self):
        result = redact_sensitive("API_KEY=ABC123")
        assert "ABC123" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_json_style_quoted(self):
        result = redact_sensitive('{"api_secret": "topsecret"}')
        assert "topsecret" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_json_style_unquoted_value(self):
        result = redact_sensitive('"api_key": "AKEY_xyz"')
        assert "AKEY_xyz" not in result
        assert REDACTED_PLACEHOLDER in result


class TestRedactMultipleSecrets:

    def test_multiple_secrets_in_one_message_all_redacted(self):
        msg = (
            "Headers: api_key=KEY_aaa, api_secret=SEC_bbb, "
            "X-BAPI-SIGN: sign_ccc, X-BAPI-API-KEY: KEY_ddd"
        )
        result = redact_sensitive(msg)
        for secret in ("KEY_aaa", "SEC_bbb", "sign_ccc", "KEY_ddd"):
            assert secret not in result, f"{secret} NÃO foi mascarado!"


class TestRedactNoFalsePositives:

    def test_non_sensitive_messages_unchanged(self):
        msg = "BotEngine started | cycle=42 | symbol=BTCUSDT | pnl=+12.34"
        result = redact_sensitive(msg)
        assert result == msg

    def test_keyword_in_text_without_separator_not_redacted(self):
        # "api_key" como palavra no meio de texto SEM "=" ou ":" não é mascarado
        msg = "this string mentions api_key but has no value pattern"
        result = redact_sensitive(msg)
        assert result == msg

    def test_empty_string(self):
        assert redact_sensitive("") == ""

    def test_none_input_returns_input(self):
        # Função tolerante a tipos não-string
        assert redact_sensitive(None) is None  # type: ignore[arg-type]


class TestRedactDict:

    def test_dict_redacts_sensitive_keys(self):
        data = {
            "api_key": "AKEY_aaa",
            "api_secret": "SEC_bbb",
            "symbol": "BTCUSDT",
            "qty": 0.01,
        }
        result = redact_dict(data)
        assert result["api_key"] == REDACTED_PLACEHOLDER
        assert result["api_secret"] == REDACTED_PLACEHOLDER
        assert result["symbol"] == "BTCUSDT"
        assert result["qty"] == 0.01

    def test_dict_case_insensitive_keys(self):
        data = {"API_KEY": "secret", "API_SECRET": "secret2"}
        result = redact_dict(data)
        assert result["API_KEY"] == REDACTED_PLACEHOLDER
        assert result["API_SECRET"] == REDACTED_PLACEHOLDER

    def test_dict_bapi_headers_redacted(self):
        data = {
            "X-BAPI-API-KEY": "AKEY",
            "X-BAPI-SIGN": "SIGN",
            "Content-Type": "application/json",
        }
        result = redact_dict(data)
        assert result["X-BAPI-API-KEY"] == REDACTED_PLACEHOLDER
        assert result["X-BAPI-SIGN"] == REDACTED_PLACEHOLDER
        assert result["Content-Type"] == "application/json"

    def test_dict_empty(self):
        assert redact_dict({}) == {}
