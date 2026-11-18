"""
Time-limit no BacktestEngine via ExitPolicy (FASE 12)
======================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Sem time-limit: não dispara.
    - Com time-limit menor que duração natural: dispara TIME_LIMIT.
    - SL antes do time-limit prevalece (precedência preservada).
    - exit_decision_snapshot reflete reason/source corretos.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_trending_candles,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_trade import CloseReason
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


def _signal_far_sl_tp() -> StrategySignal:
    # SL próximo (dentro do limite RiskEngine 5%) mas longe do range
    # observado para evitar hit natural — testa só time-limit.
    return StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="stub",
        entry_price=65000.0, stop_loss_price=63000.0,  # ~3.08% — OK no Risk
        take_profit_price=200000.0, position_size_usd=200.0,
    )


def _engine(*, candles, policy=None, use_policy=True, signal=None):
    # one_shot=True: cenarios de time-limit validam UM trade controlado
    # (engine agora notifica on_trade_closed -> reentrada).
    strategy = StubStrategy(
        signal=signal or _signal_far_sl_tp(), one_shot=True)
    strategy.set_running()
    return BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=5000.0),
        feature_engine=FeatureEngine(),
        initial_capital=5000.0,
        min_candles=5,
        symbol="BTCUSDT",
        use_exit_policy=use_policy,
        exit_policy=policy,
    )


class TestTimeLimitFires:

    def test_time_limit_fires_when_configured(self):
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=10,
        )
        # SL longe → não bate; time-limit de 3 candles deve disparar
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=3,
        )
        e = _engine(candles=candles, policy=policy, signal=_signal_far_sl_tp())
        r = e.run(candles)
        assert r.total_trades == 1
        trade = r.trades[0]
        assert trade.close_reason == CloseReason.TIME_LIMIT
        snap = trade.exit_decision_snapshot
        assert snap is not None
        assert snap["reason"] == "time_limit"
        assert snap["source"] == "rule_time"

    def test_time_limit_none_does_not_fire(self):
        candles = generate_trending_candles(
            n=150, base_price=65000.0, trend_pct_per_candle=0.0005,
            volatility_pct=0.002,
        )
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=None,
        )
        e = _engine(candles=candles, policy=policy, signal=_signal_far_sl_tp())
        r = e.run(candles)
        # Sem time-limit, SL e TP longe → posição fica aberta até END_OF_DATA
        # ou time-limit. Como max_time_in_position_candles=None, nenhum trade
        # fecha por TIME_LIMIT.
        for t in r.trades:
            assert t.close_reason != CloseReason.TIME_LIMIT


class TestStopLossWinsOverTimeLimit:

    def test_sl_disparing_before_time_limit_wins(self):
        # Sinal cujo SL bate no candle de gatilho.
        sig = StrategySignal.buy(
            symbol="BTCUSDT", strategy_name="stub",
            entry_price=65000.0, stop_loss_price=64000.0,
            take_profit_price=67000.0, position_size_usd=200.0,
        )
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0, stop_price=64000.0,
            take_profit_price=67000.0, hit_what="stop",
            n_before_entry=60, n_after_entry=3,
        )
        # Time-limit grande → SL deve disparar antes.
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=999,
        )
        e = _engine(candles=candles, policy=policy, signal=sig)
        r = e.run(candles)
        assert r.total_trades == 1
        assert r.trades[0].close_reason == CloseReason.STOP_LOSS
