"""
Tests - build_demo_api_blueprint (FASE 22)
================================================
100% offline. ZERO network. ZERO secrets.

Covers aborts (preflight not ok, missing pieces, open position, open
orders, spread too wide, leverage manual without flag) and happy path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_session_execution import (
    DemoApiBlueprint,
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    MarketInfo,
    OrderProposal,
    PreflightAbortReason,
    PreflightReport,
)


def _market(
    *, best_bid=65000.0, best_ask=65020.0, mid_price=65010.0,
) -> MarketInfo:
    return MarketInfo(
        symbol="BTCUSDT",
        category="linear",
        best_bid=best_bid,
        best_ask=best_ask,
        mid_price=mid_price,
        last_price=mid_price,
        reference_price=mid_price,
        min_order_qty=0.001,
        max_order_qty=100.0,
        qty_step=0.001,
        min_notional_value=5.0,
        tick_size=0.5,
    )


def _account(
    *,
    open_positions_count=0,
    open_orders_count=0,
    leverage_confirmable=True,
    leverage_value=1.0,
) -> AccountState:
    return AccountState(
        wallet_balance_usdt=5000.0,
        available_balance_usdt=4900.0,
        open_positions_count=open_positions_count,
        open_orders_count=open_orders_count,
        leverage_confirmable=leverage_confirmable,
        leverage_value=leverage_value,
    )


def _proposal(*, side="buy") -> OrderProposal:
    return OrderProposal(
        symbol="BTCUSDT",
        side=side,
        reference_price=65010.0,
        qty=0.001,
        position_size_usd=65.01,
        stop_loss=64034.85 if side == "buy" else 66000.0,
        take_profit=66950.30 if side == "buy" else 64000.0,
        leverage=1.0,
        risk_usd=0.98,
        capital=5000.0,
    )


def _report(
    *,
    ok=True,
    market=None,
    account=None,
    proposal=None,
    abort_reason=None,
    manual_confirmations_needed=(),
) -> PreflightReport:
    return PreflightReport(
        ok=ok,
        market_info=market if market is not None else _market(),
        account_state=account if account is not None else _account(),
        proposal=proposal if proposal is not None else _proposal(),
        abort_reason=abort_reason,
        abort_details="" if abort_reason is None else "synthetic",
        manual_confirmations_needed=manual_confirmations_needed,
    )


# ===========================================================================
# Happy path
# ===========================================================================

class TestBuildHappyPath:

    def test_clean_inputs_accepted(self):
        bp = build_demo_api_blueprint(_report())
        assert isinstance(bp, DemoApiBlueprint)
        assert bp.proposal.side == "buy"
        assert bp.spread_pct > 0
        assert bp.notional_usd > 0
        assert bp.risk_pct > 0

    def test_command_preview_present(self):
        bp = build_demo_api_blueprint(_report())
        assert "run_bybit_demo_session_gated.py" in bp.command_preview
        assert "--from-blueprint" in bp.command_preview

    def test_sell_side_accepted(self):
        bp = build_demo_api_blueprint(_report(proposal=_proposal(side="sell")))
        assert bp.proposal.side == "sell"

    def test_manual_confirmations_propagated(self):
        bp = build_demo_api_blueprint(
            _report(manual_confirmations_needed=("verify_leverage_in_ui",)),
        )
        assert "verify_leverage_in_ui" in bp.manual_confirmations_needed


# ===========================================================================
# Aborts - structural
# ===========================================================================

class TestBuildStructuralAborts:

    def test_wrong_type_rejected(self):
        with pytest.raises(DemoApiBlueprintRejected):
            build_demo_api_blueprint("not-a-report")  # type: ignore[arg-type]

    def test_preflight_not_ok_rejected(self):
        with pytest.raises(DemoApiBlueprintRejected, match="ok=False"):
            build_demo_api_blueprint(
                _report(ok=False,
                        abort_reason=PreflightAbortReason.ORDERBOOK_EMPTY),
            )

    def test_market_info_missing(self):
        r = PreflightReport(
            ok=True,
            market_info=None,
            account_state=_account(),
            proposal=_proposal(),
            abort_reason=None,
            abort_details="",
        )
        with pytest.raises(DemoApiBlueprintRejected, match="market_info"):
            build_demo_api_blueprint(r)

    def test_account_state_missing(self):
        r = PreflightReport(
            ok=True,
            market_info=_market(),
            account_state=None,
            proposal=_proposal(),
            abort_reason=None,
            abort_details="",
        )
        with pytest.raises(DemoApiBlueprintRejected, match="account_state"):
            build_demo_api_blueprint(r)

    def test_proposal_missing(self):
        r = PreflightReport(
            ok=True,
            market_info=_market(),
            account_state=_account(),
            proposal=None,
            abort_reason=None,
            abort_details="",
        )
        with pytest.raises(DemoApiBlueprintRejected, match="proposal"):
            build_demo_api_blueprint(r)


# ===========================================================================
# Aborts - account state
# ===========================================================================

class TestBuildAccountAborts:

    def test_open_position_rejected(self):
        r = _report(account=_account(open_positions_count=1))
        with pytest.raises(DemoApiBlueprintRejected, match="open_position"):
            build_demo_api_blueprint(r)

    def test_open_order_rejected(self):
        r = _report(account=_account(open_orders_count=1))
        with pytest.raises(DemoApiBlueprintRejected, match="open_order"):
            build_demo_api_blueprint(r)

    def test_leverage_not_confirmable_without_flag_rejected(self):
        r = _report(account=_account(leverage_confirmable=False))
        with pytest.raises(DemoApiBlueprintRejected, match="leverage"):
            build_demo_api_blueprint(r)

    def test_leverage_not_confirmable_with_flag_accepted(self):
        r = _report(account=_account(leverage_confirmable=False))
        bp = build_demo_api_blueprint(
            r, accept_leverage_manual_confirmation=True,
        )
        assert bp.account_state.leverage_confirmable is False


# ===========================================================================
# Aborts - market info
# ===========================================================================

class TestBuildMarketAborts:

    def test_bid_zero_rejected(self):
        r = _report(market=_market(best_bid=0.0))
        with pytest.raises(DemoApiBlueprintRejected, match="bid/ask"):
            build_demo_api_blueprint(r)

    def test_ask_below_bid_rejected(self):
        r = _report(market=_market(best_bid=65020.0, best_ask=65000.0))
        with pytest.raises(DemoApiBlueprintRejected, match="ask < bid"):
            build_demo_api_blueprint(r)

    def test_zero_mid_rejected(self):
        r = _report(market=_market(mid_price=0.0))
        with pytest.raises(DemoApiBlueprintRejected, match="mid_price"):
            build_demo_api_blueprint(r)

    def test_spread_too_wide_rejected(self):
        # Default max spread = 0.10%. 1% spread should fail.
        r = _report(market=_market(best_bid=64500.0, best_ask=65500.0,
                                   mid_price=65000.0))
        with pytest.raises(DemoApiBlueprintRejected, match="spread"):
            build_demo_api_blueprint(r)

    def test_custom_max_spread_pct_accepted(self):
        r = _report(market=_market(best_bid=64500.0, best_ask=65500.0,
                                   mid_price=65000.0))
        bp = build_demo_api_blueprint(r, max_spread_pct=2.0)
        assert bp.spread_pct < 2.0
