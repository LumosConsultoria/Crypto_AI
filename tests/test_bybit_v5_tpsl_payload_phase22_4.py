"""
Tests - FASE 22.4: Bybit V5 SL/TP server-side payload + post-fill check
=============================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Reproduces operational bug: Bybit Demo accepted market order but did
NOT attach SL/TP server-side (UI showed entry but no SL/TP). Cause:
payload missing tpslMode + slTriggerBy/tpTriggerBy + slOrderType/
tpOrderType, which Bybit V5 (UTA) silently discards.

Covers:
    - place_market_order payload includes tpslMode="Full" when SL or
      TP is present.
    - slTriggerBy="LastPrice" + slOrderType="Market" sent when SL.
    - tpTriggerBy="LastPrice" + tpOrderType="Market" sent when TP.
    - Without SL nor TP, payload omits all tpsl params (legacy compat).
    - _sl_or_tp_missing_in_position helper: True only when expected SL/TP
      was set in signal but position snapshot reports absent/zero.
    - DemoExecutionResult.manual_review_required=True if a real position
      snapshot post-fill is missing SL/TP that the signal requested.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.execution.bybit_demo_executor import (
    _sl_or_tp_missing_in_position,
)


# ---------------------------------------------------------------------------
# Payload contract for /v5/order/create
# ---------------------------------------------------------------------------

class _PayloadCapture:
    """Captures body_payload from BybitClient._signed_request without rede."""

    def __init__(self):
        self.captured: list[dict] = []

    def __call__(self, *, method, endpoint, body_payload=None, **kw):
        self.captured.append(
            {"method": method, "endpoint": endpoint, "body": body_payload}
        )
        return {"orderId": "FAKE_ORDER_ID", "orderLinkId": "L1"}


def _make_demo_client():
    return BybitClient(
        environment="demo", api_key="FAKE_K", api_secret="FAKE_S",
    )


class TestPayloadHasTpslMode:

    def test_payload_includes_tpsl_mode_when_sl_and_tp(self, monkeypatch):
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=65843.4, take_profit=68851.6,
            )
        body = cap.captured[0]["body"]
        assert body["stopLoss"] == "65843.4"
        assert body["takeProfit"] == "68851.6"
        # FASE 22.4 critical invariant:
        assert body["tpslMode"] == "Full"
        assert body["slTriggerBy"] == "LastPrice"
        assert body["tpTriggerBy"] == "LastPrice"
        assert body["slOrderType"] == "Market"
        assert body["tpOrderType"] == "Market"

    def test_payload_includes_tpsl_mode_for_sell(self, monkeypatch):
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="sell", qty=0.001,
                stop_loss=66000.0, take_profit=64000.0,
            )
        body = cap.captured[0]["body"]
        assert body["side"] == "Sell"
        assert body["tpslMode"] == "Full"
        assert body["slTriggerBy"] == "LastPrice"
        assert body["tpTriggerBy"] == "LastPrice"

    def test_payload_has_tpsl_when_only_sl(self, monkeypatch):
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=64000.0, take_profit=None,
            )
        body = cap.captured[0]["body"]
        # SL present
        assert "stopLoss" in body
        assert body["slTriggerBy"] == "LastPrice"
        assert body["slOrderType"] == "Market"
        # TP absent
        assert "takeProfit" not in body
        assert "tpTriggerBy" not in body
        assert "tpOrderType" not in body
        # tpslMode applied for the partial case (SL only).
        assert body["tpslMode"] == "Full"

    def test_payload_has_tpsl_when_only_tp(self, monkeypatch):
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=None, take_profit=67000.0,
            )
        body = cap.captured[0]["body"]
        assert "stopLoss" not in body
        assert "slTriggerBy" not in body
        assert body["takeProfit"] == "67000.0"
        assert body["tpTriggerBy"] == "LastPrice"
        assert body["tpOrderType"] == "Market"
        assert body["tpslMode"] == "Full"

    def test_payload_omits_tpsl_params_when_no_sl_no_tp(self, monkeypatch):
        """Legacy compat: chamadas sem SL/TP nao recebem tpsl params."""
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=None, take_profit=None,
            )
        body = cap.captured[0]["body"]
        for k in ("stopLoss", "takeProfit", "tpslMode",
                  "slTriggerBy", "tpTriggerBy",
                  "slOrderType", "tpOrderType"):
            assert k not in body, f"unexpected key in legacy payload: {k}"


# ---------------------------------------------------------------------------
# Sanitization
# ---------------------------------------------------------------------------

class TestPayloadNoSecrets:

    def test_payload_contains_no_secret_substrings(self, monkeypatch):
        cap = _PayloadCapture()
        monkeypatch.setattr(BybitClient, "_signed_request", cap)
        with patch("httpx.Client"):
            client = _make_demo_client()
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=64000.0, take_profit=67000.0,
            )
        body_str = str(cap.captured[0]["body"]).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi-sign",
                    "authorization"):
            assert tok not in body_str


# ---------------------------------------------------------------------------
# Helper _sl_or_tp_missing_in_position
# ---------------------------------------------------------------------------

class TestSlOrTpMissingHelper:

    def test_signal_no_sl_returns_false(self):
        # No expected_value -> never "missing".
        assert _sl_or_tp_missing_in_position({}, "stopLoss", None) is False
        assert _sl_or_tp_missing_in_position({}, "stopLoss", 0.0) is False
        assert _sl_or_tp_missing_in_position({}, "stopLoss", -5.0) is False

    def test_expected_sl_position_has_value_returns_false(self):
        snapshot = {"stopLoss": "64000.0"}
        assert _sl_or_tp_missing_in_position(
            snapshot, "stopLoss", 64000.0,
        ) is False

    def test_expected_sl_position_empty_returns_true(self):
        # Bybit retorna "" quando SL nao foi anexado.
        snapshot = {"stopLoss": ""}
        assert _sl_or_tp_missing_in_position(
            snapshot, "stopLoss", 64000.0,
        ) is True

    def test_expected_sl_position_zero_returns_true(self):
        # Bybit retorna "0" / "0.0" quando SL ausente.
        for raw in ("0", "0.0", "0.00"):
            assert _sl_or_tp_missing_in_position(
                {"stopLoss": raw}, "stopLoss", 64000.0,
            ) is True

    def test_expected_sl_position_missing_key_returns_true(self):
        assert _sl_or_tp_missing_in_position(
            {}, "stopLoss", 64000.0,
        ) is True

    def test_non_numeric_string_treated_as_present(self):
        # Defensivo: se a Bybit retornar algo nao-numerico, nao assume
        # ausencia (evita falsos manual_review).
        assert _sl_or_tp_missing_in_position(
            {"stopLoss": "active"}, "stopLoss", 64000.0,
        ) is False

    def test_take_profit_same_logic(self):
        assert _sl_or_tp_missing_in_position(
            {"takeProfit": "0"}, "takeProfit", 68000.0,
        ) is True
        assert _sl_or_tp_missing_in_position(
            {"takeProfit": "68000.0"}, "takeProfit", 68000.0,
        ) is False


# ---------------------------------------------------------------------------
# Integration: BybitDemoExecutor sets manual_review when position lacks SL/TP
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
    DemoTradeStatus,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)


def _settings_demo_ready() -> Settings:
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_testnet_execution=False,
        enable_live_trading=False,
    )


def _make_demo_executor_with_mocks():
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "demo")
    type(client).has_credentials = property(lambda self: True)
    # place_market_order returns OrderResult shape
    from crypto_trading_bot.exchange.base_exchange import OrderResult
    client.place_market_order.return_value = OrderResult(
        order_id="ORDER_FAKE",
        symbol="BTCUSDT", side="buy", order_type="market",
        qty=0.001, price=None, status="submitted", fee=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    # Canonical reconciliation path (no triangulation)
    client.get_order_status.return_value = {
        "orderId": "ORDER_FAKE",
        "orderStatus": "Filled",
        "cumExecQty": "0.001",
    }
    return client


def _make_signal(stop=64000.0, tp=68000.0):
    return TradingSignal(
        symbol="BTCUSDT", side=OrderSide.BUY,
        entry_price=66000.0, stop_loss_price=stop,
        take_profit_price=tp, position_size_usd=66.0,
        strategy_name="test", leverage=1.0,
    )


def _make_risk_result_approved(signal):
    return RiskResult(approved=True, reason="", signal=signal)


class TestPostFillSlTpCheck:

    def test_manual_review_true_when_position_lacks_sl(self):
        client = _make_demo_executor_with_mocks()
        client.get_positions.return_value = [{
            "symbol": "BTCUSDT", "size": "0.001", "side": "Buy",
            # SL FALTANDO (cenario operacional observado).
            "stopLoss": "0",
            "takeProfit": "0",
        }]
        executor = BybitDemoExecutor(
            client=client, mode_guard=ModeGuard(_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=1,
            reconciliation_delay_seconds=0,
        )
        result = executor.execute(
            risk_result=_make_risk_result_approved(_make_signal()),
            dry_run=False,
        )
        assert result.success is True
        assert result.trade is not None
        # Status canonical, mas manual_review ativada pela defesa.
        assert result.manual_review_required is True

    def test_manual_review_false_when_position_has_sl_and_tp(self):
        client = _make_demo_executor_with_mocks()
        client.get_positions.return_value = [{
            "symbol": "BTCUSDT", "size": "0.001", "side": "Buy",
            "stopLoss": "64000.0",
            "takeProfit": "68000.0",
        }]
        executor = BybitDemoExecutor(
            client=client, mode_guard=ModeGuard(_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=1,
            reconciliation_delay_seconds=0,
        )
        result = executor.execute(
            risk_result=_make_risk_result_approved(_make_signal()),
            dry_run=False,
        )
        assert result.success is True
        # Sem triangulation e SL/TP presentes -> sem manual_review.
        assert result.manual_review_required is False
        assert result.reconciliation_confidence == "canonical"

    def test_manual_review_when_only_tp_missing(self):
        client = _make_demo_executor_with_mocks()
        client.get_positions.return_value = [{
            "symbol": "BTCUSDT", "size": "0.001", "side": "Buy",
            "stopLoss": "64000.0",
            "takeProfit": "",  # falta TP
        }]
        executor = BybitDemoExecutor(
            client=client, mode_guard=ModeGuard(_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=1,
            reconciliation_delay_seconds=0,
        )
        result = executor.execute(
            risk_result=_make_risk_result_approved(_make_signal()),
            dry_run=False,
        )
        assert result.manual_review_required is True
