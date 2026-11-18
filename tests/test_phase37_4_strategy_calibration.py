"""
FASE 37.4 - Strategy Calibration Offline + Cost Realism
=======================================================
Testes 100% OFFLINE/DETERMINISTICOS. ZERO rede / ordem / secret.

Cobre os 6 ajustes obrigatorios do operador:
  1. Filtro de stop com nome explicito (stop_loss_floor_filter_pct ->
     min_stop_loss_pct), filtro de SINAL, nunca baixa o piso.
  2. precompute_features default-off + equivalencia + anti-look-ahead +
     sem vazamento de futuro no walk-forward.
  3. Cost realism ROTULADO (zero/realistic_research/stressed_research),
     override; custo nao e limite de risco.
  4. Selecao de variantes para cost sweep DETERMINISTICA (nao-dominada).
  5. Walk-forward: "ajustar" so com estabilidade e sem overfitting;
     inconclusivo => manual_review/rejeitar, nunca ajustar.
  6. Demo gate: bloquear_demo default; demo NUNCA autorizada.
"""

from __future__ import annotations

import math

import pytest

from crypto_trading_bot.backtesting import BacktestEngine
from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.research.strategy_research import evaluate_strategy
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    build_trend_pullback_spec,
)
from crypto_trading_bot.research.calibration_costs import (
    COST_SCENARIO_LABELS,
    build_cost_scenario,
    default_cost_sweep,
)
from crypto_trading_bot.research.strategy_calibration import (
    VariantMetrics,
    VariantResult,
    WalkForwardEval,
    _recommend,
    build_ofat_variants,
    run_calibration,
    select_for_followup,
)


# ---------------------------------------------------------------------------
# 1. OFAT builders + nome explicito do filtro de stop
# ---------------------------------------------------------------------------

class TestOfatBuilders:

    def test_bidirectional_has_all_axes_incl_stop_filter(self):
        names = [n for n, a, v, o in build_ofat_variants(
            "trend_pullback_bidirectional")]
        assert any(n.startswith("stop_atr_multiplier=") for n in names)
        assert any(n.startswith("risk_reward_ratio=") for n in names)
        assert "stop_loss_floor_filter_pct=off" in names
        assert "stop_loss_floor_filter_pct=0.005" in names

    def test_filter_maps_to_signal_param_not_floor(self):
        # O eixo de filtro mapeia para min_stop_loss_pct (filtro de
        # SINAL); valor 'off' = sem override (nao toca no piso real).
        variants = build_ofat_variants("trend_pullback_bidirectional")
        by_name = {n: o for n, a, v, o in variants}
        assert by_name["stop_loss_floor_filter_pct=off"] == {}
        assert by_name["stop_loss_floor_filter_pct=0.005"] == {
            "min_stop_loss_pct": 0.005}

    def test_volatility_breakout_has_no_stop_filter_axis(self):
        names = [n for n, a, v, o in build_ofat_variants(
            "volatility_breakout")]
        assert not any("stop_loss_floor_filter" in n for n in names)


# ---------------------------------------------------------------------------
# 2. precompute: equivalencia + anti-look-ahead + walk-forward sem vazamento
# ---------------------------------------------------------------------------

def _fp(rep):
    return (
        rep.total_trades, round(rep.total_pnl_usd, 6),
        rep.risk_blocked_count, round(rep.max_drawdown_pct, 6),
        [(t.side, round(t.entry_price, 6),
          round(t.pnl_usd, 6) if t.pnl_usd is not None else None)
         for t in rep.trades],
    )


class TestPrecompute:

    def test_default_off_signature(self):
        # evaluate_strategy aceita precompute_features e default e False.
        import inspect
        sig = inspect.signature(evaluate_strategy)
        assert sig.parameters["precompute_features"].default is False

    def test_evaluate_strategy_precompute_equivalent(self):
        spec = build_trend_pullback_spec()
        candles = generate_ranging_candles(
            500, symbol="BTCUSDT", timeframe="15")
        legacy = evaluate_strategy(
            spec, candles, min_candles=60, symbol="BTCUSDT",
            precompute_features=False).single_report
        pre = evaluate_strategy(
            spec, candles, min_candles=60, symbol="BTCUSDT",
            precompute_features=True).single_report
        assert _fp(legacy) == _fp(pre)

    def test_anti_lookahead_future_change_does_not_alter_past(self):
        # Mudar um candle FUTURO nao pode alterar features de candle
        # PASSADO (precompute O(n) fatia [:i+1], causal).
        fe = FeatureEngine()
        candles = generate_trending_candles(
            n=250, base_price=65000.0, trend_pct_per_candle=0.0005,
            volatility_pct=0.01, symbol="BTCUSDT", timeframe="15")
        before = fe.compute_indexed(candles).at(120)
        mutated = list(candles)
        c = mutated[200]
        mutated[200] = Candle(
            symbol=c.symbol, timeframe=c.timeframe, timestamp=c.timestamp,
            open=c.open * 5, high=c.high * 5, low=c.low * 5,
            close=c.close * 5, volume=c.volume * 5)
        after = fe.compute_indexed(mutated).at(120)
        for k in ("last_close", "last_rsi", "last_atr", "last_ema_9",
                  "last_vwap"):
            a, b = before[k], after[k]
            assert (math.isnan(a) and math.isnan(b)) or a == b, k

    def test_walk_forward_precompute_equivalent_no_future_leak(self):
        from crypto_trading_bot.backtesting import run_walk_forward
        candles = generate_ranging_candles(
            800, symbol="BTCUSDT", timeframe="15")

        def factory():
            spec = build_trend_pullback_spec()
            return spec.factory(dict(spec.default_config))

        legacy = run_walk_forward(
            factory, candles, n_folds=4, min_candles=60, symbol="BTCUSDT",
            precompute_features=False)
        pre = run_walk_forward(
            factory, candles, n_folds=4, min_candles=60, symbol="BTCUSDT",
            precompute_features=True)
        assert len(legacy) == len(pre)
        for a, b in zip(legacy, pre):
            assert _fp(a.test_report) == _fp(b.test_report)
            assert _fp(a.train_report) == _fp(b.train_report)


