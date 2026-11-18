"""
Tests - FASE 29.x: estrategia bidirecional + advisor + gate SHORT
==================================================================
100% OFFLINE. ZERO rede. ZERO ordem real. ZERO API key.

Cobre (Partes G-M):
  - Estrategia bidirecional BUY/SELL/HOLD + hold_reason + failed_conditions
  - SL/TP coerentes por lado (BUY: SL<entry<TP; SELL: TP<entry<SL)
  - RiskEngine valida BUY e SELL
  - Executor side=sell + reduceOnly close invertido (LONG/SELL, SHORT/BUY)
  - Telemetria explica HOLD (signal snapshot rico)
  - Advisor ranqueia LONG/SHORT separados + recomendacoes + robustez
  - Gate SHORT: FASE 29 real long-only sem DEMO_30_MIN_ALLOW_SHORT...
  - Sem segredos no relatorio do advisor
  - Preservacao: trend_pullback (long-only) intacta no factory
"""

from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.strategies.signal_model import StrategyAction
from crypto_trading_bot.strategies.trend_pullback_bidirectional_strategy import (
    TrendPullbackBidirectionalStrategy,
    build_trend_pullback_bidirectional_spec,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_strategy(**kw) -> TrendPullbackBidirectionalStrategy:
    s = TrendPullbackBidirectionalStrategy(**kw)
    s.set_running()
    return s


def _features(
    *, ema_fast_val, ema_slow_val, last_close, last_rsi, last_atr,
    fast=20, slow=50, sufficient=True, n=120, symbol="BTCUSDT",
):
    """Constroi um features dict compativel com evaluate()."""
    feats = {
        "symbol": symbol,
        "has_sufficient_data": sufficient,
        "n_candles": n,
        "last_close": last_close,
        "last_high": last_close * 1.001,
        "last_low": last_close * 0.999,
        "last_volume": 1000.0,
        "last_rsi": last_rsi,
        "last_atr": last_atr,
        f"ema_{fast}": pd.Series([ema_fast_val]),
        f"ema_{slow}": pd.Series([ema_slow_val]),
    }
    return feats


# ---------------------------------------------------------------------------
# G/I - Sinais bidirecionais
# ---------------------------------------------------------------------------

class TestBidirectionalSignals:

    def test_buy_when_uptrend_pullback_rsi_ok(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.BUY
        assert sig.is_actionable
        assert sig.metadata["signal_side"] == "buy"
        assert sig.metadata["direction"] == "long"

    def test_sell_when_downtrend_pullback_rsi_ok(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.SELL
        assert sig.is_actionable
        assert sig.metadata["signal_side"] == "sell"
        assert sig.metadata["direction"] == "short"

    def test_hold_insufficient_candles(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
            sufficient=False, n=10,
        ))
        assert sig.action == StrategyAction.HOLD
        assert sig.reason == "insufficient_candles"
        assert sig.metadata["hold_reason"] == "insufficient_candles"

    def test_hold_ema_unavailable(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=float("nan"), ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.HOLD
        assert sig.reason == "ema_unavailable"

    def test_hold_rsi_overbought_long(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=85.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.HOLD
        assert "rsi_overbought" in sig.metadata["failed_conditions_long"]

    def test_hold_position_already_open(self):
        s = _make_strategy()
        s._has_open_position = True
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.HOLD
        assert "position_already_open" in \
            sig.metadata["failed_conditions_long"]

    def test_no_uptrend_recorded_in_failed_long(self):
        # downtrend setup, but long-only -> HOLD with no_uptrend.
        s = _make_strategy(enable_short=False)
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.HOLD
        assert "no_uptrend" in sig.metadata["failed_conditions_long"]

    def test_short_disabled_blocks_sell(self):
        s = _make_strategy(enable_short=False)
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.HOLD
        assert "short_disabled" in sig.metadata["failed_conditions_short"]

    def test_long_and_short_mutually_exclusive(self):
        # EMA fast>slow is uptrend; never both. Run many: never both valid.
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        meta = sig.metadata
        # uptrend and downtrend cannot both be True.
        assert not (meta["uptrend"] and meta["downtrend"])


# ---------------------------------------------------------------------------
# L - SL/TP coerentes por lado
# ---------------------------------------------------------------------------

class TestStopAndTargetPerSide:

    def test_buy_sl_below_entry_tp_above(self):
        s = _make_strategy(stop_atr_multiplier=1.5, risk_reward_ratio=2.0)
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.BUY
        assert sig.stop_loss_price < sig.entry_price < sig.take_profit_price
        # SL = 95 - 1.5*2 = 92 ; risk=3 ; TP = 95 + 2*3 = 101
        assert sig.stop_loss_price == pytest.approx(92.0)
        assert sig.take_profit_price == pytest.approx(101.0)

    def test_sell_tp_below_entry_sl_above(self):
        s = _make_strategy(stop_atr_multiplier=1.5, risk_reward_ratio=2.0)
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.SELL
        assert sig.take_profit_price < sig.entry_price < sig.stop_loss_price
        # SL = 95 + 1.5*2 = 98 ; risk=3 ; TP = 95 - 2*3 = 89
        assert sig.stop_loss_price == pytest.approx(98.0)
        assert sig.take_profit_price == pytest.approx(89.0)

    def test_buy_fallback_stop_when_atr_nan(self):
        s = _make_strategy(stop_fallback_pct=0.015)
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=100.0, last_rsi=50.0, last_atr=float("nan"),
        ))
        assert sig.action == StrategyAction.BUY
        # SL = 100 * (1 - 0.015) = 98.5
        assert sig.stop_loss_price == pytest.approx(98.5)
        assert sig.stop_loss_price < sig.entry_price < sig.take_profit_price

    def test_sell_fallback_stop_when_atr_nan(self):
        s = _make_strategy(stop_fallback_pct=0.015)
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=float("nan"),
        ))
        assert sig.action == StrategyAction.SELL
        # SL = 95 * (1 + 0.015) = 96.425
        assert sig.stop_loss_price == pytest.approx(96.425, abs=0.01)
        assert sig.take_profit_price < sig.entry_price < sig.stop_loss_price


