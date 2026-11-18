"""
Testes determinísticos — TrendPullbackStrategy (FASE 10)
==========================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO IA/LLM.

Cobertura:
    - Contrato BaseStrategy (name, generate_signal, reset, evaluate).
    - Determinismo: chamadas idênticas → mesmo sinal.
    - Anti-lookahead: estratégia só usa o último valor visível.
    - HOLD seguro com dados insuficientes / sem tendência / pullback fora /
      RSI sobrecomprado / posição já aberta / estado != RUNNING.
    - BUY válido: SL < entry < TP, todos > 0.
    - position_size_usd vem do construtor (sem hardcode em runtime).
    - StrategySpec/factory: produz instância pronta, sem mutar default_config.

Os testes NÃO exigem lucro. Eles provam contrato + auditoria.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd
import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.base_strategy import StrategyState
from crypto_trading_bot.strategies.signal_model import StrategyAction
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    TrendPullbackStrategy,
    _trend_pullback_factory,
    build_trend_pullback_spec,
)


# ---------------------------------------------------------------------------
# Helpers de teste — features sintéticas determinísticas
# ---------------------------------------------------------------------------

def _features_manual(
    *,
    close: float,
    ema_fast: float,
    ema_slow: float,
    rsi: float,
    atr: float,
    ema_fast_period: int = 20,
    ema_slow_period: int = 50,
    rsi_period: int = 14,
    has_sufficient_data: bool = True,
    symbol: str = "BTCUSDT",
) -> Dict[str, Any]:
    """Constrói dict de features manual para forçar cenários precisos."""
    return {
        "symbol": symbol,
        "last_close": close,
        "last_rsi": rsi,
        "last_atr": atr,
        f"ema_{ema_fast_period}": pd.Series([ema_fast]),
        f"ema_{ema_slow_period}": pd.Series([ema_slow]),
        f"rsi_{rsi_period}": pd.Series([rsi]),
        "has_sufficient_data": has_sufficient_data,
        "n_candles": 200,
    }


def _make_strategy(**overrides) -> TrendPullbackStrategy:
    defaults = dict(
        ema_fast_period=20,
        ema_slow_period=50,
        rsi_period=14,
        rsi_overbought=70.0,
        stop_atr_multiplier=1.5,
        stop_fallback_pct=0.015,
        risk_reward_ratio=2.0,
        position_size_usd=250.0,
    )
    defaults.update(overrides)
    strategy = TrendPullbackStrategy(**defaults)
    strategy.set_running()
    return strategy


def _trend_pullback_candles_with_real_engine(n: int = 200):
    """Constrói candles + FeatureEngine compatíveis com EMA 20/50."""
    candles = generate_trending_candles(
        n=n, base_price=65000.0, trend_pct_per_candle=0.0015
    )
    feature_engine = FeatureEngine(ema_periods=[20, 50])
    return candles, feature_engine


# ---------------------------------------------------------------------------
# Contrato BaseStrategy
# ---------------------------------------------------------------------------

class TestContract:

    def test_name_is_string_with_params(self):
        s = _make_strategy()
        assert isinstance(s.name, str)
        assert "trend_pullback" in s.name
        assert "20" in s.name and "50" in s.name and "14" in s.name

    def test_initial_state_is_warming_up(self):
        # Não chama set_running para verificar estado inicial
        s = TrendPullbackStrategy(position_size_usd=100.0)
        assert s.state == StrategyState.WARMING_UP

    def test_hold_when_not_running(self):
        s = TrendPullbackStrategy(position_size_usd=100.0)  # WARMING_UP
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "inativa" in sig.reason.lower()

    def test_reset_returns_to_warming_up(self):
        s = _make_strategy()
        assert s.state == StrategyState.RUNNING
        s.reset()
        assert s.state == StrategyState.WARMING_UP

    def test_invalid_constructor_raises(self):
        with pytest.raises(ValueError):
            TrendPullbackStrategy(
                ema_fast_period=50, ema_slow_period=20  # fast >= slow
            )
        with pytest.raises(ValueError):
            TrendPullbackStrategy(rsi_overbought=150.0)
        with pytest.raises(ValueError):
            TrendPullbackStrategy(position_size_usd=-1.0)
        with pytest.raises(ValueError):
            TrendPullbackStrategy(risk_reward_ratio=0.0)
        with pytest.raises(ValueError):
            TrendPullbackStrategy(stop_fallback_pct=2.0)


# ---------------------------------------------------------------------------
# Regras de HOLD
# ---------------------------------------------------------------------------

class TestHoldRules:

    def test_hold_when_insufficient_data(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0, has_sufficient_data=False,
        )
        features["n_candles"] = 10
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "insuficientes" in sig.reason.lower()

    def test_hold_when_ema_fast_below_slow_no_uptrend(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=64500.0, ema_slow=65500.0,  # fast < slow
            rsi=50.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "ema" in sig.reason.lower()

    def test_hold_when_no_pullback_close_above_ema_fast(self):
        s = _make_strategy()
        features = _features_manual(
            close=66500.0, ema_fast=65500.0, ema_slow=64000.0,  # close > ema_fast
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "pullback" in sig.reason.lower()

    def test_hold_when_pullback_too_deep_below_ema_slow(self):
        s = _make_strategy()
        features = _features_manual(
            close=63500.0, ema_fast=65500.0, ema_slow=64000.0,  # close < ema_slow
            rsi=45.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "pullback" in sig.reason.lower()

    def test_hold_when_rsi_overbought(self):
        s = _make_strategy(rsi_overbought=70.0)
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=85.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "rsi" in sig.reason.lower()

    def test_hold_when_position_already_open(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig1 = s.evaluate(features)
        assert sig1.action == StrategyAction.BUY
        s.on_signal_approved(sig1.to_trading_signal())
        sig2 = s.evaluate(features)
        assert sig2.action == StrategyAction.HOLD
        assert "posição" in sig2.reason.lower() or "open" in sig2.reason.lower()

    def test_hold_when_invalid_close(self):
        s = _make_strategy()
        features = _features_manual(
            close=0.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD


# ---------------------------------------------------------------------------
# BUY válido + invariantes SL/TP
# ---------------------------------------------------------------------------

class TestBuySignal:

    def test_buy_sl_lt_entry_lt_tp(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.BUY
        assert 0 < sig.stop_loss_price < sig.entry_price
        assert sig.take_profit_price is not None
        assert sig.entry_price < sig.take_profit_price

    def test_stop_uses_atr_when_available(self):
        s = _make_strategy(stop_atr_multiplier=2.0, stop_fallback_pct=0.1)
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=500.0,
        )
        sig = s.evaluate(features)
        # Stop should be entry - 2 * 500 = 64000, NOT entry * 0.9 = 58500
        assert abs(sig.stop_loss_price - 64000.0) < 0.01
        assert sig.metadata.get("stop_source") == "atr"

    def test_stop_uses_fallback_when_atr_nan(self):
        s = _make_strategy(stop_atr_multiplier=2.0, stop_fallback_pct=0.02)
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=float("nan"),
        )
        sig = s.evaluate(features)
        # Stop should be entry * (1 - 0.02) = 63700
        assert abs(sig.stop_loss_price - 63700.0) < 0.01
        assert sig.metadata.get("stop_source") == "fallback_pct"

    def test_take_profit_matches_risk_reward(self):
        s = _make_strategy(stop_atr_multiplier=1.0, risk_reward_ratio=3.0)
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=500.0,
        )
        sig = s.evaluate(features)
        # Stop=64500, risk=500, tp=65000+1500=66500
        assert abs(sig.stop_loss_price - 64500.0) < 0.01
        assert sig.take_profit_price is not None
        assert abs(sig.take_profit_price - 66500.0) < 0.01

    def test_position_size_comes_from_constructor(self):
        s = _make_strategy(position_size_usd=777.5)
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.position_size_usd == 777.5

    def test_leverage_default_one(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.leverage == 1.0

    def test_signal_count_increments_only_on_buy(self):
        s = _make_strategy()
        features_buy = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        features_hold = _features_manual(
            close=65000.0, ema_fast=64500.0, ema_slow=65500.0,  # no uptrend
            rsi=55.0, atr=300.0,
        )
        assert s._signal_count == 0
        s.evaluate(features_hold)
        assert s._signal_count == 0
        s.evaluate(features_buy)
        assert s._signal_count == 1


# ---------------------------------------------------------------------------
# Determinismo + auditabilidade
# ---------------------------------------------------------------------------

class TestDeterminismAndAudit:

    def test_same_features_produce_same_signal(self):
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        s1 = _make_strategy()
        s2 = _make_strategy()
        sig1 = s1.evaluate(features)
        sig2 = s2.evaluate(features)
        assert sig1.action == sig2.action
        assert sig1.entry_price == sig2.entry_price
        assert sig1.stop_loss_price == sig2.stop_loss_price
        assert sig1.take_profit_price == sig2.take_profit_price
        assert sig1.position_size_usd == sig2.position_size_usd

    def test_metadata_contains_indicator_snapshot(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, ema_fast=65500.0, ema_slow=64000.0,
            rsi=55.0, atr=300.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.BUY
        assert "ema_20" in sig.metadata
        assert "ema_50" in sig.metadata
        assert "rsi" in sig.metadata
        assert "atr" in sig.metadata
        assert sig.metadata["rsi"] == 55.0


# ---------------------------------------------------------------------------
# Integração com BacktestEngine (anti-lookahead via candles[:i+1])
# ---------------------------------------------------------------------------

class TestBacktestIntegration:

    def test_runs_in_backtest_without_errors(self):
        candles, feature_engine = _trend_pullback_candles_with_real_engine(150)
        s = _make_strategy()
        engine = BacktestEngine(
            strategy=s,
            risk_engine=RiskEngine(initial_capital=5000.0),
            feature_engine=feature_engine,
            initial_capital=5000.0,
            min_candles=60,
            symbol="BTCUSDT",
        )
        report = engine.run(candles)
        # Não exige lucro. Exige que o engine rode até o fim sem erro.
        assert report.total_trades >= 0
        assert len(report.equity_curve) == len(candles)

    def test_works_on_ranging_market(self):
        candles = generate_ranging_candles(n=150, center_price=65000.0)
        feature_engine = FeatureEngine(ema_periods=[20, 50])
        s = _make_strategy()
        engine = BacktestEngine(
            strategy=s,
            risk_engine=RiskEngine(initial_capital=5000.0),
            feature_engine=feature_engine,
            initial_capital=5000.0,
            min_candles=60,
            symbol="BTCUSDT",
        )
        report = engine.run(candles)
        assert report.total_trades >= 0

    def test_works_on_volatile_market(self):
        candles = generate_volatile_candles(n=150, volatility_pct=0.03)
        feature_engine = FeatureEngine(ema_periods=[20, 50])
        s = _make_strategy()
        engine = BacktestEngine(
            strategy=s,
            risk_engine=RiskEngine(initial_capital=5000.0),
            feature_engine=feature_engine,
            initial_capital=5000.0,
            min_candles=60,
            symbol="BTCUSDT",
        )
        report = engine.run(candles)
        assert report.total_trades >= 0


# ---------------------------------------------------------------------------
# StrategySpec + factory
# ---------------------------------------------------------------------------

class TestStrategySpec:

    def test_spec_builds_and_has_name(self):
        spec = build_trend_pullback_spec()
        assert spec.name == "trend_pullback_default"
        assert "pullback" in (spec.description or "").lower()
        assert "deterministic" in spec.tags

    def test_factory_returns_running_instance(self):
        spec = build_trend_pullback_spec()
        instance = spec.factory(dict(spec.default_config))
        assert isinstance(instance, TrendPullbackStrategy)
        assert instance.state == StrategyState.RUNNING

    def test_factory_does_not_mutate_default_config(self):
        spec = build_trend_pullback_spec()
        config_snapshot = dict(spec.default_config)
        _ = spec.factory(dict(spec.default_config))
        # default_config is MappingProxyType - cannot be mutated directly,
        # but verify content remained equal even after calling factory
        assert dict(spec.default_config) == config_snapshot

    def test_factory_accepts_override_position_size(self):
        instance = _trend_pullback_factory({"position_size_usd": 999.0})
        assert instance._position_size_usd == 999.0