# ---------------------------------------------------------------------------
# 3. Cost realism ROTULADO
# ---------------------------------------------------------------------------

class TestCostScenarios:

    def test_labels_and_illustrative_flags(self):
        zero = build_cost_scenario("zero_cost")
        real = build_cost_scenario("realistic_research")
        stress = build_cost_scenario("stressed_research")
        assert zero.is_research_illustrative is False
        assert real.is_research_illustrative is True
        assert stress.is_research_illustrative is True
        assert real.config.taker_fee_pct > 0
        assert stress.config.taker_fee_pct > real.config.taker_fee_pct

    def test_default_sweep_labels(self):
        labels = [s.label for s in default_cost_sweep()]
        assert labels == list(COST_SCENARIO_LABELS)

    def test_override_is_labeled_illustrative(self):
        sc = build_cost_scenario(
            "operator_override", fees_bps=6.0, slippage_bps=5.0)
        assert sc.is_research_illustrative is True
        assert abs(sc.config.taker_fee_pct - 0.0006) < 1e-9

    def test_cost_reduces_pnl_vs_zero(self):
        # Custo piora (ou nao melhora) o PnL liquido vs zero-cost.
        spec = build_trend_pullback_spec()
        candles = generate_ranging_candles(
            600, symbol="BTCUSDT", timeframe="15")
        zero = evaluate_strategy(
            spec, candles, min_candles=60, symbol="BTCUSDT",
            execution_cost_config=build_cost_scenario("zero_cost").config,
            precompute_features=True).single_report
        costed = evaluate_strategy(
            spec, candles, min_candles=60, symbol="BTCUSDT",
            execution_cost_config=build_cost_scenario(
                "realistic_research").config,
            precompute_features=True).single_report
        if zero.total_trades > 0:
            assert costed.total_pnl_usd <= zero.total_pnl_usd + 1e-9


# ---------------------------------------------------------------------------
# 4. Selecao deterministica (nao-dominada, baseline sempre)
# ---------------------------------------------------------------------------

def _vm(pf, exp, dd, trades=30):
    return VariantMetrics(
        total_trades=trades, win_rate=40.0, profit_factor=pf,
        expectancy_usd=exp, total_pnl_usd=exp * trades,
        max_drawdown_pct=dd, payoff=1.5, risk_blocked_count=0,
        blocked_reasons_summary={})


def _vr(name, pf, exp, dd, override=None):
    return VariantResult(
        name=name, axis="x", value=None, config_override=override or {},
        metrics=_vm(pf, exp, dd))


