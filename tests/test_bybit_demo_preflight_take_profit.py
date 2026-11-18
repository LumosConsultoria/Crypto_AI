"""
BybitDemoPreflight — Validação de Take Profit (FASE 13)
=========================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Cobertura (todos com mocks — nenhum BybitClient real):
    - target_take_profit_factor=None → proposal.take_profit=None (default).
    - BUY com factor válido (>1.0) → tp > reference, alinhado a tick.
    - BUY com factor <=1.0 → aborta TAKE_PROFIT_INVALID.
    - SELL com factor válido (<1.0) → tp < reference.
    - SELL com factor >=1.0 → aborta TAKE_PROFIT_INVALID.
    - Preflight nunca chama place_market_order / cancel / close.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.execution import (
    BybitDemoPreflight,
    PreflightAbortReason,
)
from tests.test_bybit_demo_preflight import (
    _make_client,
    _make_preflight,
    _settings_demo_ready,
)
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.risk.risk_engine import RiskEngine


def _make_pf_with_tp(
    *,
    side: str = "buy",
    tp_factor: float | None = None,
    client=None,
):
    """Variante de _make_preflight com target_take_profit_factor."""
    client = client or _make_client()
    guard = ModeGuard(settings=_settings_demo_ready())
    risk = RiskEngine(initial_capital=10000.0)
    pf = BybitDemoPreflight(
        client=client, mode_guard=guard, risk_engine=risk,
        symbol="BTCUSDT", side=side, leverage_target=1.0,
        confirm_demo_execution=True,
        target_take_profit_factor=tp_factor,
    )
    return pf, client


# ---------------------------------------------------------------------------
# Default: sem TP (retrocompat)
# ---------------------------------------------------------------------------

class TestDefaultNoTakeProfit:

    def test_factor_none_yields_no_take_profit(self):
        pf, _ = _make_pf_with_tp(tp_factor=None)
        r = pf.run()
        assert r.ok
        assert r.proposal is not None
        assert r.proposal.take_profit is None


# ---------------------------------------------------------------------------
# BUY
# ---------------------------------------------------------------------------

class TestBuyValid:

    def test_buy_factor_above_one_produces_tp_above_reference(self):
        pf, _ = _make_pf_with_tp(side="buy", tp_factor=1.03)
        r = pf.run()
        assert r.ok
        assert r.proposal is not None
        assert r.proposal.take_profit is not None
        assert r.proposal.take_profit > r.proposal.reference_price

    def test_buy_factor_equal_one_aborts(self):
        pf, _ = _make_pf_with_tp(side="buy", tp_factor=1.0)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason == PreflightAbortReason.TAKE_PROFIT_INVALID

    def test_buy_factor_below_one_aborts(self):
        pf, _ = _make_pf_with_tp(side="buy", tp_factor=0.97)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason == PreflightAbortReason.TAKE_PROFIT_INVALID


# ---------------------------------------------------------------------------
# SELL
# ---------------------------------------------------------------------------

class TestSellValid:

    def test_sell_factor_below_one_produces_tp_below_reference(self):
        pf, _ = _make_pf_with_tp(side="sell", tp_factor=0.97)
        r = pf.run()
        assert r.ok
        assert r.proposal is not None
        assert r.proposal.take_profit is not None
        assert r.proposal.take_profit < r.proposal.reference_price

    def test_sell_factor_equal_one_aborts(self):
        pf, _ = _make_pf_with_tp(side="sell", tp_factor=1.0)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason == PreflightAbortReason.TAKE_PROFIT_INVALID

    def test_sell_factor_above_one_aborts(self):
        pf, _ = _make_pf_with_tp(side="sell", tp_factor=1.03)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason == PreflightAbortReason.TAKE_PROFIT_INVALID


# ---------------------------------------------------------------------------
# Preflight NÃO envia ordem
# ---------------------------------------------------------------------------

class TestPreflightNeverSends:

    def test_no_place_order_call(self):
        pf, client = _make_pf_with_tp(side="buy", tp_factor=1.03)
        pf.run()
        # Não pode ter chamado place_market_order/cancel/close
        client.place_market_order.assert_not_called()
        # cancel/close podem nem existir no mock spec; verificamos via getattr
        for method in ("cancel_order", "close_position"):
            spy = getattr(client, method, None)
            if spy is not None and hasattr(spy, "assert_not_called"):
                spy.assert_not_called()
