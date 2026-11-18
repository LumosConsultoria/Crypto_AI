"""
Paridade SL/TP-only entre legado e ExitPolicy (FASE 12)
========================================================
⚠️  100% offline. ZERO rede.

Crítico: quando ExitPolicy roda APENAS com SL+TP (sem time-limit e sem
opposite-signal), o resultado deve ser BYTE-A-BYTE igual ao caminho legado.

Cobertura: 14 testes em cenários sintéticos:
    - trending (sem hit)
    - stop hit
    - tp hit
    - ambiguidade SL+TP no mesmo candle
    - custos zero / realistic / stressed (com entry_latency_candles=2)
    - BUY e SELL (onde aplicável)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal
from tests.helpers import StubStrategy


def _cap() -> ProviderCapability:
    return ProviderCapability(
        provider_id="mock", supports_market_order=True,
        supports_reduce_only=True,
    )


def _stub_buy_signal(
    *, entry: float = 65000.0, sl: float = 64000.0, tp: float = 67000.0
) -> StrategySignal:
    return StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="stub",
        entry_price=entry, stop_loss_price=sl,
        take_profit_price=tp, position_size_usd=200.0,
    )


def _build_engine(
    candles, *, use_policy: bool, policy: ExitPolicy = None,
    cost_config: ExecutionCostConfig = None,
    signal: StrategySignal = None, min_candles: int = 5,
):
    # one_shot=True: cenarios de paridade/snapshot validam UM trade
    # controlado. Com o engine agora notificando on_trade_closed
    # (lifecycle/reentrada), one_shot preserva a intencao "1 trade".
    strategy = StubStrategy(
        signal=signal or _stub_buy_signal(),
        block_after_trade=True,
        one_shot=True,
    )
    strategy.set_running()
    return BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=5000.0),
        feature_engine=FeatureEngine(),
        initial_capital=5000.0,
        min_candles=min_candles,
        symbol="BTCUSDT",
        use_exit_policy=use_policy,
        exit_policy=policy,
        execution_cost_config=cost_config,
    )


def _assert_byte_parity(report_legacy, report_policy) -> None:
    """Compara reports byte-a-byte nos campos críticos."""
    assert report_legacy.total_trades == report_policy.total_trades, (
        "total_trades diverge"
    )
    assert (
        abs(report_legacy.total_pnl_usd - report_policy.total_pnl_usd) < 1e-9
    ), "total_pnl_usd diverge"
    assert report_legacy.equity_curve == report_policy.equity_curve, (
        "equity_curve diverge"
    )
    leg_trades = report_legacy.trades
    pol_trades = report_policy.trades
    assert len(leg_trades) == len(pol_trades)
    for t_leg, t_pol in zip(leg_trades, pol_trades):
        assert t_leg.close_reason == t_pol.close_reason, (
            f"close_reason diverge: {t_leg.close_reason} vs {t_pol.close_reason}"
        )
        assert t_leg.exit_candle_idx == t_pol.exit_candle_idx
        assert abs((t_leg.exit_price or 0) - (t_pol.exit_price or 0)) < 1e-9
        assert abs((t_leg.pnl_usd or 0) - (t_pol.pnl_usd or 0)) < 1e-9


def _run_pair(candles, *, cost_config=None, signal=None, min_candles=5):
    policy = ExitPolicy(provider_capability=_cap())  # SL/TP-only
    e_legacy = _build_engine(
        candles, use_policy=False, cost_config=cost_config,
        signal=signal, min_candles=min_candles,
    )
    e_policy = _build_engine(
        candles, use_policy=True, policy=policy, cost_config=cost_config,
        signal=signal, min_candles=min_candles,
    )
    r_legacy = e_legacy.run(candles)
    r_policy = e_policy.run(candles)
    return r_legacy, r_policy


# ---------------------------------------------------------------------------
# Cenários básicos
# ---------------------------------------------------------------------------

class TestParityNoHit:

    def test_trending_no_sl_tp_hit_parity(self):
        candles = generate_trending_candles(
            n=80, base_price=65000.0, trend_pct_per_candle=0.0005,
            volatility_pct=0.002,
        )
        # Sinal cujo SL e TP estão longe do range
        sig = _stub_buy_signal(entry=65000.0, sl=50000.0, tp=99999.0)
        r1, r2 = _run_pair(candles, signal=sig)
        _assert_byte_parity(r1, r2)

    def test_ranging_market_parity(self):
        candles = generate_ranging_candles(
            n=80, center_price=65000.0, range_pct=0.005
        )
        sig = _stub_buy_signal(entry=65000.0, sl=60000.0, tp=70000.0)
        r1, r2 = _run_pair(candles, signal=sig)
        _assert_byte_parity(r1, r2)


class TestParityStopHit:

    def test_stop_hit_parity(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=3,
        )
        r1, r2 = _run_pair(candles)
        _assert_byte_parity(r1, r2)
        assert r1.total_trades == 1
        assert r1.trades[0].close_reason.value == "stop_loss"


class TestParityTakeProfitHit:

    def test_tp_hit_parity(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="tp",
            n_before_entry=60, n_after_entry=3,
        )
        r1, r2 = _run_pair(candles)
        _assert_byte_parity(r1, r2)
        assert r1.total_trades == 1
        assert r1.trades[0].close_reason.value == "take_profit"


class TestParityAmbiguitySlWinsTp:

    def test_sl_tp_same_candle_sl_wins(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="both",
            n_before_entry=60, n_after_entry=3,
        )
        r1, r2 = _run_pair(candles)
        _assert_byte_parity(r1, r2)
        assert r1.trades[0].close_reason.value == "stop_loss"


# ---------------------------------------------------------------------------
# Cenários com custos
# ---------------------------------------------------------------------------

class TestParityWithCosts:

    def test_zero_cost_parity_explicit(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="tp",
            n_before_entry=60, n_after_entry=3,
        )
        r1, r2 = _run_pair(candles, cost_config=ExecutionCostConfig())
        _assert_byte_parity(r1, r2)

    def test_realistic_cost_parity(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="tp",
            n_before_entry=60, n_after_entry=3,
        )
        cfg = ExecutionCostConfig(
            taker_fee_pct=0.0006, slippage_pct=0.0005, spread_pct=0.0002,
        )
        r1, r2 = _run_pair(candles, cost_config=cfg)
        _assert_byte_parity(r1, r2)

    def test_realistic_cost_with_stop_hit_parity(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=3,
        )
        cfg = ExecutionCostConfig(
            taker_fee_pct=0.0006, slippage_pct=0.0005, spread_pct=0.0002,
        )
        r1, r2 = _run_pair(candles, cost_config=cfg)
        _assert_byte_parity(r1, r2)

    def test_stressed_with_entry_latency_parity(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="tp",
            n_before_entry=20, n_after_entry=5,
        )
        cfg = ExecutionCostConfig(
            taker_fee_pct=0.0012, slippage_pct=0.001, spread_pct=0.0005,
            entry_latency_candles=2,
        )
        r1, r2 = _run_pair(candles, cost_config=cfg)
        _assert_byte_parity(r1, r2)

    def test_volatile_parity(self):
        candles = generate_volatile_candles(
            n=80, volatility_pct=0.03, trend_pct_per_candle=0.0005,
        )
        # Sinal genérico; o objetivo é só rodar e comparar
        sig = _stub_buy_signal(entry=65000.0, sl=60000.0, tp=70000.0)
        r1, r2 = _run_pair(candles, signal=sig)
        _assert_byte_parity(r1, r2)


# ---------------------------------------------------------------------------
# Snapshot só existe no caminho ExitPolicy
# ---------------------------------------------------------------------------

class TestSnapshotPresence:

    def test_legacy_trade_has_no_snapshot(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=3,
        )
        e = _build_engine(candles, use_policy=False)
        r = e.run(candles)
        assert r.total_trades == 1
        assert r.trades[0].exit_decision_snapshot is None

    def test_policy_trade_has_snapshot_with_capability_field(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=3,
        )
        policy = ExitPolicy(provider_capability=_cap())
        e = _build_engine(candles, use_policy=True, policy=policy)
        r = e.run(candles)
        assert r.total_trades == 1
        snap = r.trades[0].exit_decision_snapshot
        assert snap is not None
        assert snap["reason"] == "stop_loss"
        # capability_allows_auto_close DEVE estar; execution_allowed NÃO.
        assert "capability_allows_auto_close" in snap
        assert "execution_allowed" not in snap
