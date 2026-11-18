"""
Tests - FASE 25 Bloco 1: alinhamento estrutural Strategy <-> FeatureEngine
==========================================================================
100% offline. ZERO network. ZERO secrets.

Regression guard: garante que nenhuma strategy suportada fica em HOLD
perpetuo por feature ausente. Ataca o root cause do "0 trades" da FASE 24
(TrendPullbackStrategy buscava ema_20/ema_50 mas FeatureEngine default
gerava apenas ema_9/ema_21).

Cobre:
    - FeatureEngine() default produz ema_20 e ema_50.
    - FeatureEngine.from_strategy_spec(trend_pullback_spec) garante
      ema_fast/slow_period nas features.
    - FeatureEngine.from_strategy_spec(vol_breakout_spec) garante
      direction_filter_period nas features.
    - Todas as strategies de SUPPORTED_STRATEGIES sao cobertas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.challenge_readiness.strategy_factory import (
    SUPPORTED_STRATEGIES, build_strategy_spec,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle


def _make_candles(n: int):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = []
    price = 65000.0
    for i in range(n):
        candles.append(Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=start + timedelta(minutes=15 * i),
            open=round(price, 2),
            high=round(price * 1.001, 2),
            low=round(price * 0.999, 2),
            close=round(price * 1.0001, 2),
            volume=100.0,
        ))
        price *= 1.0001
    return candles


class TestFeatureEngineDefaults:
    """Defesa em profundidade (Preferencia B do plano)."""

    def test_default_ema_periods_include_20_and_50(self):
        engine = FeatureEngine()
        candles = _make_candles(80)
        features = engine.compute(candles)
        # CHAVE: estes sao consumidos por TrendPullbackStrategy e
        # VolatilityBreakoutStrategy.
        assert "ema_20" in features, (
            "ema_20 ausente do FeatureEngine default - root cause da "
            "regressao FASE 24"
        )
        assert "ema_50" in features
        # Mantemos legado (9/21) por compatibilidade com BotEngine antigo.
        assert "ema_9" in features
        assert "ema_21" in features

    def test_ema_20_not_nan_with_sufficient_data(self):
        engine = FeatureEngine()
        features = engine.compute(_make_candles(80))
        ema_20 = features["ema_20"]
        # iloc[-1] nao pode ser NaN com 80 candles.
        import math
        last = float(ema_20.iloc[-1])
        assert not math.isnan(last)

    def test_ema_50_not_nan_with_sufficient_data(self):
        engine = FeatureEngine()
        features = engine.compute(_make_candles(80))
        ema_50 = features["ema_50"]
        import math
        last = float(ema_50.iloc[-1])
        assert not math.isnan(last)


class TestFromStrategySpec:
    """Preferencia A do plano: alinhamento estrito por spec."""

    def test_from_strategy_spec_trend_pullback(self):
        spec = build_strategy_spec("trend_pullback")
        engine = FeatureEngine.from_strategy_spec(spec)
        features = engine.compute(_make_candles(80))
        # trend_pullback usa ema_fast=20, ema_slow=50
        assert "ema_20" in features
        assert "ema_50" in features

    def test_from_strategy_spec_volatility_breakout(self):
        spec = build_strategy_spec("volatility_breakout")
        engine = FeatureEngine.from_strategy_spec(spec)
        features = engine.compute(_make_candles(80))
        # vol_breakout usa direction_filter_period=50
        assert "ema_50" in features

    def test_from_strategy_spec_preserves_defaults(self):
        """Mesmo com spec custom, defaults defensivos permanecem."""
        spec = build_strategy_spec("trend_pullback")
        engine = FeatureEngine.from_strategy_spec(spec)
        features = engine.compute(_make_candles(80))
        # Defaults [9, 20, 21, 50] todos presentes (defesa em
        # profundidade preserva legado).
        for p in (9, 20, 21, 50):
            assert f"ema_{p}" in features


class TestAllSupportedStrategiesAligned:
    """Nenhuma strategy de SUPPORTED_STRATEGIES fica em HOLD perpetuo
    por feature ausente."""

    @pytest.mark.parametrize("strategy_name", list(SUPPORTED_STRATEGIES))
    def test_strategy_features_present(self, strategy_name):
        spec = build_strategy_spec(strategy_name)
        engine = FeatureEngine.from_strategy_spec(spec)
        features = engine.compute(_make_candles(80))
        # Cada strategy precisa ao menos das features comuns:
        for required in (
            "last_close", "last_rsi", "last_atr",
            "last_bb_upper", "last_bb_lower",
        ):
            assert required in features, (
                f"strategy {strategy_name}: feature {required} ausente"
            )

    @pytest.mark.parametrize("strategy_name", list(SUPPORTED_STRATEGIES))
    def test_strategy_specific_emas_present(self, strategy_name):
        spec = build_strategy_spec(strategy_name)
        engine = FeatureEngine.from_strategy_spec(spec)
        features = engine.compute(_make_candles(80))
        # Leitura dos periods da spec
        default_config = dict(spec.default_config or {})
        candidate_keys = [
            default_config.get("ema_fast_period"),
            default_config.get("ema_slow_period"),
            default_config.get("direction_filter_period"),
        ]
        for p in candidate_keys:
            if isinstance(p, int) and p > 0:
                assert f"ema_{p}" in features, (
                    f"strategy {strategy_name}: ema_{p} ausente"
                )
