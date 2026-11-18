"""
Tests - FASE 22.1 hotfix (RR-based TP + critical manual confirmations)
=========================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Covers:
    - BybitDemoPreflight: target_take_profit_rr produces TP from SL
      distance + RR, aligned to tick_size, BUY/SELL ordering enforced.
    - target_take_profit_factor and target_take_profit_rr mutually
      exclusive.
    - target_take_profit_rr <= 0 rejected.
    - build_demo_api_blueprint: take_profit_rr propagated and persisted.
    - build_demo_api_blueprint: open orders critical manual_confirmation
      blocks blueprint (no easy bypass).
    - to_signal_blueprint accepts blueprint whose proposal has real TP.
    - DEFAULT_TAKE_PROFIT_RR exported and equals 2.0.
"""

from __future__ import annotations

import math
from typing import Optional
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.demo_session_execution import (
    DEFAULT_TAKE_PROFIT_RR,
    BlueprintSide,
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
    to_signal_blueprint,
)
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.exchange.base_exchange import OrderBook, Ticker
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    BybitDemoPreflight,
    MarketInfo,
    OrderProposal,
    PreflightReport,
)


# ---------------------------------------------------------------------------
# Helpers (mock BybitClient totally; no network). Same shape as
# tests/test_bybit_demo_preflight.py.
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


def _orderbook(bid: float = 67000.1, ask: float = 67000.2) -> OrderBook:
    return OrderBook(
        symbol="BTCUSDT",
        bids=[(bid, 1.5)],
        asks=[(ask, 1.2)],
    )


