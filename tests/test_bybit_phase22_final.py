"""
Tests - FASE 22 Final: signed GET ordering + redaction + post-session check
================================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Reproduces and covers the FASE 22 Final hotfixes:
    - BybitClient._signed_request now passes httpx.get params in the
      SAME order used to build the HMAC payload (sorted alphabetically).
    - BybitAPIError.ret_msg is sanitized via redact_ret_msg on
      construction: origin_string[...] and other secret-like tokens are
      replaced with REDACTED markers.
    - BybitDemoExecutor.post_session_check is a read-only fortified
      check: balance + positions + open_orders, with residual detection
      and api_error tracking.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
    redact_ret_msg,
)


# ---------------------------------------------------------------------------
# Signed GET: params order matches HMAC payload
# ---------------------------------------------------------------------------

class TestSignedGetParamsOrdering:

    def _capture_request(self, signed_capture: dict, ret_value=None):
        """Returns a patched client whose _http.get records the params."""
        client = BybitClient(
            environment="demo", api_key="FAKE_K", api_secret="FAKE_S",
        )

        def _fake_get(endpoint, params=None, headers=None):
            signed_capture["endpoint"] = endpoint
            signed_capture["params"] = params
            signed_capture["headers"] = headers
            # minimal valid response
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "retCode": 0, "retMsg": "OK", "result": ret_value or {},
            }
            return response

        client._http.get = _fake_get  # type: ignore[assignment]
        return client

    def test_get_params_sent_in_sorted_order_simple(self):
        captured: dict = {}
        client = self._capture_request(captured)
        # Insertion order: symbol, orderId, category
        # Alphabetical:    category, orderId, symbol
        client._signed_request(
            method="GET",
            endpoint="/v5/order/realtime",
            query_params={
                "symbol": "BTCUSDT",
                "orderId": "ABC123",
                "category": "linear",
            },
            timestamp_ms=1700000000000,
        )
        sent_params = captured["params"]
        # Dict preserves insertion order in Python 3.7+, so we can inspect.
        assert list(sent_params.keys()) == ["category", "orderId", "symbol"]

    def test_get_params_sent_in_sorted_order_two_keys(self):
        captured: dict = {}
        client = self._capture_request(captured)
        # Insertion s before c
        client._signed_request(
            method="GET",
            endpoint="/v5/order/realtime",
            query_params={"symbol": "BTCUSDT", "category": "linear"},
            timestamp_ms=1700000000000,
        )
        assert list(captured["params"].keys()) == ["category", "symbol"]

    def test_get_with_empty_params(self):
        captured: dict = {}
        client = self._capture_request(captured)
        client._signed_request(
            method="GET",
            endpoint="/v5/account/info",
            query_params={},
            timestamp_ms=1700000000000,
        )
        # empty dict is OK; no key error
        assert captured["params"] == {}

    def test_get_with_none_params(self):
        captured: dict = {}
        client = self._capture_request(captured)
        client._signed_request(
            method="GET",
            endpoint="/v5/account/info",
            timestamp_ms=1700000000000,
        )
        assert captured["params"] == {}

    def test_post_is_not_affected_by_get_sort(self):
        # POST signs body, doesn't sort query params.
        client = BybitClient(
            environment="demo", api_key="FAKE_K", api_secret="FAKE_S",
        )
        captured: dict = {}

        def _fake_post(endpoint, content=None, headers=None):
            captured["endpoint"] = endpoint
            captured["content"] = content
            captured["headers"] = headers
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "retCode": 0, "retMsg": "OK", "result": {"orderId": "X"},
            }
            return response

        client._http.post = _fake_post  # type: ignore[assignment]
        client._signed_request(
            method="POST",
            endpoint="/v5/order/create",
            body_payload={
                "symbol": "BTCUSDT", "category": "linear", "qty": "0.001",
            },
            timestamp_ms=1700000000000,
        )
        # POST sends body as JSON content; insertion order preserved.
        # Should contain all keys in some valid order.
        assert "BTCUSDT" in captured["content"]
        assert "linear" in captured["content"]


# ---------------------------------------------------------------------------
# Sign payload vs sent params match (regression for retCode=10004)
# ---------------------------------------------------------------------------

class TestSignPayloadMatchesSentParams:

    def test_alphabetical_signed_payload_equals_sent_query(self):
        """FASE 22 Final regression: ensure the string used to compute
        HMAC is built from the same key order as the params sent to
        httpx, so Bybit V5 server's recomputed HMAC matches."""
        from crypto_trading_bot.exchange.bybit_auth import build_query_string

        client = BybitClient(
            environment="demo", api_key="FAKE_K", api_secret="FAKE_S",
        )
        captured: dict = {}

        def _fake_get(endpoint, params=None, headers=None):
            captured["params"] = params
            response = MagicMock()
            response.raise_for_status.return_value = None
            response.json.return_value = {
                "retCode": 0, "retMsg": "OK", "result": {},
            }
            return response

        client._http.get = _fake_get  # type: ignore[assignment]
        client._signed_request(
            method="GET",
            endpoint="/v5/order/realtime",
            query_params={
                "symbol": "BTCUSDT", "orderId": "X", "category": "linear",
            },
            timestamp_ms=1700000000000,
        )
        # Rebuild signed query and compare against what was sent.
        sent = captured["params"]
        rebuilt_sign = build_query_string(sent)
        # Order MUST be alphabetical: c,o,s
        assert rebuilt_sign == "category=linear&orderId=X&symbol=BTCUSDT"


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedactRetMsg:

    def test_origin_string_bracket_redacted(self):
        raw = "error sign! origin_string[1700000000000FAKEKEY5000category=linear]"
        out = redact_ret_msg(raw)
        assert "origin_string[REDACTED]" in out
        assert "FAKEKEY" not in out
        assert "category=linear" not in out

    def test_origin_string_inline_redacted(self):
        raw = "fail because origin_string=blob_with_secrets here"
        out = redact_ret_msg(raw)
        assert "origin_string=REDACTED" in out
        assert "blob_with_secrets" not in out

    def test_x_bapi_sign_redacted(self):
        out = redact_ret_msg("error with X-BAPI-SIGN=abcdef123")
        assert "X-BAPI-SIGN=REDACTED" in out
        assert "abcdef123" not in out

    def test_bearer_token_redacted(self):
        out = redact_ret_msg("Authentication failed: Bearer xyz.abc-123")
        assert "Bearer REDACTED" in out
        assert "xyz.abc-123" not in out

    def test_authorization_redacted(self):
        out = redact_ret_msg("ERROR: Authorization=mytoken123, sign=abcdef0123456789ABCD")
        assert "Authorization=REDACTED" in out
        assert "mytoken123" not in out

    def test_sign_with_hex_redacted(self):
        out = redact_ret_msg("error sign=abcdef0123456789ABCDEF")
        assert "sign=REDACTED" in out

    def test_signature_redacted(self):
        out = redact_ret_msg("bad signature: 0123456789abcdef0123456789abcdef")
        assert "signature=REDACTED" in out or "signature: REDACTED" in out

    def test_api_key_redacted(self):
        out = redact_ret_msg("api_key=AKxyz123 invalid")
        assert "api_key=REDACTED" in out
        assert "AKxyz123" not in out

    def test_api_secret_redacted(self):
        out = redact_ret_msg("api_secret=SECRETxyz")
        assert "api_secret=REDACTED" in out
        assert "SECRETxyz" not in out

    def test_clean_message_unchanged(self):
        # Mensagens benignas devem passar inalteradas (apenas truncadas).
        out = redact_ret_msg("Insufficient balance")
        assert out == "Insufficient balance"

    def test_truncated_at_max_len(self):
        raw = "x" * 500
        out = redact_ret_msg(raw, max_len=100)
        assert len(out) == 100

    def test_non_string_returns_empty(self):
        assert redact_ret_msg(None) == ""  # type: ignore[arg-type]
        assert redact_ret_msg(123) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# BybitAPIError sanitizes ret_msg on construction