# ---------------------------------------------------------------------------
# L - RiskEngine valida BUY e SELL
# ---------------------------------------------------------------------------

class TestRiskEngineValidatesBothSides:

    def _engine(self):
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        return RiskEngine(initial_capital=5000.0)

    def test_risk_approves_buy(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        res = self._engine().validate_signal(sig.to_trading_signal())
        assert res.approved, getattr(res, "reason", "")

    def test_risk_approves_sell(self):
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        res = self._engine().validate_signal(sig.to_trading_signal())
        assert res.approved, getattr(res, "reason", "")


# ---------------------------------------------------------------------------
# J/L - Executor side + reduceOnly close invertido
# ---------------------------------------------------------------------------

class _RecordingExecutor:
    """Mock executor que registra a side recebida em close."""

    def __init__(self):
        self.calls = []

    def submit_reduce_only_close(self, *, symbol, side, qty,
                                 dry_run, confirm_demo_execution):
        self.calls.append({"symbol": symbol, "side": side, "qty": qty})

        class _R:
            success = True
            reason = "ok"
            manual_review_required = False
            safety_halt_recommended = False

            def to_dict(self_inner):
                return {"side": side, "qty": qty}
        return _R()


class TestExecutorBidirectional:

    def test_sell_signal_maps_to_orderside_sell(self):
        from crypto_trading_bot.risk.risk_engine import OrderSide
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=90.0, ema_slow_val=100.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        ts = sig.to_trading_signal()
        assert ts.side == OrderSide.SELL

    def test_close_short_uses_buy_reduce_only(self):
        from crypto_trading_bot.demo_endurance.close_executor_wrapper import (
            CloseExecutorWrapper,
        )
        ex = _RecordingExecutor()
        wrapper = CloseExecutorWrapper(executor=ex)
        r = wrapper.close_position(
            symbol="BTCUSDT", position_side="sell", position_qty=0.01,
            dry_run=True,
        )
        assert r.success
        assert ex.calls[0]["side"] == "buy"  # close SHORT with BUY

    def test_close_long_uses_sell_reduce_only(self):
        from crypto_trading_bot.demo_endurance.close_executor_wrapper import (
            CloseExecutorWrapper,
        )
        ex = _RecordingExecutor()
        wrapper = CloseExecutorWrapper(executor=ex)
        r = wrapper.close_position(
            symbol="BTCUSDT", position_side="buy", position_qty=0.01,
            dry_run=True,
        )
        assert r.success
        assert ex.calls[0]["side"] == "sell"  # close LONG with SELL


# ---------------------------------------------------------------------------
# K - Gate SHORT (long-only por default)
# ---------------------------------------------------------------------------

class TestShortGate:

    def _call(self, **kw):
        from crypto_trading_bot.demo_endurance import (
            validate_phase29_short_gate,
        )
        base = dict(
            signal_side="sell", operator_confirmed_short=True,
            operator_token="OPTOK",
        )
        base.update(kw)
        return validate_phase29_short_gate(**base)

    def test_buy_always_approved(self, monkeypatch):
        from crypto_trading_bot.demo_endurance import ENV_ALLOW_SHORT
        monkeypatch.delenv(ENV_ALLOW_SHORT, raising=False)
        r = self._call(signal_side="buy", operator_confirmed_short=False,
                       operator_token="")
        assert r.approved
        assert r.gate_name == "short"

    def test_sell_blocked_without_env(self, monkeypatch):
        from crypto_trading_bot.demo_endurance import ENV_ALLOW_SHORT
        monkeypatch.delenv(ENV_ALLOW_SHORT, raising=False)
        r = self._call()
        assert not r.approved
        assert any("ALLOW_SHORT" in b for b in r.blockers)

    def test_sell_blocked_without_operator_confirm(self, monkeypatch):
        from crypto_trading_bot.demo_endurance import ENV_ALLOW_SHORT
        monkeypatch.setenv(ENV_ALLOW_SHORT, "true")
        r = self._call(operator_confirmed_short=False)
        assert not r.approved
        assert any("confirm SHORT" in b for b in r.blockers)

    def test_sell_approved_with_env_and_confirm(self, monkeypatch):
        from crypto_trading_bot.demo_endurance import ENV_ALLOW_SHORT
        monkeypatch.setenv(ENV_ALLOW_SHORT, "true")
        r = self._call()
        assert r.approved

    def test_runner_accepts_allow_short_param(self):
        # Defesa em profundidade: runner expoe allow_short (default False).
        import inspect
        from crypto_trading_bot.demo_endurance.real_runner import (
            Demo30MinRealRunner,
        )
        sig = inspect.signature(Demo30MinRealRunner.__init__)
        assert "allow_short" in sig.parameters
        assert sig.parameters["allow_short"].default is False


# ---------------------------------------------------------------------------
# A/B - Telemetria explica HOLD
# ---------------------------------------------------------------------------

class TestTelemetrySnapshotExplainsHold:

    def test_snapshot_carries_hold_reason_and_failed(self):
        from crypto_trading_bot.demo_endurance.real_runner import (
            _signal_snapshot_fields,
        )
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=85.0, last_atr=2.0,
        ))
        snap = _signal_snapshot_fields(sig)
        assert snap["hold_reason"]
        assert "failed_conditions_long" in snap
        assert snap["ema_fast_period"] == 20
        assert snap["signal_side"] == "hold"

    def test_snapshot_carries_buy_decision_fields(self):
        from crypto_trading_bot.demo_endurance.real_runner import (
            _signal_snapshot_fields,
        )
        s = _make_strategy()
        sig = s.evaluate(_features(
            ema_fast_val=100.0, ema_slow_val=90.0,
            last_close=95.0, last_rsi=50.0, last_atr=2.0,
        ))
        snap = _signal_snapshot_fields(sig)
        assert snap["signal_side"] == "buy"
        assert snap["direction"] == "long"
        assert snap["uptrend"] is True