def _ticker(last: float = 67000.15) -> Ticker:
    return Ticker(
        symbol="BTCUSDT",
        last_price=last,
        bid=last - 0.05,
        ask=last + 0.05,
        volume_24h=1234.5,
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


def _fake_client(side="buy"):
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


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestDefaults:

    def test_default_rr_is_2(self):
        assert DEFAULT_TAKE_PROFIT_RR == 2.0


# ---------------------------------------------------------------------------
# Preflight - RR TP calculation
# ---------------------------------------------------------------------------

class TestPreflightRR:

    def test_rr_default_produces_tp_for_buy(self):
        pre = BybitDemoPreflight(
            client=_fake_client("buy"),
            mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT",
            side="buy",
            leverage_target=1.0,
            confirm_demo_execution=True,
            target_take_profit_rr=2.0,
        )
        report = pre.run()
        assert report.ok, f"abort: {report.abort_reason}"
        prop = report.proposal
        assert prop is not None
        assert prop.take_profit is not None
        # BUY: TP > entry > SL
        assert prop.stop_loss < prop.reference_price < prop.take_profit

    def test_rr_custom_produces_correct_distance(self):
        # RR=3 should put TP further than RR=1.
        c = _fake_client("buy")
        pre_rr3 = BybitDemoPreflight(
            client=c, mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT", side="buy",
            leverage_target=1.0, confirm_demo_execution=True,
            target_take_profit_rr=3.0,
        )
        r3 = pre_rr3.run()
        assert r3.ok
        tp3 = r3.proposal.take_profit
        entry = r3.proposal.reference_price
        sl = r3.proposal.stop_loss

        pre_rr1 = BybitDemoPreflight(
            client=_fake_client("buy"), mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT", side="buy",
            leverage_target=1.0, confirm_demo_execution=True,
            target_take_profit_rr=1.0,
        )
        r1 = pre_rr1.run()
        tp1 = r1.proposal.take_profit
        assert tp3 > tp1

        # Approximate: tp ~= entry + (entry-sl) * rr
        expected_rr3 = entry + (entry - sl) * 3.0
        # Within one tick_size of expected
        assert abs(tp3 - expected_rr3) <= 0.5  # 5*tick_size buffer

    def test_rr_tp_aligned_to_tick_size_buy(self):
        pre = BybitDemoPreflight(
            client=_fake_client("buy"),
            mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT", side="buy",
            leverage_target=1.0, confirm_demo_execution=True,
            target_take_profit_rr=2.0,
        )
        report = pre.run()
        tp = report.proposal.take_profit
        tick = report.market_info.tick_size
        # tp / tick must be (close to) integer
        ratio = tp / tick
        assert abs(ratio - round(ratio)) < 1e-6

    def test_rr_zero_rejected_in_constructor(self):
        with pytest.raises(ValueError):
            BybitDemoPreflight(
                client=_fake_client(), mode_guard=_make_mode_guard_demo(),
                risk_engine=_make_risk_engine(),
                symbol="BTCUSDT", side="buy",
                leverage_target=1.0, confirm_demo_execution=True,
                target_take_profit_rr=0.0,
            )

    def test_rr_negative_rejected_in_constructor(self):
        with pytest.raises(ValueError):
            BybitDemoPreflight(
                client=_fake_client(), mode_guard=_make_mode_guard_demo(),
                risk_engine=_make_risk_engine(),
                symbol="BTCUSDT", side="buy",
                leverage_target=1.0, confirm_demo_execution=True,
                target_take_profit_rr=-1.0,
            )

    def test_factor_and_rr_mutually_exclusive(self):
        with pytest.raises(ValueError, match="mutuamente exclusivos"):
            BybitDemoPreflight(
                client=_fake_client(), mode_guard=_make_mode_guard_demo(),
                risk_engine=_make_risk_engine(),
                symbol="BTCUSDT", side="buy",
                leverage_target=1.0, confirm_demo_execution=True,
                target_take_profit_factor=1.03,
                target_take_profit_rr=2.0,
            )

    def test_no_tp_when_neither_provided(self):
        pre = BybitDemoPreflight(
            client=_fake_client(), mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT", side="buy",
            leverage_target=1.0, confirm_demo_execution=True,
        )
        report = pre.run()
        assert report.ok
        assert report.proposal.take_profit is None

    def test_target_take_profit_rr_property(self):
        pre = BybitDemoPreflight(
            client=_fake_client(), mode_guard=_make_mode_guard_demo(),
            risk_engine=_make_risk_engine(),
            symbol="BTCUSDT", side="buy",
            leverage_target=1.0, confirm_demo_execution=True,
            target_take_profit_rr=2.5,
        )
        assert pre.target_take_profit_rr == 2.5


# ---------------------------------------------------------------------------
# build_demo_api_blueprint - take_profit_rr propagation
# ---------------------------------------------------------------------------

def _make_report_with_tp(rr=2.0):
    """Use a real preflight run with mocked client to keep behavior consistent."""
    pre = BybitDemoPreflight(
        client=_fake_client(),
        mode_guard=_make_mode_guard_demo(),
        risk_engine=_make_risk_engine(),
        symbol="BTCUSDT", side="buy",
        leverage_target=1.0, confirm_demo_execution=True,
        target_take_profit_rr=rr,
    )
    return pre.run()


class TestBlueprintRRPropagation:

    def test_take_profit_rr_recorded_in_blueprint(self):
        report = _make_report_with_tp(2.0)
        bp = build_demo_api_blueprint(report, take_profit_rr=2.0)
        assert bp.take_profit_rr == 2.0
        assert bp.proposal.take_profit is not None
        assert bp.schema_version == 2

    def test_take_profit_rr_none_when_not_passed(self):
        report = _make_report_with_tp(2.0)
        bp = build_demo_api_blueprint(report)
        assert bp.take_profit_rr is None
        # proposal still has TP because preflight produced it
        assert bp.proposal.take_profit is not None

    def test_to_signal_blueprint_accepts_blueprint_with_real_tp(self):
        report = _make_report_with_tp(2.0)
        bp = build_demo_api_blueprint(report, take_profit_rr=2.0)
        sig = to_signal_blueprint(bp)
        assert sig.side is BlueprintSide.BUY
        assert sig.take_profit > sig.entry_price > sig.stop_loss
        assert sig.strategy_name == "demo_session_v1_api_driven"


# ---------------------------------------------------------------------------
# Critical manual_confirmations: open orders failure blocks blueprint
# ---------------------------------------------------------------------------

def _make_open_orders_failure_report() -> PreflightReport:
    return PreflightReport(
        ok=True,
        market_info=MarketInfo(
            symbol="BTCUSDT", category="linear",
            best_bid=65000.0, best_ask=65020.0,
            mid_price=65010.0, last_price=65015.0,
            reference_price=65010.0,
            min_order_qty=0.001, max_order_qty=100.0,
            qty_step=0.001, min_notional_value=5.0, tick_size=0.5,
        ),
        account_state=AccountState(
            wallet_balance_usdt=5000.0, available_balance_usdt=4900.0,
            open_positions_count=0,
            open_orders_count=0,  # conservative default when API failed
            leverage_confirmable=True, leverage_value=1.0,
        ),
        proposal=OrderProposal(
            symbol="BTCUSDT", side="buy", reference_price=65010.0,
            qty=0.001, position_size_usd=65.01,
            stop_loss=64034.85, take_profit=66950.30,
            leverage=1.0, risk_usd=0.98, capital=5000.0,
        ),
        abort_reason=None, abort_details="",
        manual_confirmations_needed=(
            "open orders nao puderam ser lidas via API (BybitAPIError); "
            "operador deve confirmar manualmente",
        ),
    )


class TestCriticalManualConfirmationBlocks:

    def test_open_orders_failure_blocks_blueprint(self):
        with pytest.raises(
            DemoApiBlueprintRejected, match="critical_manual_confirmation"
        ):
            build_demo_api_blueprint(_make_open_orders_failure_report())

    def test_open_orders_failure_blocks_even_with_leverage_flag(self):
        with pytest.raises(
            DemoApiBlueprintRejected, match="critical_manual_confirmation"
        ):
            build_demo_api_blueprint(
                _make_open_orders_failure_report(),
                accept_leverage_manual_confirmation=True,
            )

    def test_non_critical_manual_confirmation_allowed(self):
        # Manual confirmation that does NOT mention open orders should
        # propagate but not block.
        report = PreflightReport(
            ok=True,
            market_info=_make_open_orders_failure_report().market_info,
            account_state=_make_open_orders_failure_report().account_state,
            proposal=_make_open_orders_failure_report().proposal,
            abort_reason=None, abort_details="",
            manual_confirmations_needed=(
                "leverage deve ser conferida na UI",
            ),
        )
        bp = build_demo_api_blueprint(report)
        assert "leverage deve ser conferida na UI" in \
            bp.manual_confirmations_needed

    def test_classification_substrings_case_insensitive(self):
        report = PreflightReport(
            ok=True,
            market_info=_make_open_orders_failure_report().market_info,
            account_state=_make_open_orders_failure_report().account_state,
            proposal=_make_open_orders_failure_report().proposal,
            abort_reason=None, abort_details="",
            manual_confirmations_needed=(
                "OPEN_ORDERS endpoint deu erro",
            ),
        )
        with pytest.raises(
            DemoApiBlueprintRejected, match="critical_manual_confirmation"
        ):
            build_demo_api_blueprint(report)


# ---------------------------------------------------------------------------
# Schema version bump
# ---------------------------------------------------------------------------

class TestSchemaVersion:

    def test_schema_version_is_2(self):
        report = _make_report_with_tp(2.0)
        bp = build_demo_api_blueprint(report, take_profit_rr=2.0)
        assert bp.schema_version == 2

    def test_to_dict_contains_take_profit_rr_field(self):
        report = _make_report_with_tp(2.0)
        bp = build_demo_api_blueprint(report, take_profit_rr=2.0)
        d = bp.to_dict()
        assert "take_profit_rr" in d
        assert d["take_profit_rr"] == 2.0