# ---------------------------------------------------------------------------

class TestBybitAPIErrorSanitization:

    def test_ret_msg_sanitized_on_construction(self):
        raw = "error sign! origin_string[1700000000FAKEAPIKEYbody]"
        e = BybitAPIError(10004, raw, "/v5/order/realtime")
        assert "origin_string[REDACTED]" in e.ret_msg
        assert "FAKEAPIKEY" not in e.ret_msg
        # str(e) also must be safe.
        assert "FAKEAPIKEY" not in str(e)

    def test_ret_code_preserved(self):
        e = BybitAPIError(10004, "anything", "/v5/order/realtime")
        assert e.ret_code == 10004

    def test_endpoint_preserved(self):
        e = BybitAPIError(0, "ok", "/v5/foo")
        assert e.endpoint == "/v5/foo"

    def test_clean_ret_msg_truncated(self):
        e = BybitAPIError(99, "x" * 500, "/v5/foo")
        assert len(e.ret_msg) <= 200


# ---------------------------------------------------------------------------
# BybitDemoExecutor.post_session_check (read-only fortified)
# ---------------------------------------------------------------------------

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine


def _settings_demo_ready():
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_testnet_execution=False,
        enable_live_trading=False,
    )


def _make_executor(client):
    return BybitDemoExecutor(
        client=client,
        mode_guard=ModeGuard(_settings_demo_ready()),
        risk_engine=RiskEngine(initial_capital=5000.0),
        confirm_demo_execution=True,
        reconciliation_attempts=1,
        reconciliation_delay_seconds=0,
    )


