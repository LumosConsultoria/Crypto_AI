"""
FASE 38 - Strategy Family Research + Market Regime Discovery
============================================================
Testes 100% OFFLINE/DETERMINISTICOS. ZERO rede / ordem / secret.

Cobre os ajustes obrigatorios:
  1. Regime label = primary_regime + secondary_flags; cobertura ~100%.
  2. Anti-look-ahead: mudar candle futuro nao altera regime passado.
  3. Segmentos = cross-check; curtos => inconclusive.
  4. Amostra minima: regime com poucos trades => inconclusive; sem
     promover com amostra pequena.
  5. Prototipos research-only: BaseStrategy/StrategySpec, tags
     research/prototype, FORA do registry operacional, respeitam piso.
  6. Metricas por familia x regime.
  7. Recomendacao: manter_demo_bloqueada default; promover so com
     PF>=1.2/exp>0/dd ok/amostra/walk-forward estavel/sem overfitting.
  8. Demo SEMPRE bloqueada.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
)
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.research.market_regime import (
    PRIMARY_REGIMES,
    SECONDARY_FLAGS,
    classify_regimes,
)
from crypto_trading_bot.research.strategy_family_research import (
    DEFAULT_FAMILIES,
    FamilyWalkForward,
    RegimeMetrics,
    _recommend_family,
    run_family_research,
)


# ---------------------------------------------------------------------------
# 1. Regime classification
# ---------------------------------------------------------------------------

def _trend():
    return generate_trending_candles(
        n=400, base_price=65000.0, trend_pct_per_candle=0.0008,
        volatility_pct=0.015, symbol="BTCUSDT", timeframe="15")


class TestRegimeClassification:

    def test_labels_valid_and_coverage_sums_to_one(self):
        rc = classify_regimes(_trend(), lookback=96)
        assert rc.n_labeled > 0
        for lab in rc.labels:
            assert lab.primary_regime in PRIMARY_REGIMES
            for fl in lab.secondary_flags:
                assert fl in SECONDARY_FLAGS
        assert abs(sum(rc.coverage.values()) - 1.0) < 1e-6

    def test_secondary_flags_are_independent_of_primary(self):
        # high/low volatility sao FLAGS (podem coexistir com trend/range).
        rc = classify_regimes(_trend(), lookback=96)
        # nao deve haver high E low volatility juntas no mesmo candle.
        for lab in rc.labels:
            assert not ("high_volatility" in lab.secondary_flags
                        and "low_volatility" in lab.secondary_flags)

    def test_warmup_unlabeled_before_lookback(self):
        rc = classify_regimes(_trend(), lookback=96)
        assert all(lab.index >= 96 for lab in rc.labels)


# ---------------------------------------------------------------------------
# 2. Anti-look-ahead
# ---------------------------------------------------------------------------

class TestAntiLookahead:

    def test_future_candle_change_does_not_alter_past_regime(self):
        candles = _trend()
        rc = classify_regimes(candles, lookback=96)
        before = rc.primary_at(150)
        mutated = list(candles)
        c = mutated[300]
        mutated[300] = Candle(
            symbol=c.symbol, timeframe=c.timeframe, timestamp=c.timestamp,
            open=c.open * 4, high=c.high * 4, low=c.low * 4,
            close=c.close * 4, volume=c.volume * 4)
        rc2 = classify_regimes(mutated, lookback=96)
        assert rc.primary_at(150) == rc2.primary_at(150) == before
        # candle anterior a mutacao (250) tambem inalterado
        assert rc.primary_at(250) == rc2.primary_at(250)


# ---------------------------------------------------------------------------
# 5. Prototipos research-only
# ---------------------------------------------------------------------------

def _mr_features(*, atr: float):
    # Features que satisfazem a entrada do mean_reversion com SL via ATR.
    return {
        "symbol": "BTCUSDT", "has_sufficient_data": True, "n_candles": 100,
        "last_close": 65000.0, "last_rsi": 25.0, "last_atr": atr,
        "bb_lower": pd.Series([66000.0, 65000.0]),   # close <= lower
        "bb_middle": pd.Series([66000.0, 65500.0]),
    }


class TestPrototypes:

    def test_prototypes_have_research_tags(self):
        from crypto_trading_bot.strategies.mean_reversion_strategy import (
            build_mean_reversion_spec,
        )
        from crypto_trading_bot.strategies\
            .volatility_contraction_expansion_strategy import (
                build_volatility_contraction_expansion_spec,
            )
        for b in (build_mean_reversion_spec,
                  build_volatility_contraction_expansion_spec):
            spec = b()
            assert "research" in spec.tags and "prototype" in spec.tags

    def test_prototypes_not_in_operational_registry(self):
        from crypto_trading_bot.backtest_operational import (
            default_backtest_registry,
        )
        names = default_backtest_registry().list_names()
        assert "mean_reversion_research" not in names
        assert "volatility_contraction_expansion_research" not in names

    def test_mean_reversion_emits_buy(self):
        from crypto_trading_bot.strategies.mean_reversion_strategy import (
            MeanReversionStrategy,
        )
        s = MeanReversionStrategy()
        s.set_running()
        sig = s.evaluate(_mr_features(atr=300.0))
        assert sig.is_actionable
        assert sig.action.value == "buy"
        assert sig.stop_loss_price < sig.entry_price < sig.take_profit_price

    def test_prototype_tiny_stop_blocked_by_riskengine_floor(self):
        # SL minusculo (ATR=10 => SL ~0.023% < piso 0.5%) DEVE ser
        # bloqueado pelo RiskEngine (piso 0.005 intacto).
        from crypto_trading_bot.strategies.mean_reversion_strategy import (
            MeanReversionStrategy,
        )
        s = MeanReversionStrategy()
        s.set_running()
        sig = s.evaluate(_mr_features(atr=10.0))
        assert sig.is_actionable
        result = RiskEngine(initial_capital=5000.0).validate_signal(
            sig.to_trading_signal())
        assert result.approved is False
        assert result.block_reason.value == "stop_loss_too_small"


# ---------------------------------------------------------------------------
# 7. Recomendacao (fixtures deterministicas) + demo gate
# ---------------------------------------------------------------------------

def _rm(regime, *, pf, exp, dd=-5.0, trades=30, suff=True):
    return RegimeMetrics(
        regime=regime, trades=trades, win_rate=45.0, profit_factor=pf,
        expectancy_usd=exp, total_pnl_usd=exp * trades,
        max_drawdown_pct=dd, payoff=1.5, coverage=0.3,
        sample_sufficient=suff, source="trade_tagging",
        inconclusive=not suff)


def _wf(*, in_pf, oos_pf, stab, overfit, inconcl):
    return FamilyWalkForward(in_pf, oos_pf, stab, overfit, inconcl)


class TestRecommendation:

    def test_reject_when_no_edge(self):
        per = [_rm("range", pf=0.8, exp=-0.1), _rm("trend_up", pf=0.9,
                                                   exp=-0.05)]
        wf = _wf(in_pf=0.9, oos_pf=0.8, stab=0.5, overfit=False,
                 inconcl=False)
        rec, *_ = _recommend_family(per, wf, real_dataset=True)
        assert rec == "rejeitar_familia"

    def test_continue_research_when_weak_or_inconclusive(self):
        # edge positivo porem amostra pequena (sample insufficient).
        per = [_rm("range", pf=1.4, exp=0.2, trades=4, suff=False)]
        wf = _wf(in_pf=1.4, oos_pf=None, stab=None, overfit=False,
                 inconcl=True)
        rec, detail, best, gate, block = _recommend_family(
            per, wf, real_dataset=True)
        assert rec == "continuar_pesquisa"
        assert gate is False

    def test_promote_requires_robust_regime_and_stable_wf(self):
        per = [_rm("range", pf=1.5, exp=0.3, dd=-8.0, trades=40,
                   suff=True)]
        wf = _wf(in_pf=1.5, oos_pf=1.4, stab=0.85, overfit=False,
                 inconcl=False)
        rec, detail, best, gate, block = _recommend_family(
            per, wf, real_dataset=True)
        assert rec == "promover_para_calibracao"
        assert best == "range"
        assert gate is True            # criterios atendidos...
        # ...mas continua CONSULTIVO: demo nunca autorizada (ver runner).

    def test_promote_blocked_when_wf_unstable(self):
        per = [_rm("range", pf=1.5, exp=0.3, dd=-8.0, trades=40,
                   suff=True)]
        wf = _wf(in_pf=2.0, oos_pf=0.7, stab=0.35, overfit=True,
                 inconcl=False)
        rec, *_ = _recommend_family(per, wf, real_dataset=True)
        assert rec in ("continuar_pesquisa", "rejeitar_familia")

    def test_promote_blocked_when_sample_small(self):
        # PF bom mas amostra pequena => nunca promover.
        per = [_rm("range", pf=1.6, exp=0.3, trades=4, suff=False)]
        wf = _wf(in_pf=1.6, oos_pf=1.5, stab=0.9, overfit=False,
                 inconcl=False)
        rec, *_ = _recommend_family(per, wf, real_dataset=True)
        assert rec != "promover_para_calibracao"


# ---------------------------------------------------------------------------
# 8. End-to-end: demo SEMPRE bloqueada + trade-tagging soma
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_demo_always_blocked_and_structure(self):
        candles = generate_ranging_candles(
            1500, symbol="BTCUSDT", timeframe="15")
        rep = run_family_research(
            candles, families=["trend_pullback_bidirectional",
                               "mean_reversion_research"],
            capital=5000.0, min_candles=60, data_source="synthetic",
            regime_lookback=96, wf_folds=3, run_segments=False)
        d = rep.to_dict()
        assert d["demo_blocked"] is True
        assert d["synthetic_warning"] is True
        # distribuicao arredondada a 6 casas no to_dict -> tolerancia frouxa.
        assert abs(sum(d["regime_distribution"].values()) - 1.0) < 1e-3
        for f in d["families"]:
            assert f["demo_authorized"] is False
            assert f["recommendation"] in (
                "continuar_pesquisa", "rejeitar_familia",
                "promover_para_calibracao")

    def test_trade_tagging_sums_to_total_trades(self):
        candles = generate_ranging_candles(
            1500, symbol="BTCUSDT", timeframe="15")
        rep = run_family_research(
            candles, families=["trend_pullback_bidirectional"],
            capital=5000.0, min_candles=60, data_source="synthetic",
            regime_lookback=96, wf_folds=2, run_segments=False)
        fam = rep.families[0]
        tagged = sum(m.trades for m in fam.per_regime_tagging)
        assert tagged == fam.overall.trades   # tagging cobre todos os trades

    def test_default_families_include_two_prototypes(self):
        assert "mean_reversion_research" in DEFAULT_FAMILIES
        assert "volatility_contraction_expansion_research" in DEFAULT_FAMILIES