# ---------------------------------------------------------------------------
# C/H - Advisor: ranking, recomendacoes, robustez
# ---------------------------------------------------------------------------

class TestAdvisorGrids:

    def test_long_grid_long_only(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            default_long_grid,
        )
        grid = default_long_grid()
        assert grid
        for cfg in grid:
            assert cfg["enable_long"] is True
            assert cfg["enable_short"] is False
            assert "rsi_long_overbought" in cfg

    def test_short_grid_short_only(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            default_short_grid,
        )
        grid = default_short_grid()
        assert grid
        for cfg in grid:
            assert cfg["enable_short"] is True
            assert cfg["enable_long"] is False
            assert "rsi_short_oversold" in cfg


class TestRobustnessScore:

    def test_insufficient_trades_scores_zero(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _compute_robustness_score,
        )
        score, warns = _compute_robustness_score(
            total_trades=2, win_rate=60.0, profit_factor=3.0,
            expectancy_usd=50.0, max_drawdown_pct=5.0, trades_per_day=1.0,
        )
        assert score == 0.0
        assert "insufficient_trades" in warns

    def test_high_drawdown_penalized(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _compute_robustness_score,
        )
        good, _ = _compute_robustness_score(
            total_trades=20, win_rate=60.0, profit_factor=1.6,
            expectancy_usd=20.0, max_drawdown_pct=5.0, trades_per_day=2.0,
        )
        bad, warns = _compute_robustness_score(
            total_trades=20, win_rate=60.0, profit_factor=1.6,
            expectancy_usd=20.0, max_drawdown_pct=60.0, trades_per_day=2.0,
        )
        assert bad < good
        assert "high_drawdown" in warns

    def test_overtrading_penalized(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _compute_robustness_score,
        )
        _, warns = _compute_robustness_score(
            total_trades=200, win_rate=55.0, profit_factor=1.4,
            expectancy_usd=10.0, max_drawdown_pct=8.0, trades_per_day=50.0,
        )
        assert "possible_overtrading" in warns