class TestPostSessionCheck:

    def test_dry_run_returns_simulated_success(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        executor = _make_executor(client)
        result = executor.post_session_check("BTCUSDT", dry_run=True)
        assert result.success is True
        assert result.dry_run is True
        # Nada chamado na API
        client.get_balance.assert_not_called()
        client.get_positions.assert_not_called()
        client.get_open_orders.assert_not_called()

    def test_clean_no_residual_no_errors_success_true(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "100"}
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "0"},
        ]
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        # flat_check: expects zero positions and zero orders.
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="flat_check",
        )
        assert result.success is True
        assert result.manual_review_required is False
        assert result.safety_halt_recommended is False
        assert "clean=True" in result.reason
        assert "stage=flat_check" in result.reason

    def test_flat_check_residual_position_triggers_halt(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "100"}
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "0.001"},
        ]
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="flat_check",
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert result.safety_halt_recommended is True
        assert "residual_positions=1" in result.reason

    def test_flat_check_residual_order_triggers_manual_review(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "100"}
        client.get_positions.return_value = []
        client.get_open_orders.return_value = [
            {"orderId": "X", "symbol": "BTCUSDT"},
        ]
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="flat_check",
        )
        assert result.success is False
        assert result.manual_review_required is True

    def test_api_error_triggers_halt_and_sanitized(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.side_effect = BybitAPIError(
            10004,
            "error sign! origin_string[FAKEAPIKEY12345body]",
            "/v5/account/wallet-balance",
        )
        client.get_positions.return_value = []
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        result = executor.post_session_check("BTCUSDT", dry_run=False)
        assert result.success is False
        assert result.manual_review_required is True
        assert result.safety_halt_recommended is True
        # origin_string contents NOT leaked.
        assert "FAKEAPIKEY12345body" not in result.reason
        # retCode preservado
        assert "10004" in result.reason

    def test_open_orders_api_failure_does_not_leak_secrets(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "100"}
        client.get_positions.return_value = []
        client.get_open_orders.side_effect = BybitAPIError(
            10004,
            "error sign! origin_string[SECRETPAYLOAD]",
            "/v5/order/realtime",
        )
        executor = _make_executor(client)
        result = executor.post_session_check("BTCUSDT", dry_run=False)
        assert result.success is False
        joined = result.reason.lower()
        for tok in ("secretpayload", "x-bapi-sign", "bearer ",
                    "api_key=", "api_secret=", "authorization:"):
            assert tok not in joined

    def test_mode_guard_blocked_returns_halt(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        settings = Settings(
            trading_mode=TradingMode.PAPER,
            enable_demo_execution=False,
        )
        executor = BybitDemoExecutor(
            client=client,
            mode_guard=ModeGuard(settings),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=1,
            reconciliation_delay_seconds=0,
        )
        result = executor.post_session_check("BTCUSDT", dry_run=False)
        assert result.success is False
        assert result.manual_review_required is True
        assert result.safety_halt_recommended is True
        # Nao chamou nenhum endpoint privado.
        client.get_balance.assert_not_called()
        client.get_positions.assert_not_called()
        client.get_open_orders.assert_not_called()

    def test_flat_check_non_numeric_size_treated_as_zero(self):
        # Defensivo: se a Bybit retornar "size": "abc", nao deve crashar.
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {}
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "garbage"},
        ]
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="flat_check",
        )
        # size invalido vira 0 -> sem position residual contada
        assert "open_positions_count=0" in result.reason


# ---------------------------------------------------------------------------
# FASE 22 close-out: after_entry stage tests
# ---------------------------------------------------------------------------

