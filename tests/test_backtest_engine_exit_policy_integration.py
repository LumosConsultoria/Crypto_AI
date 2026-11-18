"""
Integração ExitPolicy ↔ BacktestEngine (FASE 12)
=================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordem.

Cobertura:
    - Default: use_exit_policy=False, comportamento legado intocado.
    - use_exit_policy=True sem exit_policy → ValueError.
    - exit_policy ignorada quando use_exit_policy=False.
    - Validação de tipo: exit_policy precisa ser ExitPolicy.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_data import generate_trending_candles
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    TrendPullbackStrategy,
)


def _cap(supports_ro: bool = True) -> ProviderCapability:
    return ProviderCapability(
        provider_id="mock", supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _strategy():
    s = TrendPullbackStrategy(position_size_usd=200.0)
    s.set_running()
    return s


def _engine(*, use_policy: bool = False, policy=None, feature_engine=None):
    return BacktestEngine(
        strategy=_strategy(),
        risk_engine=RiskEngine(initial_capital=5000.0),
        feature_engine=feature_engine or FeatureEngine(ema_periods=[20, 50]),
        initial_capital=5000.0,
        min_candles=60,
        symbol="BTCUSDT",
        use_exit_policy=use_policy,
        exit_policy=policy,
    )


class TestConstructorContract:

    def test_default_use_exit_policy_is_false(self):
        e = _engine()
        assert e._use_exit_policy is False
        assert e._exit_policy is None

    def test_true_without_policy_raises(self):
        with pytest.raises(ValueError, match="use_exit_policy=True"):
            _engine(use_policy=True, policy=None)

    def test_true_with_wrong_type_raises(self):
        with pytest.raises(TypeError, match="ExitPolicy"):
            _engine(use_policy=True, policy="not_a_policy")  # type: ignore[arg-type]

    def test_false_ignores_passed_policy(self):
        policy = ExitPolicy(provider_capability=_cap())
        e = _engine(use_policy=False, policy=policy)
        # Flag desligada → policy NÃO é armazenada (preserva legado)
        assert e._use_exit_policy is False
        assert e._exit_policy is None

    def test_true_with_policy_stores_it(self):
        policy = ExitPolicy(provider_capability=_cap())
        e = _engine(use_policy=True, policy=policy)
        assert e._use_exit_policy is True
        assert e._exit_policy is policy


class TestRunsWithBothPaths:

    def test_legacy_path_runs(self):
        candles = generate_trending_candles(n=150, trend_pct_per_candle=0.0015)
        e = _engine()
        report = e.run(candles)
        assert report is not None
        assert len(report.equity_curve) == len(candles)

    def test_exit_policy_path_runs(self):
        candles = generate_trending_candles(n=150, trend_pct_per_candle=0.0015)
        policy = ExitPolicy(provider_capability=_cap())
        e = _engine(use_policy=True, policy=policy)
        report = e.run(candles)
        assert report is not None
        assert len(report.equity_curve) == len(candles)
