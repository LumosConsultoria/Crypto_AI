"""
Tests - to_signal_blueprint bridge (FASE 22)
==================================================
100% offline. ZERO network.

Covers OrderProposal -> SignalBlueprint mapping and rejections.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.demo_session_execution import (
    BlueprintSide,
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
    to_signal_blueprint,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    MarketInfo,
    OrderProposal,
    PreflightReport,
)


def _market() -> MarketInfo:
    return MarketInfo(
        symbol="BTCUSDT",
        category="linear",
        best_bid=65000.0,
        best_ask=65020.0,
        mid_price=65010.0,
        last_price=65015.0,
        reference_price=65010.0,
        min_order_qty=0.001,
        max_order_qty=100.0,
        qty_step=0.001,
        min_notional_value=5.0,
        tick_size=0.5,
    )


def _account() -> AccountState:
    return AccountState(
        wallet_balance_usdt=5000.0,
        available_balance_usdt=4900.0,
        open_positions_count=0,
        open_orders_count=0,
        leverage_confirmable=True,
        leverage_value=1.0,
    )


def _proposal(
    *, side="buy", take_profit=66950.30, stop_loss=None,
) -> OrderProposal:
    if stop_loss is None:
        stop_loss = 64034.85 if side == "buy" else 66000.0
    return OrderProposal(
        symbol="BTCUSDT",
        side=side,
        reference_price=65010.0,
        qty=0.001,
        position_size_usd=65.01,
        stop_loss=stop_loss,
        take_profit=take_profit,
        leverage=1.0,
        risk_usd=0.98,
        capital=5000.0,
    )


def _report(proposal: OrderProposal) -> PreflightReport:
    return PreflightReport(
        ok=True,
        market_info=_market(),
        account_state=_account(),
        proposal=proposal,
        abort_reason=None,
        abort_details="",
    )


# ===========================================================================
# Mapping
# ===========================================================================

class TestBridgeMapping:

    def test_buy_mapping(self):
        bp = build_demo_api_blueprint(_report(_proposal(side="buy")))
        sig = to_signal_blueprint(bp)
        assert sig.symbol == "BTCUSDT"
        assert sig.side is BlueprintSide.BUY
        assert sig.entry_price == 65010.0
        assert sig.stop_loss == 64034.85
        assert sig.take_profit == 66950.30
        assert sig.position_size_usd == 65.01
        assert sig.leverage == 1.0
        assert sig.strategy_name == "demo_session_v1_api_driven"

    def test_sell_mapping(self):
        bp = build_demo_api_blueprint(_report(
            _proposal(side="sell", take_profit=64000.0, stop_loss=66000.0),
        ))
        sig = to_signal_blueprint(bp)
        assert sig.side is BlueprintSide.SELL
        assert sig.take_profit == 64000.0
        assert sig.stop_loss == 66000.0

    def test_strategy_name_fixed(self):
        bp = build_demo_api_blueprint(_report(_proposal()))
        sig = to_signal_blueprint(bp)
        assert sig.strategy_name == "demo_session_v1_api_driven"


# ===========================================================================
# Rejections
# ===========================================================================

class TestBridgeRejections:

    def test_take_profit_none_rejected(self):
        bp = build_demo_api_blueprint(_report(
            _proposal(take_profit=None),  # type: ignore[arg-type]
        ))
        with pytest.raises(DemoApiBlueprintRejected, match="take_profit"):
            to_signal_blueprint(bp)

    def test_invalid_side_rejected(self):
        bp = build_demo_api_blueprint(_report(_proposal(side="long")))
        with pytest.raises(DemoApiBlueprintRejected, match="side"):
            to_signal_blueprint(bp)
