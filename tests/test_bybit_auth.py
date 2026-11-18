"""
Testes de bybit_auth.py — FASE 5
===================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys reais (fake fixtures determinísticas).
⚠️  Função pura: testa só matemática HMAC + serialização.

Cobertura:
    - sign_request determinístico (mesmo input → mesma assinatura).
    - assinatura muda com payload diferente.
    - secret nunca aparece em headers/output.
    - recv_window inválido gera erro.
    - timestamp inválido gera erro.
    - api_key/api_secret vazios geram erro.
    - method inválido gera erro.
    - build_query_string ordena por chave alfabeticamente.
    - build_body_string produz JSON compacto sem espaços.
    - assinatura é hex lowercase.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from crypto_trading_bot.exchange.bybit_auth import (
    build_body_string,
    build_query_string,
    sign_request,
)

# Fixtures FAKE — não são credentials reais.
_FAKE_API_KEY = "AKEY_TEST_0123456789ABCDEFGH"
_FAKE_API_SECRET = "ASEC_TEST_FEDCBA9876543210IJKLMNOPQRSTUV"
_FAKE_TIMESTAMP = 1_700_000_000_000  # determinístico
_FAKE_RECV_WINDOW = 5000


# ---------------------------------------------------------------------------
# build_query_string
# ---------------------------------------------------------------------------

class TestBuildQueryString:

    def test_empty_params_returns_empty(self):
        assert build_query_string({}) == ""

    def test_single_param(self):
        assert build_query_string({"category": "linear"}) == "category=linear"

    def test_params_ordered_alphabetically(self):
        result = build_query_string({
            "symbol": "BTCUSDT",
            "category": "linear",
            "limit": 100,
        })
        assert result == "category=linear&limit=100&symbol=BTCUSDT"

    def test_numeric_values_str_serialized(self):
        result = build_query_string({"a": 1, "b": 2.5})
        # Sem aspas; números viram strings via f-string
        assert "a=1" in result
        assert "b=2.5" in result


# ---------------------------------------------------------------------------
# build_body_string
# ---------------------------------------------------------------------------

class TestBuildBodyString:

    def test_empty_returns_braces(self):
        assert build_body_string({}) == "{}"

    def test_compact_no_spaces(self):
        result = build_body_string({"a": 1, "b": 2})
        # JSON compacto: NÃO contém ", " nem ": "
        assert " " not in result
        assert result == '{"a":1,"b":2}'

    def test_preserves_insertion_order(self):
        result = build_body_string({"z": 1, "a": 2, "m": 3})
        # sort_keys=False → ordem de inserção preservada
        assert result == '{"z":1,"a":2,"m":3}'


# ---------------------------------------------------------------------------
# sign_request — caminho feliz e determinismo
# ---------------------------------------------------------------------------

class TestSignRequestHappyPath:

    def test_returns_required_headers(self):
        headers = sign_request(
            api_key=_FAKE_API_KEY,
            api_secret=_FAKE_API_SECRET,
            timestamp_ms=_FAKE_TIMESTAMP,
            recv_window_ms=_FAKE_RECV_WINDOW,
            method="GET",
            query_or_body="category=linear&symbol=BTCUSDT",
        )
        # Todos os 5 headers obrigatórios da Bybit V5
        assert headers["X-BAPI-API-KEY"] == _FAKE_API_KEY
        assert headers["X-BAPI-TIMESTAMP"] == str(_FAKE_TIMESTAMP)
        assert headers["X-BAPI-RECV-WINDOW"] == str(_FAKE_RECV_WINDOW)
        assert headers["X-BAPI-SIGN-TYPE"] == "2"
        assert "X-BAPI-SIGN" in headers
        assert len(headers["X-BAPI-SIGN"]) == 64   # SHA-256 hex = 64 chars

    def test_signature_is_hex_lowercase(self):
        headers = sign_request(
            api_key=_FAKE_API_KEY,
            api_secret=_FAKE_API_SECRET,
            timestamp_ms=_FAKE_TIMESTAMP,
            recv_window_ms=_FAKE_RECV_WINDOW,
            method="GET",
            query_or_body="",
        )
        sig = headers["X-BAPI-SIGN"]
        assert sig == sig.lower()
        # Apenas hex chars
        assert all(c in "0123456789abcdef" for c in sig)

    def test_deterministic_same_inputs(self):
        h1 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "category=linear",
        )
        h2 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "category=linear",
        )
        assert h1["X-BAPI-SIGN"] == h2["X-BAPI-SIGN"]

    def test_different_payloads_produce_different_signatures(self):
        h1 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "category=linear&symbol=BTCUSDT",
        )
        h2 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "category=linear&symbol=ETHUSDT",
        )
        assert h1["X-BAPI-SIGN"] != h2["X-BAPI-SIGN"]

    def test_different_timestamps_produce_different_signatures(self):
        h1 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "",
        )
        h2 = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP + 1000, _FAKE_RECV_WINDOW,
            "GET", "",
        )
        assert h1["X-BAPI-SIGN"] != h2["X-BAPI-SIGN"]

    def test_signature_matches_manual_hmac_computation(self):
        """Verifica que o algoritmo bate com a spec Bybit V5."""
        query = "category=linear&symbol=BTCUSDT"
        expected_payload = f"{_FAKE_TIMESTAMP}{_FAKE_API_KEY}{_FAKE_RECV_WINDOW}{query}"
        expected_sig = hmac.new(
            key=_FAKE_API_SECRET.encode(),
            msg=expected_payload.encode(),
            digestmod=hashlib.sha256,
        ).hexdigest()

        headers = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", query,
        )
        assert headers["X-BAPI-SIGN"] == expected_sig


# ---------------------------------------------------------------------------
# Segurança: secret nunca aparece em headers/output
# ---------------------------------------------------------------------------

class TestSecretsNeverLeak:

    def test_secret_not_in_headers_values(self):
        headers = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "category=linear",
        )
        # api_secret NUNCA aparece nos valores dos headers
        for k, v in headers.items():
            assert _FAKE_API_SECRET not in str(v), (
                f"api_secret VAZADO no header {k}"
            )

    def test_secret_not_in_headers_keys(self):
        headers = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "",
        )
        for k in headers.keys():
            assert _FAKE_API_SECRET not in k

    def test_api_key_in_headers_but_secret_not(self):
        """api_key é HEADER público (X-BAPI-API-KEY); api_secret NÃO."""
        headers = sign_request(
            _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
            "GET", "",
        )
        assert headers["X-BAPI-API-KEY"] == _FAKE_API_KEY
        # api_secret nunca em valor algum
        joined = "|".join(str(v) for v in headers.values())
        assert _FAKE_API_SECRET not in joined


# ---------------------------------------------------------------------------
# Validação de entrada
# ---------------------------------------------------------------------------

class TestSignRequestInputValidation:

    @pytest.mark.parametrize("bad_key", ["", "   ", None])
    def test_empty_api_key_raises(self, bad_key):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            sign_request(
                bad_key, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
                "GET", "",
            )

    @pytest.mark.parametrize("bad_secret", ["", "   ", None])
    def test_empty_api_secret_raises(self, bad_secret):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            sign_request(
                _FAKE_API_KEY, bad_secret, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
                "GET", "",
            )

    def test_negative_timestamp_raises(self):
        with pytest.raises(ValueError, match="timestamp"):
            sign_request(
                _FAKE_API_KEY, _FAKE_API_SECRET, -1, _FAKE_RECV_WINDOW,
                "GET", "",
            )

    @pytest.mark.parametrize("bad_recv", [0, 99, 60001, 100000])
    def test_invalid_recv_window_raises(self, bad_recv):
        with pytest.raises(ValueError, match="recv_window"):
            sign_request(
                _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, bad_recv,
                "GET", "",
            )

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError, match="method"):
            sign_request(
                _FAKE_API_KEY, _FAKE_API_SECRET, _FAKE_TIMESTAMP, _FAKE_RECV_WINDOW,
                "PATCH", "",
            )
