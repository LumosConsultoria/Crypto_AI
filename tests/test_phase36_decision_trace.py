"""
Tests - FASE 36 Bloco A: Decision Trace
========================================
100% offline. O trace NUNCA decide; apenas registra e explica.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.decision_trace import (
    DecisionTraceEntry,
    FinalDecision,
    build_trace_entry,
    render_trace_entries,
    render_trace_entry,
)
from crypto_trading_bot.operational_profile import (
    derive_endurance_limits,
    resolve_profile,
)
from tests.test_phase30_demo_endurance import (
    FakeClock,
    StubFeatureEngine,
    StubRiskApprove,
    StubStrategyBuy,
    StubStrategyHold,
    _fresh_candles,
)

_SNAP_BUY = {
    "strategy_id": "trend_pullback_bidirectional_v1",
    "strategy_name": "trend_pullback_bidirectional",
    "symbol": "BTCUSDT",
    "signal_side": "buy",
    "ema_fast_period": 20, "ema_slow_period": 50,
    "ema_fast_value": 101.0, "ema_slow_value": 99.0,
    "rsi_period": 14, "rsi_value": 58.0,
    "atr_period": 14, "atr_value": 2.1,
    "last_close": 100.0,
    "long_conditions": {
        "uptrend": True, "pullback_zone": True,
        "rsi_ok": True, "no_position": True,
    },
}

_SNAP_HOLD = {
    "strategy_name": "trend_pullback_bidirectional",
    "symbol": "BTCUSDT",
    "signal_side": "hold",
    "hold_reason": "no_uptrend",
    "failed_conditions_long": ["no_uptrend"],
    "failed_conditions_short": ["no_downtrend"],
    "ema_fast_value": 99.0, "ema_slow_value": 101.0,
    "rsi_value": 45.0, "last_close": 100.0,
}


def _signal():
    from crypto_trading_bot.strategies.signal_model import (
        StrategySignal,
    )
    return StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="s",
        entry_price=100.0, stop_loss_price=99.0,
        take_profit_price=102.0, position_size_usd=200.0,
    ).to_trading_signal()


class TestTraceEntryFields:

    def test_enter_entry_complete_fields(self):
        entry = build_trace_entry(
            cycle_idx=12, session_id="sess-1",
            final_decision=FinalDecision.ENTER,
            final_reason="entrada liberada",
            profile=resolve_profile("personal", capital=5000.0),
            provider_id="bybit_demo_linear",
            timeframe="15m",
            signal_snapshot=_SNAP_BUY,
            trading_signal=_signal(),
            risk_summary={"approved": True, "reason": ""},
            exposure_before=0.0, exposure_after=200.0,
            position_before={"qty": 0.0},
            open_orders_before=0, conditional_orders_before=0,
            gates_approved=("phase29_short_gate",),
        )
        d = entry.to_dict()
        assert d["final_decision"] == "enter"
        assert d["strategy_name"] == "trend_pullback_bidirectional"
        assert d["indicators"]["rsi_value"] == 58.0
        assert d["risk_decision"] == "approved"
        assert d["planned_sl"] == 99.0
        assert d["planned_tp"] == 102.0
        assert d["risk_reward"] == 2.0
        assert d["qty"] == 2.0          # 200 USD / 100
        assert d["estimated_risk_usd"] == 2.0   # 1.0 * 2.0
        assert d["exposure_before"] == 0.0
        assert d["exposure_after"] == 200.0
        assert d["gates_approved"] == ["phase29_short_gate"]
        assert d["trace_id"].startswith("trace-")

    def test_hold_entry_has_rejection_reason(self):
        entry = build_trace_entry(
            cycle_idx=3, final_decision=FinalDecision.HOLD,
            final_reason="no_uptrend",
            signal_snapshot=_SNAP_HOLD,
        )
        assert "no_uptrend" in entry.rejection_reason_technical
        assert entry.signal_side == "hold"
        assert entry.risk_decision is None  # risco nem foi consultado

    def test_ai_and_mi_not_used_recorded(self):
        entry = build_trace_entry(
            cycle_idx=0, final_decision=FinalDecision.HOLD,
            final_reason="x", signal_snapshot=_SNAP_HOLD,
            ai_not_used_reason="ai_disabled_by_profile",
            mi_not_used_reason="prediction_context_disabled",
        )
        d = entry.to_dict()
        assert d["ai_used"] is False
        assert d["ai_not_used_reason"] == "ai_disabled_by_profile"
        assert d["market_intelligence_used"] is False
        assert d["mi_not_used_reason"] == \
            "prediction_context_disabled"

    def test_mi_used_with_stale_flagged(self):
        entry = build_trace_entry(
            cycle_idx=0, final_decision=FinalDecision.SKIP,
            final_reason="x", signal_snapshot=_SNAP_BUY,
            mi_snapshot={
                "sources_used": ["polymarket", "funding"],
                "sources_stale": ["polymarket"],
                "sources_unavailable": ["news"],
                "risk_flags": ["macro_event_volatility"],
                "inconclusive": True,
            },
        )
        d = entry.to_dict()
        assert d["market_intelligence_used"] is True
        assert d["funding_used"] is True
        assert d["news_used"] is False
        assert d["mi_sources_stale"] == ["polymarket"]
        assert d["context_inconclusive"] is True

    def test_all_final_decisions_supported(self):
        for fd in FinalDecision:
            entry = build_trace_entry(
                cycle_idx=0, final_decision=fd, final_reason="t",
                signal_snapshot=_SNAP_HOLD,
            )
            assert entry.final_decision is fd


class TestHumanRenderer:

    def test_enter_narrative_matches_spec_example_shape(self):
        entry = build_trace_entry(
            cycle_idx=12, final_decision=FinalDecision.ENTER,
            final_reason="entrada liberada",
            signal_snapshot=_SNAP_BUY, trading_signal=_signal(),
            risk_summary={"approved": True, "reason": ""},
            timeframe="15m", gates_approved=("provider_gate",),
        )
        text = render_trace_entry(entry)
        assert text.startswith("Ciclo 12:")
        assert "gerou BUY em BTCUSDT 15m" in text
        assert "RSI=58.0" in text
        assert "IA nao usada" in text
        assert "RiskEngine aprovou" in text
        assert "SL=99.0" in text and "RR=2.0" in text
        assert "Decisao final: ENTER" in text

    def test_block_narrative_shows_gate(self):
        entry = build_trace_entry(
            cycle_idx=5, final_decision=FinalDecision.BLOCK,
            final_reason="short gate bloqueou",
            signal_snapshot={**_SNAP_BUY, "signal_side": "sell"},
            gates_blocked=("phase29_short_gate",),
        )
        text = render_trace_entry(entry)
        assert "BLOQUEADOS" in text
        assert "Decisao final: BLOCK" in text

    def test_close_narrative_shows_pnl(self):
        entry = build_trace_entry(
            cycle_idx=9, final_decision=FinalDecision.CLOSE,
            final_reason="tp atingido", signal_snapshot=_SNAP_BUY,
            realized_pnl=2.5, trade_idx=0,
        )
        text = render_trace_entry(entry)
        assert "P&L realizado: 2.5 USD" in text

    def test_multi_entries(self):
        entries = [
            build_trace_entry(
                cycle_idx=i, final_decision=FinalDecision.HOLD,
                final_reason="x", signal_snapshot=_SNAP_HOLD,
            )
            for i in range(3)
        ]
        text = render_trace_entries(entries)
        assert text.count("Ciclo") == 3


class TestRunnerIntegration:

    def _run(self, strategy, telemetry=None, **kw):
        from crypto_trading_bot.demo_endurance import (
            DemoEnduranceRunner, DurationSpec,
        )
        clock = FakeClock()
        profile = resolve_profile("personal", capital=5000.0)
        return DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=5, cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTEST",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=strategy,
            risk_engine=StubRiskApprove(),
            real_time=True, clock=clock, sleep=clock.sleep,
            telemetry_recorder=telemetry,
            **kw,
        ).run()

    def test_enter_trace_in_session_summary(self):
        outcome = self._run(StubStrategyBuy())
        summ = dict(outcome.session_summary)
        assert summ["decision_traces_count"] >= 1
        enters = [
            t for t in summ["decision_traces"]
            if t["final_decision"] == "enter"
        ]
        assert enters
        assert enters[0]["risk_decision"] == "approved"
        assert "dry-run" in enters[0]["final_reason"]

    def test_hold_traces_recorded(self):
        outcome = self._run(StubStrategyHold())
        summ = dict(outcome.session_summary)
        holds = [
            t for t in summ["decision_traces"]
            if t["final_decision"] == "hold"
        ]
        assert len(holds) == outcome.signals_evaluated

    def test_risk_rejection_trace_skip(self):
        class RiskReject:
            def validate_signal(self, signal):
                class _R:
                    approved = False
                    reason = "fixture rejection"
                return _R()

        from crypto_trading_bot.demo_endurance import (
            DemoEnduranceRunner, DurationSpec,
        )
        clock = FakeClock()
        profile = resolve_profile("personal", capital=5000.0)
        outcome = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=3, cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTEST",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyBuy(),
            risk_engine=RiskReject(),
            real_time=True, clock=clock, sleep=clock.sleep,
        ).run()
        summ = dict(outcome.session_summary)
        skips = [
            t for t in summ["decision_traces"]
            if t["final_decision"] == "skip"
        ]
        assert skips
        assert skips[0]["risk_decision"] == "rejected"
        assert "fixture rejection" in skips[0]["final_reason"]

    def test_telemetry_event_emitted(self):
        from crypto_trading_bot.demo_endurance import (
            SessionTelemetryRecorder,
        )
        rec = SessionTelemetryRecorder(operator_token="OPTEST")
        self._run(StubStrategyBuy(), telemetry=rec)
        types = [e.event_type for e in rec.events]
        assert "decision_trace_recorded" in types
        # E nada virou fallback api_failure.
        assert "api_failure" not in types

    def test_short_block_trace_in_long_only_profile(self):
        class StubStrategySell:
            def evaluate(self, features):
                from crypto_trading_bot.strategies.signal_model \
                    import StrategySignal
                return StrategySignal.sell(
                    symbol="BTCUSDT", strategy_name="stub",
                    entry_price=100.0, stop_loss_price=101.0,
                    take_profit_price=98.0, position_size_usd=200.0,
                )

        from crypto_trading_bot.demo_endurance import (
            DemoEnduranceRunner, DurationSpec,
        )
        clock = FakeClock()
        profile = resolve_profile(
            "long_only", capital=5000.0,
            allowed_symbols=("BTCUSDT",),
        )
        outcome = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=3, cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTEST",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategySell(),
            risk_engine=StubRiskApprove(),
            real_time=True, clock=clock, sleep=clock.sleep,
        ).run()
        summ = dict(outcome.session_summary)
        blocks = [
            t for t in summ["decision_traces"]
            if t["final_decision"] == "block"
        ]
        assert blocks
        assert "profile_allowed_sides" in blocks[0]["gates_blocked"]

    def test_trace_never_breaks_pipeline(self):
        # build_trace_entry com snapshot vazio nao derruba o runner.
        outcome = self._run(StubStrategyHold())
        assert outcome.cycles_completed >= 1
