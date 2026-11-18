"""
Tests - Demo30MinRealRunner + telemetry recorder (FASE 28)
==============================================================
100% offline. Runner com telemetry_recorder=None preserva FASE 27;
com recorder injetado emite eventos esperados.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.demo_endurance import (
    Demo30MinRealRunner, Demo30MinVerdict,
    LiveDemoBlueprintProvider, SessionTelemetryRecorder,
    build_default_planned_blueprint, build_demo_30_min_plan,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _fake_preflight():
    pf = MagicMock()
    pf.ok = True
    pf.manual_confirmations_needed = ()
    pf.abort_reason = None
    pf.abort_details = ""
    pf.market_info = MagicMock(symbol="BTCUSDT", tick_size=0.5)
    pf.account_state = MagicMock(
        wallet_balance_usdt=5000.0, available_balance_usdt=5000.0,
        open_positions_count=0, open_orders_count=0,
        leverage_confirmable=True, leverage_value=1.0,
    )
    pf.proposal = MagicMock(
        symbol="BTCUSDT", side="buy", reference_price=65000.0,
        qty=0.003, position_size_usd=195.0,
        stop_loss=64025.0, take_profit=66950.0,
        leverage=1.0, risk_usd=2.925, capital=5000.0,
    )
    return pf


def _make_runner(*, signal_action="hold", risk_approved=True,
                 gate_outcome=None, telemetry=None, apply_demo_real=False):
    provider = LiveDemoBlueprintProvider(
        preflight_factory=_fake_preflight, clock=lambda: NOW,
    )
    bp = build_default_planned_blueprint(now=NOW)
    plan = build_demo_30_min_plan(
        symbol="BTCUSDT", strategy_name="trend_pullback",
        max_orders=1, max_session_minutes=30,
        risk_thresholds_snapshot={},
        planned_blueprint=bp, operator_token="OPTOK1234567",
        now=NOW,
    )
    risk_engine = MagicMock()
    risk_engine.validate_signal.return_value = MagicMock(
        approved=risk_approved, reason="ok",
    )
    fake_signal_actionable = MagicMock(
        is_actionable=True,
        action=MagicMock(value="buy"),
        to_trading_signal=lambda: MagicMock(
            symbol="BTCUSDT", side=MagicMock(value="buy"),
            entry_price=65000.0, stop_loss_price=64025.0,
            take_profit_price=66950.0, position_size_usd=195.0,
        ),
    )
    fake_signal_hold = MagicMock(
        is_actionable=False, action=MagicMock(value="hold"),
    )

    def fake_strategy_factory():
        s = MagicMock()
        def eval_fn(features):
            if signal_action == "hold":
                return fake_signal_hold
            return fake_signal_actionable
        s.evaluate = eval_fn
        s.set_running = MagicMock()
        return s

    def fake_feature_factory():
        fe = MagicMock()
        fe.compute = lambda candles: {
            "closes": [], "has_sufficient_data": True,
        }
        return fe

    def fake_market(**kw):
        return [MagicMock(symbol="BTCUSDT", close=65000.0)]

    def default_gate(*args, **kwargs):
        if gate_outcome is not None:
            return gate_outcome
        return MagicMock(
            executor_called=True, executor_success=True,
            is_filled_canonical=True, requires_manual_review=False,
            safety_halt_recommended=False, final_safety_state="normal",
            outcome_reason="canonical fill",
            to_dict=lambda: {"is_filled_canonical": True},
        )

    def fake_session_plan_factory(**kw):
        return MagicMock(plan_id=kw.get("plan_id", "TEST"))

    runner = Demo30MinRealRunner(
        plan=plan, provider=provider, risk_engine=risk_engine,
        safety_machine=MagicMock(requires_operator_ack=False),
        mode_guard=MagicMock(), provider_registry=MagicMock(),
        effective_risk_config=MagicMock(), profile=MagicMock(),
        operator_token="OPTOK1234567",
        market_data_callable=fake_market,
        feature_engine_factory=fake_feature_factory,
        strategy_factory=fake_strategy_factory,
        demo_executor_factory=lambda: MagicMock(),
        gate_callable=default_gate,
        post_session_check_callable=lambda ex, stage: {
            "operation": "post_session_check", "stage": stage,
            "success": True, "requires_manual_review": False,
            "sl_attached": True, "tp_attached": True,
        },
        session_plan_factory=fake_session_plan_factory,
        clock=lambda: NOW, sleep=lambda s: None,
        cycle_interval_seconds=60.0,
        apply_demo_real=apply_demo_real,
        telemetry_recorder=telemetry,
    )
    return runner, plan, provider


class TestTelemetryRecorderNoneIsBackwardCompat:

    def test_runner_without_recorder_works(self):
        runner, _, _ = _make_runner(signal_action="hold")
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES

    def test_runner_with_signal_one_trade_without_recorder(self):
        runner, _, _ = _make_runner(signal_action="buy")
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.PASSED_ONE_TRADE


class TestTelemetryEventsEmitted:

    def test_no_signal_emits_start_preflight_cycle_end(self):
        recorder = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="OPTOK1234567",
        )
        runner, _, _ = _make_runner(
            signal_action="hold", telemetry=recorder,
        )
        runner.run_real()
        types = [e.event_type for e in recorder.events]
        assert "session_start" in types
        assert "preflight_done" in types
        assert "cycle_start" in types
        # Strategy retorna hold -> signal_evaluated emitido
        assert "signal_evaluated" in types
        assert "session_end" in types

    def test_signal_approved_emits_full_sequence(self):
        recorder = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="OPTOK1234567",
        )
        runner, _, _ = _make_runner(
            signal_action="buy", telemetry=recorder,
        )
        runner.run_real()
        types = [e.event_type for e in recorder.events]
        assert "session_start" in types
        assert "preflight_done" in types
        assert "cycle_start" in types
        assert "signal_evaluated" in types
        assert "risk_validated" in types
        assert "ensure_fresh_called" in types
        assert "gate_invoked" in types
        assert "post_check_done" in types
        assert "session_end" in types

    def test_gate_invoked_carries_dry_run_field(self):
        """Critical: telemetria precisa registrar dry_run para auditoria
        de quando uma ordem real SERIA enviada."""
        recorder = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="OPTOK1234567",
        )
        # apply_demo_real=False -> gate recebe dry_run=True
        runner, _, _ = _make_runner(
            signal_action="buy", telemetry=recorder,
            apply_demo_real=False,
        )
        runner.run_real()
        gate_events = [
            e for e in recorder.events if e.event_type == "gate_invoked"
        ]
        assert len(gate_events) == 1
        assert gate_events[0].snapshot.get("dry_run") is True


class TestTelemetryFailureDoesNotPropagate:

    def test_broken_recorder_does_not_break_runner(self):
        class BrokenRecorder:
            def record(self, *a, **kw):
                raise RuntimeError("recorder boom")

        runner, _, _ = _make_runner(
            signal_action="hold", telemetry=BrokenRecorder(),
        )
        # Runner deve completar sem propagar excecao do recorder.
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES


class TestTelemetrySanitization:

    def test_no_secrets_in_recorded_jsonl(self):
        recorder = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="OPSECRETTOKEN12345",
        )
        runner, _, _ = _make_runner(
            signal_action="buy", telemetry=recorder,
        )
        runner.run_real()
        text = recorder.to_jsonl()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text.lower()
        # Operator token completo NUNCA aparece
        assert "OPSECRETTOKEN12345" not in text