class TestPostSessionCheckAfterEntry:
    """Closes inconsistency: posicao recem-aberta protegida nao deve
    forcar manual_review/halt no stage after_entry."""

    def _client_with_position(
        self,
        *,
        size="0.001",
        stop_loss="64000.0",
        take_profit="67000.0",
        open_orders=None,
    ):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "5000"}
        client.get_positions.return_value = [{
            "symbol": "BTCUSDT", "side": "Buy",
            "size": size, "stopLoss": stop_loss, "takeProfit": take_profit,
        }]
        client.get_open_orders.return_value = open_orders or []
        return client

    def test_protected_open_position_is_clean(self):
        """A posicao recem-aberta com SL+TP server-side e qty esperada
        deve retornar SUCCESS, sem manual_review."""
        client = self._client_with_position(
            size="0.001", stop_loss="64000.0", take_profit="67000.0",
        )
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False,
            stage="after_entry", expected_qty=0.001,
        )
        assert result.success is True
        assert result.manual_review_required is False
        assert result.safety_halt_recommended is False
        assert "after_entry:position_protected" in result.reason

    def test_after_entry_default_kwargs_protect_clean_position(self):
        # Default sem expected_qty: aceita qualquer qty > 0 com SL/TP.
        client = self._client_with_position()
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
        )
        assert result.success is True
        assert result.manual_review_required is False

    def test_after_entry_default_stage_is_after_entry(self):
        # Sem stage explicito -> default after_entry. Posicao protegida
        # deve ser clean.
        client = self._client_with_position()
        executor = _make_executor(client)
        result = executor.post_session_check("BTCUSDT", dry_run=False)
        assert result.success is True
        assert "stage=after_entry" in result.reason

    def test_after_entry_missing_sl_triggers_manual_review(self):
        client = self._client_with_position(stop_loss="0")
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False,
            stage="after_entry", expected_qty=0.001,
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "missing_sl" in result.reason

    def test_after_entry_missing_tp_triggers_manual_review(self):
        client = self._client_with_position(take_profit="")
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False,
            stage="after_entry", expected_qty=0.001,
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "missing_tp" in result.reason

    def test_after_entry_qty_mismatch_triggers_manual_review(self):
        # Pediu 0.001 mas snapshot mostra 0.01.
        client = self._client_with_position(size="0.01")
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False,
            stage="after_entry", expected_qty=0.001,
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "qty_mismatch" in result.reason

    def test_after_entry_no_position_triggers_manual_review(self):
        # Esperava posicao mas API retornou vazio (fill nao propagou ainda).
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "5000"}
        client.get_positions.return_value = []
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "no_position" in result.reason

    def test_after_entry_multiple_positions_triggers_manual_review(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "5000"}
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "0.001",
             "stopLoss": "64000.0", "takeProfit": "67000.0"},
            {"symbol": "BTCUSDT", "size": "0.001",
             "stopLoss": "63000.0", "takeProfit": "66000.0"},
        ]
        client.get_open_orders.return_value = []
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "multiple_positions" in result.reason

    def test_after_entry_unexpected_open_orders_triggers_manual_review(self):
        # tpslMode=Full: SL/TP server-side NAO aparece em open_orders.
        # Se aparecer algo aqui, eh inesperado.
        client = self._client_with_position(
            open_orders=[{"orderId": "X", "symbol": "BTCUSDT"}],
        )
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert "unexpected_open_orders" in result.reason

    def test_after_entry_require_sl_false_allows_missing_sl(self):
        # Cenario raro: operador opt-out de SL via flag (nao no caminho
        # operacional default, mas suportado).
        client = self._client_with_position(stop_loss="0")
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False,
            stage="after_entry", expected_qty=0.001,
            require_sl=False, require_tp=True,
        )
        assert result.success is True

    def test_after_entry_api_error_triggers_halt(self):
        client = self._client_with_position()
        client.get_positions.side_effect = BybitAPIError(
            10004, "anything", "/v5/position/list",
        )
        executor = _make_executor(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
        )
        assert result.success is False
        assert result.manual_review_required is True
        assert result.safety_halt_recommended is True


# ---------------------------------------------------------------------------
# Audit / log structure does NOT leak secrets via redactor
# ---------------------------------------------------------------------------

class TestNoSecretsInAuditPaths:

    def test_bybit_api_error_does_not_leak_in_str(self):
        e = BybitAPIError(
            10004,
            "error sign! origin_string[TS_KEY_WINDOW_BODY]",
            "/v5/order/realtime",
        )
        full = str(e)
        for tok in ("TS_KEY_WINDOW_BODY", "X-BAPI-SIGN", "Bearer ",
                    "Authorization", "api_secret"):
            assert tok not in full

    def test_redact_ret_msg_handles_combined_secrets(self):
        out = redact_ret_msg(
            "error: X-BAPI-SIGN=abc, Bearer xyz, "
            "origin_string[FAKE], Authorization=tok123, "
            "api_key=K api_secret=S"
        )
        for tok in ("abc", "xyz", "FAKE", "tok123", "=K", "=S"):
            assert tok not in out