class TestSideRecommendation:

    def _result(self, **kw):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            ParameterEvalResult,
        )
        base = dict(
            side="long", config={"ema_fast_period": 20},
            total_trades=20, win_rate=60.0, profit_factor=1.8,
            expectancy_usd=25.0, total_pnl_usd=500.0,
            max_drawdown_pct=8.0, avg_win_usd=40.0, avg_loss_usd=-20.0,
            robustness_score=2.0, warnings=(),
        )
        base.update(kw)
        return ParameterEvalResult(**base)

    def test_enables_side_when_robust(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _build_side_recommendation,
        )
        rec = _build_side_recommendation("long", [self._result()])
        assert rec.enabled_recommendation is True
        assert rec.recommended_config is not None

    def test_insufficient_data_when_few_trades(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _build_side_recommendation,
        )
        rec = _build_side_recommendation(
            "long", [self._result(total_trades=2, robustness_score=0.0)]
        )
        assert rec.enabled_recommendation is False
        assert "insufficient_data" in rec.reason

    def test_blocked_when_low_profit_factor(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _build_side_recommendation,
        )
        rec = _build_side_recommendation(
            "long",
            [self._result(profit_factor=1.0, robustness_score=0.5)],
        )
        assert rec.enabled_recommendation is False

    def test_empty_ranking_returns_no_configs(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            _build_side_recommendation,
        )
        rec = _build_side_recommendation("short", [])
        assert rec.enabled_recommendation is False
        assert rec.reason == "no_configs_evaluated"


