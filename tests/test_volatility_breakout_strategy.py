"""
Testes determinísticos — VolatilityBreakoutStrategy (FASE 10)
==============================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO IA/LLM.

Cobertura:
    - Contrato BaseStrategy.
    - HOLD: dados insuficientes, sem rompimento, bandwidth abaixo,
      filtro direcional falha, posição aberta, indicadores NaN.
    - BUY válido: SL < entry < TP, todos > 0.
    - Determinismo + auditabilidade (metadata).
    - position_size_usd vem do construtor.
    - StrategySpec + factory.
    - Integração com BacktestEngine (anti-lookahead via candles[:i+1]).
"""

from __future__ import annotations

from typing import Any, Dict

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
from crypto_trading_bot.strategies.volatility_breakout_strategy import (
    VolatilityBreakoutStrategy,
    _volatility_breakout_factory,
    build_volatility_breakout_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _features_manual(
    *,
    close: float,
    bb_upper: float,
    bb_bandwidth: float,
    ema_dir: float,
    atr: float,
    direction_filter_period: int = 50,
    has_sufficient_data: bool = True,
    symbol: str = "BTCUSDT",
) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "last_close": close,
        "last_atr": atr,
        "last_bb_upper": bb_upper,
        "bb_bandwidth": pd.Series([bb_bandwidth]),
        f"ema_{direction_filter_period}": pd.Series([ema_dir]),
        "has_sufficient_data": has_sufficient_data,
        "n_candles": 200,
    }


def _make_strategy(**overrides) -> VolatilityBreakoutStrategy:
    defaults = dict(
        direction_filter_period=50,
        min_bandwidth=0.015,
        breakout_buffer_pct=0.0,
        stop_atr_multiplier=1.5,
        stop_fallback_pct=0.015,
        risk_reward_ratio=2.0,
        position_size_usd=300.0,
    )
    defaults.update(overrides)
    strategy = VolatilityBreakoutStrategy(**defaults)
    strategy.set_running()
    return strategy


# ---------------------------------------------------------------------------
# Contrato BaseStrategy
# ---------------------------------------------------------------------------

class TestContract:

    def test_name_is_string_with_params(self):
        s = _make_strategy()
        assert isinstance(s.name, str)
        assert "vol_breakout" in s.name
        assert "e50" in s.name

    def test_initial_state_is_warming_up(self):
        s = VolatilityBreakoutStrategy(position_size_usd=100.0)
        assert s.state == StrategyState.WARMING_UP

    def test_hold_when_not_running(self):
        s = VolatilityBreakoutStrategy(position_size_usd=100.0)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
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
            VolatilityBreakoutStrategy(direction_filter_period=0)
        with pytest.raises(ValueError):
            VolatilityBreakoutStrategy(min_bandwidth=-0.1)
        with pytest.raises(ValueError):
            VolatilityBreakoutStrategy(breakout_buffer_pct=-0.01)
        with pytest.raises(ValueError):
            VolatilityBreakoutStrategy(position_size_usd=0.0)
        with pytest.raises(ValueError):
            VolatilityBreakoutStrategy(risk_reward_ratio=-1.0)


# ---------------------------------------------------------------------------
# Regras de HOLD
# ---------------------------------------------------------------------------