class TestSelection:

    def test_baseline_always_selected_and_deterministic(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        variants = [
            _vr("a", 1.5, 0.20, 5.0),    # dominante
            _vr("b", 1.1, 0.05, 8.0),
            _vr("c", 0.8, -0.10, 12.0),  # dominada
        ]
        sel1 = select_for_followup(baseline, variants, top_n=2)
        sel2 = select_for_followup(baseline, variants, top_n=2)
        assert sel1 == sel2                 # deterministico
        assert sel1[0] == "baseline"        # baseline sempre
        assert "a" in sel1                  # melhor nao-dominada
        assert len(sel1) <= 3               # baseline + top_n


# ---------------------------------------------------------------------------
# 5. Walk-forward gate na recomendacao + 6. Demo gate
# ---------------------------------------------------------------------------

def _wf(name, *, in_pf, oos_pf, stab, cons, overfit, inconcl):
    return WalkForwardEval(
        variant_name=name, n_folds=5, in_sample_pf=in_pf,
        out_of_sample_pf=oos_pf, stability=stab, fold_consistency=cons,
        overfitting_warning=overfit, inconclusive=inconcl)


class TestRecommendationTree:

    def test_reject_when_baseline_bad_and_no_viable(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        variants = [_vr("a", 0.8, -0.1, 6.0)]
        wf = {"a": _wf("a", in_pf=0.8, oos_pf=0.7, stab=0.5, cons=0.2,
                       overfit=False, inconcl=False)}
        rec, *_ = _recommend("trend_pullback_bidirectional", baseline,
                             variants, wf, real_dataset=True)
        assert rec == "rejeitar"

    def test_keep_when_baseline_ok_and_no_better(self):
        baseline = _vr("baseline", 1.5, 0.20, 5.0)
        variants = [_vr("a", 1.0, 0.0, 6.0)]
        wf = {"a": _wf("a", in_pf=1.0, oos_pf=0.9, stab=0.5, cons=0.4,
                       overfit=False, inconcl=False)}
        rec, *_ = _recommend("trend_pullback_bidirectional", baseline,
                             variants, wf, real_dataset=True)
        assert rec == "manter"

    def test_adjust_requires_stable_walk_forward(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        good = _vr("a", 1.5, 0.20, 5.0, override={"risk_reward_ratio": 2.5})
        variants = [good]
        wf = {"a": _wf("a", in_pf=1.5, oos_pf=1.5, stab=0.85, cons=0.8,
                       overfit=False, inconcl=False)}
        rec, detail, suggested, gate_sat, block = _recommend(
            "trend_pullback_bidirectional", baseline, variants, wf,
            real_dataset=True)
        assert rec == "ajustar"
        assert suggested == {"risk_reward_ratio": 2.5}
        assert gate_sat is True            # criterios atendidos...
        # ...mas o gate e CONSULTIVO (demo nunca autorizada no modulo).

    def test_inconclusive_wf_blocks_adjust_to_manual_review(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        good = _vr("a", 1.5, 0.20, 5.0)
        variants = [good]
        wf = {"a": _wf("a", in_pf=1.5, oos_pf=None, stab=None, cons=None,
                       overfit=False, inconcl=True)}
        rec, *_ = _recommend("trend_pullback_bidirectional", baseline,
                             variants, wf, real_dataset=True)
        assert rec == "manual_review"      # NUNCA ajustar com WF inconclusivo

    def test_overfitting_blocks_adjust(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        good = _vr("a", 1.5, 0.20, 5.0)
        variants = [good]
        wf = {"a": _wf("a", in_pf=2.0, oos_pf=0.8, stab=0.4, cons=0.4,
                       overfit=True, inconcl=False)}
        rec, *_ = _recommend("trend_pullback_bidirectional", baseline,
                             variants, wf, real_dataset=True)
        assert rec in ("manual_review", "rejeitar")

    def test_demo_gate_requires_real_dataset(self):
        baseline = _vr("baseline", 0.9, -0.05, 5.0)
        good = _vr("a", 1.5, 0.20, 5.0)
        variants = [good]
        wf = {"a": _wf("a", in_pf=1.5, oos_pf=1.5, stab=0.85, cons=0.8,
                       overfit=False, inconcl=False)}
        # dataset sintetico => gate nunca satisfeito.
        rec, detail, suggested, gate_sat, block = _recommend(
            "trend_pullback_bidirectional", baseline, variants, wf,
            real_dataset=False)
        assert gate_sat is False


# ---------------------------------------------------------------------------
# Integracao: run_calibration em dados sinteticos -> demo SEMPRE bloqueada
# ---------------------------------------------------------------------------

class TestRunCalibration:

    def test_end_to_end_demo_always_blocked(self):
        candles = generate_ranging_candles(
            900, symbol="BTCUSDT", timeframe="15")
        rep = run_calibration(
            candles, candidate="trend_pullback_bidirectional",
            secondary="volatility_breakout", capital=5000.0,
            min_candles=60, data_source="synthetic",
            walk_forward_folds=3, top_n_followup=2)
        d = rep.to_dict()
        assert d["demo_blocked"] is True
        assert d["synthetic_warning"] is True
        for s in d["strategies"]:
            assert s["demo_authorized"] is False
            assert s["recommendation"] in (
                "manter", "ajustar", "rejeitar", "manual_review",
                "bloquear_demo")
            # baseline + cost sweep + walk-forward presentes
            assert s["cost_sweep"] and s["walk_forward"]
            # custos != zero rotulados ilustrativos
            for r in s["cost_sweep"]:
                if r["scenario"] != "zero_cost":
                    assert r["is_research_illustrative"] is True

    def test_candidate_is_first_strategy(self):
        candles = generate_ranging_candles(
            700, symbol="BTCUSDT", timeframe="15")
        rep = run_calibration(
            candles, candidate="trend_pullback_bidirectional",
            secondary=None, capital=5000.0, min_candles=60,
            data_source="synthetic", walk_forward_folds=3,
            top_n_followup=2)
        d = rep.to_dict()
        assert d["strategies"][0]["strategy"] == \
            "trend_pullback_bidirectional"
        assert d["strategies"][0]["is_candidate"] is True