class TestAdvisorEndToEnd:

    def _candles(self, n=200):
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        return generate_trending_candles(
            n=n, base_price=100.0, trend_pct_per_candle=0.001,
            volatility_pct=0.006, symbol="BTCUSDT", timeframe="15",
        )

    def test_runs_and_separates_long_short(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            run_parameter_advisor, AdvisorReport,
        )
        report = run_parameter_advisor(
            candles=self._candles(), symbol="BTCUSDT", timeframe="15",
            initial_capital=5000.0, min_candles=60,
        )
        assert isinstance(report, AdvisorReport)
        assert report.long.side == "long"
        assert report.short.side == "short"
        assert report.recommendation in (
            "keep", "adjust", "switch_candidate", "insufficient_data",
        )
        assert report.combined_recommendation in (
            "long_only", "short_only", "long_short",
            "keep_current", "insufficient_data",
        )
        assert report.candidate_strategy == "trend_pullback_bidirectional"

    def test_report_to_dict_and_human_summary(self):
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            run_parameter_advisor,
        )
        report = run_parameter_advisor(
            candles=self._candles(120), symbol="BTCUSDT", timeframe="15",
            initial_capital=5000.0, min_candles=60,
        )
        d = report.to_dict()
        assert d["candidate_strategy"] == "trend_pullback_bidirectional"
        assert "long" in d and "short" in d and "combined" in d
        summary = report.human_summary()
        assert "CONSULTIVA" in summary
        assert "BTCUSDT" in summary


# ---------------------------------------------------------------------------
# E/M - Sem efeitos colaterais, sem segredos, preservacao
# ---------------------------------------------------------------------------

class TestNoSideEffectsNoSecrets:

    def test_advisor_does_not_mutate_default_config(self):
        spec1 = build_trend_pullback_bidirectional_spec()
        cfg_before = dict(spec1.default_config)
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            run_parameter_advisor,
        )
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        candles = generate_trending_candles(
            n=120, base_price=100.0, trend_pct_per_candle=0.001,
            volatility_pct=0.006, symbol="BTCUSDT", timeframe="15",
        )
        run_parameter_advisor(
            candles=candles, symbol="BTCUSDT", timeframe="15",
            initial_capital=5000.0, min_candles=60,
        )
        spec2 = build_trend_pullback_bidirectional_spec()
        assert dict(spec2.default_config) == cfg_before

    def test_report_dict_has_no_secret_tokens(self):
        import json
        from crypto_trading_bot.research.strategy_parameter_advisor import (
            run_parameter_advisor,
        )
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        candles = generate_trending_candles(
            n=120, base_price=100.0, trend_pct_per_candle=0.001,
            volatility_pct=0.006, symbol="BTCUSDT", timeframe="15",
        )
        report = run_parameter_advisor(
            candles=candles, symbol="BTCUSDT", timeframe="15",
            initial_capital=5000.0, min_candles=60,
        )
        text = json.dumps(report.to_dict(), default=str).lower()
        for tok in ("api_key", "api_secret", "x-bapi", "authorization"):
            assert tok not in text


class TestStrategyFactoryPreservation:

    def test_bidirectional_registered(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            SUPPORTED_STRATEGIES, build_strategy_spec,
        )
        assert "trend_pullback_bidirectional" in SUPPORTED_STRATEGIES
        spec = build_strategy_spec("trend_pullback_bidirectional")
        assert spec.name == "trend_pullback_bidirectional_default"

    def test_original_trend_pullback_still_works(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        spec = build_strategy_spec("trend_pullback")
        assert spec is not None

    def test_describe_includes_all_three(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            describe_supported_strategies,
        )
        d = describe_supported_strategies()
        assert "trend_pullback" in d
        assert "volatility_breakout" in d
        assert "trend_pullback_bidirectional" in d