class TestHoldRules:

    def test_hold_when_insufficient_data(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0, has_sufficient_data=False,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "insuficientes" in sig.reason.lower()

    def test_hold_when_no_breakout(self):
        s = _make_strategy()
        features = _features_manual(
            close=65000.0, bb_upper=65500.0, bb_bandwidth=0.03,  # close < bb_upper
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "rompimento" in sig.reason.lower()

    def test_hold_when_bandwidth_below_minimum(self):
        s = _make_strategy(min_bandwidth=0.05)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.01,  # bandwidth < min
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "bandwidth" in sig.reason.lower()

    def test_hold_when_directional_filter_fails(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=66500.0, atr=400.0,  # close < ema_dir
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "direcional" in sig.reason.lower()

    def test_hold_when_position_already_open(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig1 = s.evaluate(features)
        assert sig1.action == StrategyAction.BUY
        s.on_signal_approved(sig1.to_trading_signal())
        sig2 = s.evaluate(features)
        assert sig2.action == StrategyAction.HOLD
        assert ("posição" in sig2.reason.lower()
                or "open" in sig2.reason.lower())

    def test_hold_when_bb_upper_unavailable(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=float("nan"), bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.HOLD
        assert "bb_upper" in sig.reason.lower()


# ---------------------------------------------------------------------------
# BUY válido + invariantes SL/TP
# ---------------------------------------------------------------------------

class TestBuySignal:

    def test_buy_sl_lt_entry_lt_tp(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.BUY
        assert 0 < sig.stop_loss_price < sig.entry_price
        assert sig.take_profit_price is not None
        assert sig.entry_price < sig.take_profit_price

    def test_stop_uses_atr_when_available(self):
        s = _make_strategy(stop_atr_multiplier=2.0, stop_fallback_pct=0.1)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=500.0,
        )
        sig = s.evaluate(features)
        # Stop = 66000 - 2*500 = 65000
        assert abs(sig.stop_loss_price - 65000.0) < 0.01
        assert sig.metadata.get("stop_source") == "atr"

    def test_stop_uses_fallback_when_atr_nan(self):
        s = _make_strategy(stop_atr_multiplier=2.0, stop_fallback_pct=0.02)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=float("nan"),
        )
        sig = s.evaluate(features)
        # Stop = 66000 * 0.98 = 64680
        assert abs(sig.stop_loss_price - 64680.0) < 0.01
        assert sig.metadata.get("stop_source") == "fallback_pct"

    def test_take_profit_matches_risk_reward(self):
        s = _make_strategy(stop_atr_multiplier=1.0, risk_reward_ratio=3.0)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=500.0,
        )
        sig = s.evaluate(features)
        # Stop = 65500, risk = 500, tp = 66000 + 1500 = 67500
        assert abs(sig.stop_loss_price - 65500.0) < 0.01
        assert sig.take_profit_price is not None
        assert abs(sig.take_profit_price - 67500.0) < 0.01

    def test_position_size_comes_from_constructor(self):
        s = _make_strategy(position_size_usd=888.5)
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.position_size_usd == 888.5

    def test_leverage_default_one(self):
        s = _make_strategy()
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.leverage == 1.0

    def test_breakout_buffer_blocks_marginal_close(self):
        s = _make_strategy(breakout_buffer_pct=0.01)  # exige 1% acima
        features = _features_manual(
            close=65600.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        # 65600 < 65500*1.01 = 66155 → HOLD
        assert sig.action == StrategyAction.HOLD
        assert "rompimento" in sig.reason.lower()


# ---------------------------------------------------------------------------
# Determinismo + auditabilidade
# ---------------------------------------------------------------------------

class TestDeterminismAndAudit:

    def test_same_features_produce_same_signal(self):
        features = _features_manual(
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
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
            close=66000.0, bb_upper=65500.0, bb_bandwidth=0.03,
            ema_dir=64500.0, atr=400.0,
        )
        sig = s.evaluate(features)
        assert sig.action == StrategyAction.BUY
        assert "bb_upper" in sig.metadata
        assert "bb_bandwidth" in sig.metadata
        assert "ema_50" in sig.metadata
        assert "atr" in sig.metadata


# ---------------------------------------------------------------------------
# Integração com BacktestEngine
# ---------------------------------------------------------------------------

class TestBacktestIntegration:

    def test_runs_in_backtest_on_volatile_market(self):
        candles = generate_volatile_candles(
            n=200, volatility_pct=0.04, trend_pct_per_candle=0.001
        )
        feature_engine = FeatureEngine(ema_periods=[20, 50])
        s = _make_strategy(min_bandwidth=0.005)
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
        assert len(report.equity_curve) == len(candles)

    def test_runs_in_backtest_on_trending_market(self):
        candles = generate_trending_candles(n=200, trend_pct_per_candle=0.002)
        feature_engine = FeatureEngine(ema_periods=[20, 50])
        s = _make_strategy(min_bandwidth=0.005)
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

    def test_runs_in_backtest_on_ranging_market(self):
        candles = generate_ranging_candles(n=200, center_price=65000.0)
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
        spec = build_volatility_breakout_spec()
        assert spec.name == "vol_breakout_default"
        assert "rompimento" in (spec.description or "").lower()
        assert "deterministic" in spec.tags

    def test_factory_returns_running_instance(self):
        spec = build_volatility_breakout_spec()
        instance = spec.factory(dict(spec.default_config))
        assert isinstance(instance, VolatilityBreakoutStrategy)
        assert instance.state == StrategyState.RUNNING

    def test_factory_does_not_mutate_default_config(self):
        spec = build_volatility_breakout_spec()
        config_snapshot = dict(spec.default_config)
        _ = spec.factory(dict(spec.default_config))
        assert dict(spec.default_config) == config_snapshot

    def test_factory_accepts_override_position_size(self):
        instance = _volatility_breakout_factory({"position_size_usd": 555.0})
        assert instance._position_size_usd == 555.0
