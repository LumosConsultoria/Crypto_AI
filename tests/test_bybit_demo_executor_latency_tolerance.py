"""
Tests - FASE 22 close-out: API latency tolerance for SL/TP propagation
=========================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Reproduces the operational issue: Bybit Demo accepted market order
with stopLoss/takeProfit (UI showed both), reconciliation OK via
/v5/order/realtime attempt 1, but BybitDemoExecutor.execute marked
manual_review_required=True because get_positions snapshot at the
exact moment didn't yet have stopLoss/takeProfit populated (API
propagation latency).

Covers:
    - Defense in depth: SL/TP missing in position_snapshot is OK if
      raw_order_status confirms (UI also confirms).
    - Defense in depth: SL/TP missing in BOTH sources still triggers
      manual_review (real silent discard).
    - post_session_check: retry get_positions when SL/TP missing in
      stage=after_entry until propagation completes.
    - Defense in depth: post_session_check returns success when retry
      eventually sees populated SL/TP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.base_exchange import OrderResult
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
    DemoTradeStatus,
    stage_lower,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)


def _settings_demo_ready():
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_testnet_execution=False,
        enable_live_trading=False,
    )


def _make_executor_with_client(client, *, recon_attempts=1):
    return BybitDemoExecutor(
        client=client,
        mode_guard=ModeGuard(_settings_demo_ready()),
        risk_engine=RiskEngine(initial_capital=5000.0),
        confirm_demo_execution=True,
        reconciliation_attempts=recon_attempts,
        reconciliation_delay_seconds=0,
    )


def _signal(stop=64793.8, tp=67754.0):
    # position_size_usd 200 USD garante qty >= qty_step (0.001) para
    # BTC ~$65k apos normalizacao (200/65760 ~= 0.003).
    return TradingSignal(
        symbol="BTCUSDT", side=OrderSide.BUY,
        entry_price=65760.30, stop_loss_price=stop,
        take_profit_price=tp, position_size_usd=200.0,
        strategy_name="ops", leverage=1.0,
    )


def _approved(sig):
    return RiskResult(approved=True, reason="", signal=sig)


def _make_client_canonical_filled(
    *,
    order_status_has_sltp: bool,
    position_has_sltp: bool,
    stop_loss="64793.8",
    take_profit="67754.0",
):
    """Mocks: ordem aceita, /v5/order/realtime mostra Filled.
    `order_status_has_sltp` decides if SL/TP are in the order_status
    payload (raw_order_status). `position_has_sltp` decides if the
    position snapshot has them populated.
    """
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "demo")
    type(client).has_credentials = property(lambda self: True)
    client.place_market_order.return_value = OrderResult(
        order_id="FAKE_ORDER", symbol="BTCUSDT", side="buy",
        order_type="market", qty=0.003, price=None, status="submitted",
        fee=0.0, timestamp=datetime.now(timezone.utc),
    )
    order_status = {
        "orderId": "FAKE_ORDER", "orderStatus": "Filled",
        "cumExecQty": "0.003",
    }
    if order_status_has_sltp:
        order_status["stopLoss"] = stop_loss
        order_status["takeProfit"] = take_profit
    client.get_order_status.return_value = order_status

    pos = {"symbol": "BTCUSDT", "side": "Buy", "size": "0.003"}
    if position_has_sltp:
        pos["stopLoss"] = stop_loss
        pos["takeProfit"] = take_profit
    else:
        pos["stopLoss"] = ""
        pos["takeProfit"] = ""
    client.get_positions.return_value = [pos]
    return client


# ===========================================================================
# Defense in depth: SL/TP confirmed via raw_order_status
# ===========================================================================

class TestDefenseInDepthRawOrderStatusFallback:

    def test_sltp_only_in_order_status_does_not_mark_manual_review(self):
        """Operational scenario: Bybit Demo accepted SL/TP (UI shows),
        order_status confirms, but position_snapshot lags. Defense must
        accept raw_order_status as canonical evidence."""
        client = _make_client_canonical_filled(
            order_status_has_sltp=True,
            position_has_sltp=False,
        )
        executor = _make_executor_with_client(client)
        result = executor.execute(_approved(_signal()), dry_run=False)
        assert result.success is True
        assert result.trade.status is DemoTradeStatus.FILLED
        assert result.reconciliation_confidence == "canonical"
        # CRITICAL: manual_review_required must be False because
        # raw_order_status confirms SL/TP.
        assert result.manual_review_required is False
        assert result.safety_halt_recommended is False

    def test_sltp_only_in_position_does_not_mark_manual_review(self):
        """Reverse case: order_status omits but position_snapshot has."""
        client = _make_client_canonical_filled(
            order_status_has_sltp=False,
            position_has_sltp=True,
        )
        executor = _make_executor_with_client(client)
        result = executor.execute(_approved(_signal()), dry_run=False)
        assert result.manual_review_required is False

    def test_sltp_in_both_sources_clean(self):
        client = _make_client_canonical_filled(
            order_status_has_sltp=True,
            position_has_sltp=True,
        )
        executor = _make_executor_with_client(client)
        result = executor.execute(_approved(_signal()), dry_run=False)
        assert result.manual_review_required is False
        assert result.reconciliation_confidence == "canonical"

    def test_sltp_missing_in_both_sources_marks_manual_review(self):
        """Real silent discard: SL/TP missing in BOTH raw_order_status
        AND position_snapshot -> defense correctly fires."""
        client = _make_client_canonical_filled(
            order_status_has_sltp=False,
            position_has_sltp=False,
        )
        executor = _make_executor_with_client(client)
        result = executor.execute(_approved(_signal()), dry_run=False)
        assert result.manual_review_required is True


# ===========================================================================
# post_session_check retry on SL/TP missing
# ===========================================================================

class TestPostSessionCheckRetryLatency:

    def _client_with_sequential_positions(self, sequence):
        """Returns a client whose get_positions returns successive snapshots
        from `sequence`. Each call advances the index."""
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "demo")
        type(client).has_credentials = property(lambda self: True)
        client.get_balance.return_value = {"USDT": "5000"}
        client.get_open_orders.return_value = []
        snapshots = list(sequence)
        idx = {"i": 0}

        def _get_positions(**kw):
            i = min(idx["i"], len(snapshots) - 1)
            idx["i"] += 1
            return snapshots[i]

        client.get_positions.side_effect = _get_positions
        return client, idx

    def test_retry_eventually_sees_propagated_sltp(self):
        """First snapshot missing SL/TP, second has them. With
        sltp_propagation_retries=2, post_session_check must succeed."""
        pos_missing = [{"symbol": "BTCUSDT", "size": "0.001",
                        "stopLoss": "", "takeProfit": ""}]
        pos_ok = [{"symbol": "BTCUSDT", "size": "0.001",
                   "stopLoss": "64000", "takeProfit": "67000"}]
        client, idx = self._client_with_sequential_positions(
            [pos_missing, pos_ok],
        )
        executor = _make_executor_with_client(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
            expected_qty=0.001,
            sltp_propagation_retries=2,
            sltp_propagation_delay_seconds=0.001,
        )
        assert result.success is True
        assert result.manual_review_required is False
        # At least 2 calls happened (initial + 1 retry).
        assert idx["i"] >= 2

    def test_retry_zero_falls_back_immediately(self):
        # With retries=0, single call only.
        pos_missing = [{"symbol": "BTCUSDT", "size": "0.001",
                        "stopLoss": "", "takeProfit": ""}]
        client, idx = self._client_with_sequential_positions([pos_missing])
        executor = _make_executor_with_client(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
            expected_qty=0.001,
            sltp_propagation_retries=0,
        )
        assert result.manual_review_required is True
        assert idx["i"] == 1

    def test_retry_exhausted_still_missing_marks_manual_review(self):
        # All snapshots still missing -> after retries, manual_review.
        pos_missing = [{"symbol": "BTCUSDT", "size": "0.001",
                        "stopLoss": "", "takeProfit": ""}]
        client, idx = self._client_with_sequential_positions(
            [pos_missing, pos_missing, pos_missing],
        )
        executor = _make_executor_with_client(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="after_entry",
            expected_qty=0.001,
            sltp_propagation_retries=2,
            sltp_propagation_delay_seconds=0.001,
        )
        assert result.manual_review_required is True
        # initial + 2 retries
        assert idx["i"] == 3

    def test_flat_check_does_not_trigger_retry(self):
        # Stage flat_check: no retry needed.
        pos_open = [{"symbol": "BTCUSDT", "size": "0.001",
                     "stopLoss": "", "takeProfit": ""}]
        client, idx = self._client_with_sequential_positions([pos_open])
        executor = _make_executor_with_client(client)
        result = executor.post_session_check(
            "BTCUSDT", dry_run=False, stage="flat_check",
            sltp_propagation_retries=3,
            sltp_propagation_delay_seconds=0.001,
        )
        # No retry triggered.
        assert idx["i"] == 1
        # And position is residual in flat_check.
        assert result.manual_review_required is True


# ===========================================================================
# stage_lower helper
# ===========================================================================

class TestStageLowerHelper:

    def test_default_after_entry(self):
        assert stage_lower(None) == "after_entry"
        assert stage_lower("") == "after_entry"
        assert stage_lower("garbage") == "after_entry"

    def test_normalizes_case(self):
        assert stage_lower("AFTER_ENTRY") == "after_entry"
        assert stage_lower(" Flat_check ") == "flat_check"

    def test_non_string_returns_default(self):
        assert stage_lower(123) == "after_entry"  # type: ignore[arg-type]
