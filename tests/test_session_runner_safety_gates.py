"""
Testes de safety gates do SessionRunner (FASE 17)
====================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - NORMAL permite ciclos.
    - MANUAL_REVIEW_REQUIRED bloqueia abertura (BLOCK).
    - SAFETY_HALT_RECOMMENDED bloqueia abertura.
    - SAFETY_HALT_ACTIVE bloqueia abertura.
    - SAFETY_HALT_ACTIVE + kill_switch_enabled=True → STOP.
    - SAFETY_HALT_ACTIVE + kill_switch_enabled=False → bloqueia sem parar.
    - requires_operator_ack=True gera SessionBlockEvent.
    - safety_state_machine=None → runner cria interna em NORMAL.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.operational_profile import (
    build_personal_profile,
)
from crypto_trading_bot.operational_safety import (
    SafetyState,
    SafetyStateMachine,
)
from crypto_trading_bot.research.strategy_research import StrategySpec
from crypto_trading_bot.session_runner import (
    SessionRunner,
    SessionRunnerConfig,
    SessionStopReason,
)
from crypto_trading_bot.session_runner.result import BLOCK_SAFETY_STATE

from tests.test_session_runner_config import _HoldStrategy


_FIXED_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _spec():
    def factory(cfg):
        s = _HoldStrategy()
        s.set_running()
        return s
    return StrategySpec(name="hold_v1", factory=factory)


def _build_runner(*, max_cycles=5, profile=None, safety=None):
    if profile is None:
        profile = build_personal_profile(account_size_usd=5000.0)
    cfg = SessionRunnerConfig(
        profile=profile,
        spec=_spec(),
        capital=5000.0,
        max_cycles=max_cycles,
        cycle_interval_seconds=0.0,
        clock=lambda: _FIXED_NOW,
        sleep=lambda s: None,
        safety_state_machine=safety,
        virtual_cycle_seconds=60.0,
    )
    return SessionRunner(cfg)


# ---------------------------------------------------------------------------
# Comportamento por safety state
# ---------------------------------------------------------------------------

class TestNormalAllowsCycles:

    def test_normal_runs_all_cycles(self):
        runner = _build_runner(max_cycles=5)
        result = runner.run()
        assert result.total_cycles_completed == 5
        assert result.stopped_reason == SessionStopReason.MAX_CYCLES
        # NORMAL → sem blocks
        assert result.blocks_by_safety == 0


class TestManualReviewBlocksOpen:

    def test_manual_review_blocks_open_but_does_not_stop(self):
        sm = SafetyStateMachine()
        sm.mark_manual_review_required(reason="triangulation")
        runner = _build_runner(max_cycles=3, safety=sm)
        result = runner.run()
        # Ciclos rodam (BLOCK não interrompe)
        assert result.total_cycles_completed == 3
        # Cada ciclo gera 1 block de safety
        assert result.blocks_by_safety == 3
        # Stop por max_cycles, não por safety
        assert result.stopped_reason == SessionStopReason.MAX_CYCLES
        # final_safety_state preserva MANUAL_REVIEW_REQUIRED
        assert result.final_safety_state == "manual_review_required"


class TestSafetyHaltRecommendedBlocksOpen:

    def test_recommended_blocks_open_no_stop(self):
        sm = SafetyStateMachine()
        sm.recommend_safety_halt(reason="halt rec")
        runner = _build_runner(max_cycles=3, safety=sm)
        result = runner.run()
        assert result.total_cycles_completed == 3
        assert result.blocks_by_safety == 3
        assert result.stopped_reason == SessionStopReason.MAX_CYCLES


class TestSafetyHaltActiveBlocksOpen:

    def test_active_blocks_open_no_stop_when_kill_switch_off(self):
        sm = SafetyStateMachine()
        sm.recommend_safety_halt(reason="r")
        sm.activate_safety_halt(reason="t")
        profile = build_personal_profile(
            account_size_usd=5000.0, kill_switch_enabled=False,
        )
        runner = _build_runner(max_cycles=3, safety=sm, profile=profile)
        result = runner.run()
        # Não dispara KILL_SWITCH porque kill_switch_enabled=False
        assert result.stopped_reason == SessionStopReason.MAX_CYCLES
        assert result.total_cycles_completed == 3
        # SAFETY_HALT_ACTIVE exige ack → cada ciclo gera block
        assert result.blocks_by_safety >= 3


class TestKillSwitchStopsSession:

    def test_kill_switch_with_safety_halt_active_stops(self):
        sm = SafetyStateMachine()
        sm.recommend_safety_halt(reason="r")
        sm.activate_safety_halt(reason="t")
        profile = build_personal_profile(
            account_size_usd=5000.0, kill_switch_enabled=True,
        )
        runner = _build_runner(max_cycles=10, safety=sm, profile=profile)
        result = runner.run()
        # Para imediatamente — antes do primeiro run_once
        assert result.stopped_reason == SessionStopReason.KILL_SWITCH
        assert result.total_cycles_completed == 0
        # 1 block registrado
        assert result.blocks_by_safety == 1

    def test_kill_switch_with_manual_review_required_stops(self):
        sm = SafetyStateMachine()
        sm.mark_manual_review_required(reason="t")
        profile = build_personal_profile(
            account_size_usd=5000.0, kill_switch_enabled=True,
        )
        runner = _build_runner(max_cycles=10, safety=sm, profile=profile)
        result = runner.run()
        assert result.stopped_reason == SessionStopReason.KILL_SWITCH


class TestSafetyBlockEventRegistered:

    def test_event_contains_safety_state_source(self):
        sm = SafetyStateMachine()
        sm.mark_manual_review_required(reason="t")
        runner = _build_runner(max_cycles=1, safety=sm)
        result = runner.run()
        assert len(result.blocks) >= 1
        evt = result.blocks[0]
        assert evt.block_source == BLOCK_SAFETY_STATE
        assert "safety_state" in evt.reason or "manual_review" in evt.reason


class TestDefaultSafetyMachine:

    def test_no_machine_creates_internal_normal(self):
        runner = _build_runner(max_cycles=2, safety=None)
        # Estado interno deve ser NORMAL
        assert runner.safety_state_machine.state is SafetyState.NORMAL
        result = runner.run()
        assert result.total_cycles_completed == 2
        assert result.blocks_by_safety == 0


class TestResumeAfterResolve:

    def test_runner_can_be_reused_after_ack_resolve_reset(self):
        sm = SafetyStateMachine()
        sm.mark_manual_review_required(reason="t")
        runner = _build_runner(max_cycles=2, safety=sm)
        result_1 = runner.run()
        assert result_1.blocks_by_safety >= 1

        # Operador resolve manualmente
        sm.acknowledge(operator_ack_token="op@example.com")
        sm.resolve()
        sm.reset()

        # Nova execução do mesmo runner — estado preservado, safety OK
        result_2 = runner.run()
        assert result_2.blocks_by_safety == 0
        # Estado interno ainda em NORMAL
        assert runner.safety_state_machine.state is SafetyState.NORMAL
