"""
FASE 39 - Regime Window Analysis (temporal / hypothesis expansion)
==================================================================
Testes 100% OFFLINE/DETERMINISTICOS. ZERO rede / ordem / secret / download.

Cobre os ajustes obrigatorios:
  1. Janelas separadas: full_period / monthly_windows / reference_windows;
     estabilidade SO sobre monthly (refs nao inflam sign_consistency).
  2. Meses com pouca amostra => sample_sufficient=False; nao promovem.
  3. Divergencia => window_sensitive / nunca por janela isolada.
  4. Anti-lookahead preservado por janela (slice reusa rotulos causais).
  5/6. Backlog/paper; sem implementar; sem baixar dados.
  7. Demo gate: demo_blocked=True e demo_authorized=False sempre.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
)
from crypto_trading_bot.backtesting.data_splits import split_by_calendar_month
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.market_regime import classify_regimes
from crypto_trading_bot.research.strategy_family_research import (
    FamilyRegimeReport,
    FamilyWalkForward,
    RegimeMetrics,
)
from crypto_trading_bot.research.regime_window_analysis import (
    HYPOTHESIS_BACKLOG,
    FamilyRegimeStability,
    _mr_range_verdict,
    _slice_classification,
    run_regime_window_analysis,
)


def _candle(ts):
    return Candle(symbol="BTCUSDT", timeframe="15", timestamp=ts,
                  open=100.0, high=101.0, low=99.0, close=100.0,
                  volume=10.0)


# ---------------------------------------------------------------------------
# 1. split_by_calendar_month
# ---------------------------------------------------------------------------

class TestSplitByMonth:

    def test_three_months_contiguous_and_complete(self):
        candles = []
        for m, n in ((1, 50), (2, 40), (3, 30)):
            base = datetime(2025, m, 1, tzinfo=timezone.utc)
            for i in range(n):
                candles.append(_candle(base + timedelta(minutes=15 * i)))
        windows = split_by_calendar_month(candles)
        assert [w[0] for w in windows] == ["2025-01", "2025-02", "2025-03"]
        assert windows[0] == ("2025-01", 0, 49)
        assert windows[1] == ("2025-02", 50, 89)
        assert windows[2] == ("2025-03", 90, 119)
        # cobertura total e contiguidade
        assert windows[0][1] == 0
        assert windows[-1][2] == len(candles) - 1
        for a, b in zip(windows, windows[1:]):
            assert b[1] == a[2] + 1

    def test_empty(self):
        assert split_by_calendar_month([]) == []

    def test_deterministic(self):
        candles = generate_ranging_candles(
            3000, symbol="BTCUSDT", timeframe="15")
        assert split_by_calendar_month(candles) == \
            split_by_calendar_month(candles)


# ---------------------------------------------------------------------------
# 4. Anti-lookahead: slice reusa rotulos causais (mesmo regime que o full)
# ---------------------------------------------------------------------------

class TestSliceClassification:

    def test_window_labels_match_full_series(self):
        candles = generate_ranging_candles(
            2000, symbol="BTCUSDT", timeframe="15")
        rc = classify_regimes(candles, lookback=96)
        start, end = 500, 900
        win = _slice_classification(rc, start, end)
        # cada rotulo da janela == rotulo global re-indexado (sem recomputo)
        full_by_idx = {lab.index: lab.primary_regime for lab in rc.labels}
        for lab in win.labels:
            g = lab.index + start
            assert full_by_idx[g] == lab.primary_regime
        # cobertura soma ~1
        assert abs(sum(win.coverage.values()) - 1.0) < 1e-9 or \
            win.n_labeled == 0


# ---------------------------------------------------------------------------
# Verdict mean_reversion-in-range (fixtures deterministicas)
# ---------------------------------------------------------------------------

def _rm(regime, *, pf, exp, trades=50, suff=True):
    return RegimeMetrics(
        regime=regime, trades=trades, win_rate=45.0, profit_factor=pf,
        expectancy_usd=exp, total_pnl_usd=exp * trades,
        max_drawdown_pct=-5.0, payoff=1.4, coverage=0.5,
        sample_sufficient=suff, source="trade_tagging",
        inconclusive=not suff)


def _fr(range_metrics, *, wf_inconcl=False):
    return FamilyRegimeReport(
        family="mean_reversion_research", is_prototype=True,
        overall=_rm("ALL", pf=range_metrics.profit_factor,
                    exp=range_metrics.expectancy_usd),
        overall_blocked_reasons={},
        per_regime_tagging=(range_metrics,), per_regime_segments=(),
        walk_forward=FamilyWalkForward(1.0, 1.0, 0.8, False, wf_inconcl),
        cost_realistic_pnl_usd=0.0, recommendation="x",
        recommendation_detail="", best_regime=None,
        demo_authorized=False, demo_block_reason="")


def _stab(sign_consistency, *, n_suff=4):
    return FamilyRegimeStability(
        family="mean_reversion_research", regime="range", n_months=5,
        n_sample_sufficient=n_suff, mean_pf=1.05, std_pf=0.1,
        mean_expectancy=0.05, std_expectancy=0.1,
        sign_consistency=sign_consistency, mean_coverage=0.5)


class TestMeanReversionVerdict:

    def test_insufficient_when_zero_range_trades(self):
        fr = _fr(_rm("range", pf=None, exp=0.0, trades=0, suff=False))
        v = _mr_range_verdict({"mean_reversion_research": fr}, [])
        assert v.verdict == "insuficiencia_amostra"

    def test_pista_when_positive_but_pf_below_promote(self):
        fr = _fr(_rm("range", pf=1.05, exp=0.05, trades=60, suff=True))
        v = _mr_range_verdict({"mean_reversion_research": fr},
                              [_stab(0.7)])
        assert v.verdict == "pista_para_pesquisa"

    def test_reject_when_negative_expectancy(self):
        fr = _fr(_rm("range", pf=0.8, exp=-0.1, trades=60, suff=True))
        v = _mr_range_verdict({"mean_reversion_research": fr},
                              [_stab(0.7)])
        assert v.verdict == "rejeitar"

    def test_ruido_when_window_sensitive(self):
        # exp>0, PF>=1.2 mas consistencia mensal baixa => ruido.
        fr = _fr(_rm("range", pf=1.3, exp=0.1, trades=60, suff=True))
        v = _mr_range_verdict({"mean_reversion_research": fr},
                              [_stab(0.3)])
        assert v.window_sensitive is True
        assert v.verdict == "ruido"


# ---------------------------------------------------------------------------
# 7. End-to-end: demo SEMPRE bloqueada + estrutura
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_demo_always_blocked_and_structure(self):
        # ~6000 candles 15m => ~2 meses; familias reduzidas p/ velocidade.
        candles = generate_ranging_candles(
            6000, symbol="BTCUSDT", timeframe="15")
        rep = run_regime_window_analysis(
            candles, families=["trend_pullback_bidirectional",
                               "mean_reversion_research"],
            capital=5000.0, min_candles=60, data_source="synthetic",
            regime_lookback=96, wf_folds=2,
            reference_windows=[("ref", "2024-01-01", "2024-01-10")],
            min_window_candles=200)
        d = rep.to_dict()
        assert d["demo_blocked"] is True
        assert d["demo_authorized"] is False
        assert d["partial"] is False
        assert d["full_period"] is not None
        assert d["monthly_windows"]
        assert d["reference_windows"]            # referencia separada
        assert d["mean_reversion_range_verdict"] is not None
        assert d["decision"] in (
            "promover_para_calibracao", "continuar_pesquisa",
            "expandir_dataset", "criar_nova_familia_research",
            "rejeitar_definitivamente", "manter_demo_bloqueada")
        assert len(d["hypothesis_backlog"]) == len(HYPOTHESIS_BACKLOG)

    def test_reference_windows_not_in_stability(self):
        # estabilidade so olha monthly_windows; reference nao contribui.
        candles = generate_ranging_candles(
            6000, symbol="BTCUSDT", timeframe="15")
        rep = run_regime_window_analysis(
            candles, families=["mean_reversion_research"],
            capital=5000.0, min_candles=60, data_source="synthetic",
            regime_lookback=96, wf_folds=2,
            reference_windows=[("ref", "2024-01-01", "2024-01-10")],
            min_window_candles=200)
        d = rep.to_dict()
        # n_months da estabilidade <= numero de monthly avaliados
        monthly_eval = [w for w in d["monthly_windows"] if w["families"]]
        for s in d["stability"]:
            assert s["n_months"] <= len(monthly_eval)


# ---------------------------------------------------------------------------
# 5/6. Backlog (paper) com campos obrigatorios
# ---------------------------------------------------------------------------

class TestBacklog:

    def test_backlog_fields(self):
        assert len(HYPOTHESIS_BACKLOG) >= 5
        for h in HYPOTHESIS_BACKLOG:
            for k in ("hypothesis", "target_regime", "success_criterion",
                      "overfitting_risk", "data_needed",
                      "suggested_priority"):
                assert k in h and h[k]
