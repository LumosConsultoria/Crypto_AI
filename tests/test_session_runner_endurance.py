"""
Testes de endurance do SessionRunner (FASE 17)
================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - 100 ciclos com sleep mockado terminam rapidamente.
    - 1000 ciclos com clock fake + sleep mockado terminam sem teste lento.
    - max_session_minutes interrompe antes de max_cycles (clock virtual).
    - Estado final coerente.
    - Métricas precisas.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.research.strategy_research import StrategySpec
from crypto_trading_bot.session_runner import (
    SessionRunner,
    SessionRunnerConfig,
    SessionStopReason,
)


def _spec_hold():
    from tests.test_session_runner_config import _HoldStrategy
    def factory(cfg):
        s = _HoldStrategy()
        s.set_running()
        return s
    return StrategySpec(name="hold_v1", factory=factory)


def _stepping_clock(*, start: datetime, increment_seconds: float):
    state = {"call": 0}

    def clock():
        t = start + timedelta(seconds=increment_seconds * state["call"])
        state["call"] += 1
        return t

    return clock


# ---------------------------------------------------------------------------
# 100 / 1000 ciclos
# ---------------------------------------------------------------------------

class TestEnduranceFast:

    def test_100_cycles_runs_quickly(self):
        sleep_calls = []
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(account_size_usd=5000.0),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=100,
            cycle_interval_seconds=0.0,
            clock=lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            sleep=lambda s: sleep_calls.append(s),
            virtual_cycle_seconds=0.0,
        )
        runner = SessionRunner(cfg)
        t0 = time.perf_counter()
        result = runner.run()
        elapsed = time.perf_counter() - t0
        assert result.total_cycles_completed == 100
        assert result.stopped_reason == SessionStopReason.MAX_CYCLES
        # Tempo wall-clock < 30s mesmo com BotEngine real
        assert elapsed < 30.0
        # Sleep não chamado porque cycle_interval_seconds=0.0
        assert sleep_calls == []

    def test_1000_cycles_with_fake_clock_completes(self):
        sleep_calls = []
        start = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(account_size_usd=5000.0),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=1000,
            cycle_interval_seconds=0.0,
            clock=_stepping_clock(start=start, increment_seconds=0.0),
            sleep=lambda s: sleep_calls.append(s),
            virtual_cycle_seconds=0.0,
        )
        runner = SessionRunner(cfg)
        t0 = time.perf_counter()
        result = runner.run()
        elapsed = time.perf_counter() - t0
        assert result.total_cycles_completed == 1000
        assert elapsed < 120.0   # safety upper-bound generoso
        assert sleep_calls == []


# ---------------------------------------------------------------------------
# max_session_minutes interrompe antes de max_cycles
# ---------------------------------------------------------------------------

class TestTimeLimitBeforeMaxCycles:

    def test_time_limit_interrupts_before_max_cycles(self):
        # max_cycles=10000, profile limita 5 min, cada ciclo virtual = 90s
        # → para após ~3-4 ciclos
        start = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(
                account_size_usd=5000.0,
                max_session_minutes=5,
            ),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=10000,
            cycle_interval_seconds=0.0,
            clock=_stepping_clock(start=start, increment_seconds=90.0),
            sleep=lambda s: None,
            virtual_cycle_seconds=90.0,
        )
        runner = SessionRunner(cfg)
        result = runner.run()
        assert result.stopped_reason == SessionStopReason.TIME_LIMIT
        assert result.total_cycles_completed < 10000
        assert result.total_cycles_completed >= 3


# ---------------------------------------------------------------------------
# Métricas precisas em endurance
# ---------------------------------------------------------------------------

class TestEnduranceMetrics:

    def test_completed_count_matches_max_cycles(self):
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(account_size_usd=5000.0),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=50,
            cycle_interval_seconds=0.0,
            clock=lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            sleep=lambda s: None,
            virtual_cycle_seconds=0.0,
        )
        runner = SessionRunner(cfg)
        result = runner.run()
        assert result.total_cycles_completed == result.total_cycles_requested
        assert result.total_cycles_requested == 50

    def test_blocks_aggregates_consistent_under_endurance(self):
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(account_size_usd=5000.0),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=100,
            cycle_interval_seconds=0.0,
            clock=lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            sleep=lambda s: None,
            virtual_cycle_seconds=0.0,
        )
        runner = SessionRunner(cfg)
        result = runner.run()
        # Invariante final-result
        assert result.total_blocks == (
            result.blocks_by_safety
            + result.blocks_by_profile
            + result.blocks_by_risk
        )


# ---------------------------------------------------------------------------
# Sleep mockado quando cycle_interval_seconds > 0
# ---------------------------------------------------------------------------

class TestSleepMockedNonZeroInterval:

    def test_sleep_called_with_configured_interval(self):
        calls = []
        cfg = SessionRunnerConfig(
            profile=build_personal_profile(account_size_usd=5000.0),
            spec=_spec_hold(),
            capital=5000.0,
            max_cycles=5,
            cycle_interval_seconds=0.05,
            clock=lambda: datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
            sleep=lambda s: calls.append(s),
            virtual_cycle_seconds=0.0,
        )
        runner = SessionRunner(cfg)
        result = runner.run()
        # Sleep chamado N vezes (uma por ciclo executado)
        assert len(calls) == result.total_cycles_completed
        # Valor passado é exatamente cycle_interval_seconds
        for c in calls:
            assert c == 0.05
