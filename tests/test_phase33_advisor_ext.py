"""
Tests - FASE 33: extensoes do Strategy Parameter Advisor
=========================================================
100% offline. ZERO rede. ZERO ordem. Backtests sinteticos.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.research.strategy_parameter_advisor import (
    ParameterEvalResult,
    compare_strategies,
    detect_overfitting,
    run_parameter_advisor,
    stability_score,
)


def _candles(n=200):
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    return generate_trending_candles(
        n=n, base_price=100.0, trend_pct_per_candle=0.001,
        volatility_pct=0.006, symbol="BTCUSDT", timeframe="15",
    )


class TestOverfittingDetection:

    def test_overfit_when_out_of_sample_degrades(self):
        assert detect_overfitting(2.0, 0.5) is True
        assert detect_overfitting(1.5, 0.9) is True

    def test_overfit_when_no_out_of_sample_evidence(self):
        assert detect_overfitting(2.0, None) is True

    def test_not_overfit_when_consistent(self):
        assert detect_overfitting(1.5, 1.4) is False
        assert detect_overfitting(1.0, 0.5) is False  # in fraco
        assert detect_overfitting(None, None) is False

    def test_ratio_rule(self):
        # in_pf > 2x out_pf -> alerta mesmo com out >= 1.0.
        assert detect_overfitting(3.0, 1.2) is True

    def test_stability_score(self):
        assert stability_score(2.0, 1.0) == 0.5
        assert stability_score(1.0, 1.5) == 1.0  # clampado
        assert stability_score(None, 1.0) is None
        assert stability_score(2.0, None) is None


class TestExtraMetricsFields:

    def test_param_result_has_phase33_fields(self):
        r = ParameterEvalResult(
            side="long", config={}, total_trades=10, win_rate=60.0,
            profit_factor=1.5, expectancy_usd=10.0,
            total_pnl_usd=100.0, max_drawdown_pct=5.0,
            avg_win_usd=20.0, avg_loss_usd=-10.0,
            robustness_score=1.0,
            avg_rr=2.0, consecutive_losses=2, trades_per_day=1.5,
            zero_trade_windows=1, time_in_market_pct=12.5,
            stability=0.8, in_sample_profit_factor=1.6,
            out_of_sample_profit_factor=1.3,
            overfitting_warning=False,
        )
        d = r.to_dict()
        for key in (
            "avg_rr", "consecutive_losses", "trades_per_day",
            "zero_trade_windows", "time_in_market_pct", "stability",
            "in_sample_profit_factor", "out_of_sample_profit_factor",
            "overfitting_warning",
        ):
            assert key in d
        assert d["avg_rr"] == 2.0

    def test_defaults_backward_compatible(self):
        # Construtor FASE 29.x (sem campos novos) continua valido.
        r = ParameterEvalResult(
            side="short", config={}, total_trades=0, win_rate=0.0,
            profit_factor=None, expectancy_usd=0.0,
            total_pnl_usd=0.0, max_drawdown_pct=0.0,
            avg_win_usd=0.0, avg_loss_usd=0.0, robustness_score=0.0,
        )
        assert r.overfitting_warning is False
        assert r.stability is None


class TestAdvisorReportShape:

    def test_report_json_has_spec_shape(self):
        report = run_parameter_advisor(
            candles=_candles(150), symbol="BTCUSDT", timeframe="15",
            initial_capital=5000.0, min_candles=60,
            profile="personal",
            evaluate_out_of_sample=False,  # rapido p/ teste de shape
        )
        d = report.to_dict()
        # Forma exigida pela spec FASE 33.
        for key in (
            "symbol", "timeframe", "evaluated_at", "profile",
            "current_strategy", "candidate_strategy",
            "recommendation", "long", "short", "combined",
            "warnings", "ranking",
        ):
            assert key in d, f"campo ausente: {key}"
        assert d["profile"] == "personal"
        for side in ("long", "short"):
            block = d[side]
            assert "performance" in block
            assert "recommended_config" in block
            assert "enabled_recommendation" in block
        assert d["combined"]["recommendation"] in (
            "long_only", "short_only", "long_short",
            "keep_current", "insufficient_data",
        )

    def test_advisor_does_not_mutate_default_config(self):
        from crypto_trading_bot.strategies \
            .trend_pullback_bidirectional_strategy import (
                build_trend_pullback_bidirectional_spec,
            )
        before = dict(
            build_trend_pullback_bidirectional_spec().default_config,
        )
        run_parameter_advisor(
            candles=_candles(120), evaluate_out_of_sample=False,
        )
        after = dict(
            build_trend_pullback_bidirectional_spec().default_config,
        )
        assert before == after

    def test_in_out_sample_enrichment_on_best(self):
        report = run_parameter_advisor(
            candles=_candles(200),
            # Grid minimo para custo baixo.
            long_grid=[{
                "ema_fast_period": 9, "ema_slow_period": 21,
                "rsi_long_overbought": 70.0,
                "pullback_atr_tolerance_k": 0.2,
                "enable_long": True, "enable_short": False,
            }],
            short_grid=[{
                "ema_fast_period": 9, "ema_slow_period": 21,
                "rsi_short_oversold": 30.0,
                "pullback_atr_tolerance_k": 0.2,
                "enable_long": False, "enable_short": True,
            }],
            evaluate_out_of_sample=True,
        )
        d = report.to_dict()
        # Melhor config de cada lado carrega os campos in/out-of-sample
        # (valores podem ser None se trecho nao gerou trades).
        for side in ("long", "short"):
            ranking = d[side]["ranking"]
            if ranking:
                best = ranking[0]
                assert "in_sample_profit_factor" in best
                assert "out_of_sample_profit_factor" in best
                assert "overfitting_warning" in best


class TestStrategyComparison:

    def test_compare_strategies_ranks_by_robustness(self):
        rows = compare_strategies(
            candles=_candles(200), initial_capital=5000.0,
            min_candles=60,
        )
        assert len(rows) == 3
        names = {r["strategy"] for r in rows}
        assert names == {
            "trend_pullback", "trend_pullback_bidirectional",
            "volatility_breakout",
        }
        scores = [r["robustness_score"] for r in rows]
        assert scores == sorted(scores, reverse=True)

    def test_unknown_strategy_recorded_as_error_row(self):
        rows = compare_strategies(
            candles=_candles(100),
            strategy_names=("totally_fake",),
        )
        assert rows[0]["strategy"] == "totally_fake"
        assert "error" in rows[0]


class TestCLISourceGuards:

    def test_cli_has_profile_and_compare_flags(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "scripts"
            / "run_strategy_parameter_advisor.py"
        ).read_text(encoding="utf-8")
        assert '"--profile"' in src
        assert '"--compare-strategies"' in src
        assert "load_dotenv" not in src
