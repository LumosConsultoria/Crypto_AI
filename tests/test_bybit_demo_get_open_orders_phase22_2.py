"""
Tests - FASE 22.2: BybitClient.get_open_orders + preflight diagnostic
==========================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Covers the FASE 22.2 hotfix:
    - BybitClient.get_open_orders no longer sends openOnly=1 (was wrong:
      that retrieved closed-orders history; default = open orders).
    - BybitClient.get_open_orders sends only {category, symbol}.
    - BybitDemoPreflight._collect_account_state captures BybitAPIError
      and exposes retCode/retMsg sanitized in manual_confirmations.
    - build_demo_api_blueprint continues to block when open orders
      reading fails (FASE 22.1 critical_manual_confirmation invariant).
    - Sanitization: ret_msg truncated/no secrets in audit string.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.demo_session_execution import (
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
)
from crypto_trading_bot.exchange.base_exchange import OrderBook, Ticker
from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    BybitDemoPreflight,
)


# ---------------------------------------------------------------------------
# BybitClient.get_open_orders param contract
# ---------------------------------------------------------------------------

class TestGetOpenOrdersParams:

    def _make_client(self, signed_return_value):
        client = BybitClient(
            api_key="k", api_secret="s", environment="demo",
        )
        client._signed_request = MagicMock(return_value=signed_return_value)
        return client

    def test_empty_open_orders_returns_empty_list(self):
        client = self._make_client({"list": []})
        result = client.get_open_orders("BTCUSDT", category="linear")
        assert result == []

    def test_one_open_order_returned(self):
        sample = {
            "orderId": "o1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "qty": "0.001",
            "orderStatus": "New",
        }
        client = self._make_client({"list": [sample]})
        result = client.get_open_orders("BTCUSDT", category="linear")
        assert len(result) == 1
        assert result[0]["orderId"] == "o1"

    def test_open_only_param_NOT_sent(self):
        # FASE 22.2 invariant: openOnly must NOT be in the query params.
        # Default Bybit behavior (omitido) = open orders.
        client = self._make_client({"list": []})
        client.get_open_orders("BTCUSDT", category="linear")
        _, kwargs = client._signed_request.call_args
        params = kwargs.get("query_params", {})
        assert "openOnly" not in params

    def test_required_params_sent(self):
        client = self._make_client({"list": []})
        client.get_open_orders("BTCUSDT", category="linear")
        _, kwargs = client._signed_request.call_args
        params = kwargs.get("query_params", {})
        assert params.get("symbol") == "BTCUSDT"
        assert params.get("category") == "linear"

    def test_endpoint_correct(self):
        client = self._make_client({"list": []})
        client.get_open_orders("BTCUSDT", category="linear")
        _, kwargs = client._signed_request.call_args
        assert kwargs.get("endpoint") == "/v5/order/realtime"
        assert kwargs.get("method") == "GET"

    def test_propagates_bybit_api_error(self):
        client = BybitClient(
            api_key="k", api_secret="s", environment="demo",
        )
        client._signed_request = MagicMock(
            side_effect=BybitAPIError(
                ret_code=10003,
                ret_msg="Invalid API key permissions",
                endpoint="/v5/order/realtime",
            ),
        )
        with pytest.raises(BybitAPIError) as ei:
            client.get_open_orders("BTCUSDT", category="linear")
        assert ei.value.ret_code == 10003
        assert "Invalid API key permissions" in ei.value.ret_msg


# ---------------------------------------------------------------------------
# Preflight diagnostic capture
# ---------------------------------------------------------------------------

def _instrument() -> dict:
    return {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "minOrderQty": "0.001",
            "maxOrderQty": "1500",
            "qtyStep": "0.001",
            "minNotionalValue": "5",
        },
        "priceFilter": {"tickSize": "0.10"},
    }


def _orderbook() -> OrderBook:
    return OrderBook(
        symbol="BTCUSDT",
        bids=[(67000.1, 1.5)],
        asks=[(67000.2, 1.2)],
    )


def _ticker() -> Ticker:
    return Ticker(
        symbol="BTCUSDT", last_price=67000.15,
        bid=67000.10, ask=67000.20, volume_24h=1234.5,
    )


def _balance() -> dict:
    return {
        "list": [{
            "coin": [{
                "coin": "USDT",
                "walletBalance": "5000.0",
                "availableToWithdraw": "4900.0",
            }],
        }],
    }


def _fake_client(open_orders_exception=None):
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "demo")
    type(client).has_credentials = property(lambda self: True)
    client._base_url = "https://api-demo.bybit.com"
    client.get_instruments_info.return_value = _instrument()
    client.get_order_book.return_value = _orderbook()
    client.get_ticker.return_value = _ticker()
    client.get_balance.return_value = _balance()
    client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "0", "leverage": "1"},
    ]
    if open_orders_exception is not None:
        client.get_open_orders.side_effect = open_orders_exception
    else:
        client.get_open_orders.return_value = []
    return client


def _make_mode_guard_demo():
    from crypto_trading_bot.config.settings import Settings, TradingMode
    from crypto_trading_bot.core.mode_guard import ModeGuard
    settings = Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_live_trading=False,
        enable_testnet_execution=False,
    )
    return ModeGuard(settings)


def _make_risk_engine():
    from crypto_trading_bot.risk.risk_engine import RiskEngine
    return RiskEngine(initial_capital=5000.0)


def _make_preflight(client):
    return BybitDemoPreflight(
        client=client,
        mode_guard=_make_mode_guard_demo(),
        risk_engine=_make_risk_engine(),
        symbol="BTCUSDT", side="buy",
        leverage_target=1.0, confirm_demo_execution=True,
        target_take_profit_rr=2.0,
    )


class TestPreflightDiagnostic:

    def test_open_orders_success_empty_no_manual_confirmation(self):
        pre = _make_preflight(_fake_client(open_orders_exception=None))
        report = pre.run()
        assert report.ok, f"abort: {report.abort_reason}"
        # No critical manual confirmation triggered by open_orders.
        confirms_joined = " ".join(report.manual_confirmations_needed).lower()
        assert "open orders" not in confirms_joined

    def test_open_orders_bybit_api_error_exposes_ret_code_and_msg(self):
        err = BybitAPIError(
            ret_code=10003,
            ret_msg="API key invalid or expired",
            endpoint="/v5/order/realtime",
        )
        pre = _make_preflight(_fake_client(open_orders_exception=err))
        report = pre.run()
        # Report still ok=True (manual confirmation registered, not abort).
        assert report.ok
        confirms = list(report.manual_confirmations_needed)
        joined = " ".join(confirms)
        assert "open orders nao puderam ser lidas" in joined.lower() or \
               "open orders" in joined.lower()
        # retCode and retMsg present in the audit string.
        assert "retCode=10003" in joined
        assert "API key invalid or expired" in joined

    def test_open_orders_generic_exception_falls_back_to_type_name(self):
        pre = _make_preflight(
            _fake_client(open_orders_exception=RuntimeError("network down")),
        )
        report = pre.run()
        assert report.ok
        joined = " ".join(report.manual_confirmations_needed)
        # Generic branch: only the type name (no retCode).
        assert "RuntimeError" in joined
        assert "retCode=" not in joined

    def test_open_orders_ret_msg_truncated_to_120_chars(self):
        long_msg = "x" * 500
        err = BybitAPIError(
            ret_code=999, ret_msg=long_msg,
            endpoint="/v5/order/realtime",
        )
        pre = _make_preflight(_fake_client(open_orders_exception=err))
        report = pre.run()
        joined = " ".join(report.manual_confirmations_needed)
        # Should be at most 120 x's in the ret_msg portion.
        assert "x" * 121 not in joined


# ---------------------------------------------------------------------------
# Blueprint still blocks on open_orders failure (FASE 22.1 invariant)
# ---------------------------------------------------------------------------

class TestBlueprintStillBlocksOnOpenOrdersFailure:

    def test_blueprint_blocks_when_open_orders_failed(self):
        err = BybitAPIError(
            ret_code=10003, ret_msg="permission denied",
            endpoint="/v5/order/realtime",
        )
        pre = _make_preflight(_fake_client(open_orders_exception=err))
        report = pre.run()
        with pytest.raises(
            DemoApiBlueprintRejected, match="critical_manual_confirmation"
        ):
            build_demo_api_blueprint(report)

    def test_blueprint_passes_when_open_orders_confirmed_empty(self):
        pre = _make_preflight(_fake_client(open_orders_exception=None))
        report = pre.run()
        bp = build_demo_api_blueprint(report, take_profit_rr=2.0)
        # Should pass: open_orders confirmed by API as empty list.
        assert bp.account_state.open_orders_count == 0
        assert bp.proposal.take_profit is not None


# ---------------------------------------------------------------------------
# Sanitization: no secrets leak in manual_confirmation string
# ---------------------------------------------------------------------------

class TestSanitization:

    def test_no_secret_substring_in_manual_confirmation(self):
        # If Bybit ever returned a retMsg containing api_key (unlikely
        # but defensive), ret_msg is still truncated to 120 chars and
        # the structure of the message does not include the literal
        # words api_key/api_secret/Bearer/X-BAPI-SIGN/Authorization
        # added by our own code.
        err = BybitAPIError(
            ret_code=999,
            ret_msg="some normal error",
            endpoint="/v5/order/realtime",
        )
        pre = _make_preflight(_fake_client(open_orders_exception=err))
        report = pre.run()
        joined = " ".join(report.manual_confirmations_needed).lower()
        # Our own audit string must NOT contain secret-class tokens.
        for tok in ("api_secret", "bearer ", "x-bapi-sign", "authorization:"):
            assert tok not in joined
