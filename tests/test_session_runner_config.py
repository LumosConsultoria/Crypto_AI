"""
Testes de SessionRunnerConfig (FASE 17)
=========================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - Frozen.
    - Exige profile como OperationalProfile, spec como StrategySpec.
    - capital > 0, max_cycles > 0, cycle_interval_seconds >= 0.
    - clock/sleep injetáveis.
    - safety_state_machine opcional.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.operational_safety import SafetyStateMachine
from crypto_trading_bot.research.strategy_research import StrategySpec
from crypto_trading_bot.session_runner import SessionRunnerConfig
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Stub strategy + spec
# ---------------------------------------------------------------------------

class _HoldStrategy:
    def __init__(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.WARMING_UP
        self._signal_count = 0

    @property
    def name(self) -> str:
        return "hold_only_stub"

    @property
    def state(self):
        return self._state

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    def set_running(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features):
        return StrategySignal.hold(
            symbol="BTCUSDT", strategy_name=self.name, reason="stub",
        )

    def generate_signal(self, market_data):
        return None

    def reset(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.WARMING_UP

    def on_signal_approved(self, signal): pass
    def on_signal_rejected(self, signal, reason: str): pass
    def on_trade_closed(self, symbol: str, pnl: float): pass


def _spec() -> StrategySpec:
    def factory(cfg):
        s = _HoldStrategy()
        s.set_running()
        return s
    return StrategySpec(name="hold_stub_v1", factory=factory)


def _profile():
    return build_personal_profile(account_size_usd=5000.0)


# ---------------------------------------------------------------------------
# Frozen + validações
# ---------------------------------------------------------------------------

class TestImmutability:

    def test_is_frozen(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
        )
        with pytest.raises(Exception):
            cfg.capital = 100.0  # type: ignore[misc]


class TestValidations:

    def test_rejects_non_profile(self):
        with pytest.raises(TypeError, match="profile"):
            SessionRunnerConfig(
                profile="not_a_profile",  # type: ignore[arg-type]
                spec=_spec(), capital=5000.0,
            )

    def test_rejects_non_spec(self):
        with pytest.raises(TypeError, match="spec"):
            SessionRunnerConfig(
                profile=_profile(),
                spec="not_a_spec",  # type: ignore[arg-type]
                capital=5000.0,
            )

    def test_rejects_zero_capital(self):
        with pytest.raises(ValueError, match="capital"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=0,
            )

    def test_rejects_negative_capital(self):
        with pytest.raises(ValueError, match="capital"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=-100,
            )

    def test_rejects_empty_symbol(self):
        with pytest.raises(ValueError, match="symbol"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                symbol="",
            )

    def test_rejects_zero_max_cycles(self):
        with pytest.raises(ValueError, match="max_cycles"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                max_cycles=0,
            )

    def test_rejects_negative_cycle_interval(self):
        with pytest.raises(ValueError, match="cycle_interval"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                cycle_interval_seconds=-1.0,
            )

    def test_accepts_cycle_interval_zero(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
            cycle_interval_seconds=0.0,
        )
        assert cfg.cycle_interval_seconds == 0.0


class TestInjectables:

    def test_default_clock_returns_utc(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
        )
        now = cfg.clock()
        assert isinstance(now, datetime)
        assert now.tzinfo == timezone.utc

    def test_custom_clock_used(self):
        fake = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
            clock=lambda: fake,
        )
        assert cfg.clock() == fake

    def test_default_sleep_is_time_sleep(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
        )
        # Sanity: default é time.sleep
        assert cfg.sleep is time.sleep

    def test_custom_sleep_used(self):
        calls = []
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
            sleep=lambda s: calls.append(s),
        )
        cfg.sleep(0.123)
        assert calls == [0.123]

    def test_rejects_non_callable_clock(self):
        with pytest.raises(TypeError, match="clock"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                clock="not_callable",  # type: ignore[arg-type]
            )

    def test_rejects_non_callable_sleep(self):
        with pytest.raises(TypeError, match="sleep"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                sleep=42,  # type: ignore[arg-type]
            )

    def test_safety_state_machine_optional(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
        )
        assert cfg.safety_state_machine is None

    def test_safety_state_machine_accepts_instance(self):
        sm = SafetyStateMachine()
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
            safety_state_machine=sm,
        )
        assert cfg.safety_state_machine is sm

    def test_safety_state_machine_rejects_wrong_type(self):
        with pytest.raises(TypeError, match="SafetyStateMachine"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                safety_state_machine="not_a_machine",  # type: ignore[arg-type]
            )

    def test_virtual_cycle_seconds_default(self):
        cfg = SessionRunnerConfig(
            profile=_profile(), spec=_spec(), capital=5000.0,
        )
        assert cfg.virtual_cycle_seconds == 60.0

    def test_virtual_cycle_seconds_negative_rejected(self):
        with pytest.raises(ValueError, match="virtual_cycle_seconds"):
            SessionRunnerConfig(
                profile=_profile(), spec=_spec(), capital=5000.0,
                virtual_cycle_seconds=-1.0,
            )
