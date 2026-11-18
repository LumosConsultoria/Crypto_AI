"""
Tests - FASE 30.2/36 Bloco 0: multi-ordem real demo SEQUENCIAL
================================================================
100% offline. Fakes/mocks. ZERO rede. ZERO ordem real.
Valores numericos usados aqui sao FIXTURES DE TESTE explicitamente
marcadas — nao sao limites operacionais reais (V1-V12 pendentes).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    DemoEnduranceOutcome,
    DemoEnduranceRunner,
    DurationSpec,
    EnduranceEndedReason,
    MultiOrderExecutionState,
    RealTradeLifecycle,
    RealTradeRecord,
    can_accept_new_entry,
    expected_phrase_30_2,
    validate_phase30_2_real_multi_gate,
)
from crypto_trading_bot.operational_profile import (
    derive_endurance_limits,
    resolve_profile,
)

# Reusa helpers do bloco FASE 30 (fake clock, stubs, feed offline).
from tests.test_phase30_demo_endurance import (
    FakeClock,
    StubFeatureEngine,
    StubRiskApprove,
    StubStrategyBuy,
    _fresh_candles,
)

_START = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

# FIXTURE DE TESTE (nao e limite operacional real).
_TEST_MAX_REAL_ORDERS = 2

_ALL_GATES = (
    "ENABLE_DEMO_EXECUTION", "BYBIT_USE_DEMO",
    "DEMO_30_MIN_REAL_RUNNER_DEPLOYED",
    "DEMO_ALLOW_MULTI_ORDER_PER_SESSION",
    "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED",
)


def _set_all_gates(monkeypatch):
    for env in _ALL_GATES:
        monkeypatch.setenv(env, "true")


def _gate_kwargs(profile, **overrides):
    base = dict(
        profile=profile,
        max_real_orders=_TEST_MAX_REAL_ORDERS,
        phrase_confirmation=expected_phrase_30_2(_TEST_MAX_REAL_ORDERS),
        flag_execute_demo_real_multi=True,
        flag_confirm_demo_real_multi=True,
        flag_first_real_demo_multi_order_fase30=True,
        prompt_y_confirmed=True,
        operator_token="OPTOK_TEST",
        tty_present=True,
        real_time=True,
        demo_only=True,
        observation_mode=False,
        synthetic_feed=False,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Gate FASE 30.2 (testes 1-6 da spec)
# ---------------------------------------------------------------------------

class TestPhase30_2Gate:

    def _profile(self):
        return resolve_profile(
            "demo_multi_order_validation", capital=5000.0,
        )

    def test_requires_specific_gate_env(self, monkeypatch):
        _set_all_gates(monkeypatch)
        monkeypatch.delenv(
            "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED", raising=False,
        )
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile()),
        )
        assert not r.approved
        assert any(
            "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED" in b
            for b in r.blockers
        )

    def test_requires_multi_order_session_env(self, monkeypatch):
        _set_all_gates(monkeypatch)
        monkeypatch.delenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", raising=False,
        )
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile()),
        )
        assert not r.approved

    def test_requires_profile_allow_multi(self, monkeypatch):
        _set_all_gates(monkeypatch)
        personal = resolve_profile("personal", capital=5000.0)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(personal),
        )
        assert not r.approved
        assert any("allow_multi_order_demo" in b for b in r.blockers)

    def test_personal_profile_does_not_allow_multi_real(self):
        personal = resolve_profile("personal", capital=5000.0)
        assert personal.allow_multi_order_demo is False

    def test_validation_profile_allows_multi(self):
        p = self._profile()
        assert p.allow_multi_order_demo is True
        assert p.allow_demo_real is True
        assert p.max_open_positions == 1
        assert p.require_sl_tp is True
        assert p.max_leverage == 1.0
        assert p.allow_short_demo is False

    def test_without_any_gate_blocks_with_5_env_blockers(
        self, monkeypatch,
    ):
        for env in _ALL_GATES:
            monkeypatch.delenv(env, raising=False)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile()),
        )
        assert not r.approved
        env_blockers = [b for b in r.blockers if "=true required" in b]
        assert len(env_blockers) == 5

    def test_observation_mode_blocks(self, monkeypatch):
        _set_all_gates(monkeypatch)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile(), observation_mode=True),
        )
        assert not r.approved
        assert any("observation_mode" in b for b in r.blockers)

    def test_synthetic_feed_blocks(self, monkeypatch):
        _set_all_gates(monkeypatch)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile(), synthetic_feed=True),
        )
        assert not r.approved

    def test_requires_real_time_and_demo_only(self, monkeypatch):
        _set_all_gates(monkeypatch)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile(), real_time=False),
        )
        assert not r.approved
        r2 = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile(), demo_only=False),
        )
        assert not r2.approved

    def test_phrase_must_match_exactly_with_n(self, monkeypatch):
        _set_all_gates(monkeypatch)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(
                self._profile(),
                phrase_confirmation=expected_phrase_30_2(3),  # N errado
            ),
        )
        assert not r.approved
        assert any("phrase" in b for b in r.blockers)

    def test_max_real_orders_cap(self, monkeypatch):
        _set_all_gates(monkeypatch)
        for bad in (0, 4, -1):
            r = validate_phase30_2_real_multi_gate(
                **_gate_kwargs(
                    self._profile(), max_real_orders=bad,
                    phrase_confirmation=expected_phrase_30_2(bad),
                ),
            )
            assert not r.approved

    def test_approves_with_everything(self, monkeypatch):
        _set_all_gates(monkeypatch)
        r = validate_phase30_2_real_multi_gate(
            **_gate_kwargs(self._profile()),
        )
        assert r.approved, r.blockers


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------

class TestStateMachine:

    def test_entry_allowed_states(self):
        assert can_accept_new_entry(MultiOrderExecutionState.IDLE)
        assert can_accept_new_entry(
            MultiOrderExecutionState.WAITING_SIGNAL,
        )
        assert can_accept_new_entry(
            MultiOrderExecutionState.TRADE_COMPLETED,
        )

    def test_entry_blocked_states(self):
        for state in (
            MultiOrderExecutionState.POSITION_MONITORING,
            MultiOrderExecutionState.WAITING_EXIT,
            MultiOrderExecutionState.FLAT_CHECKING,
            MultiOrderExecutionState.PNL_RESOLVING,
            MultiOrderExecutionState.ORDER_SUBMITTED,
            MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
        ):
            assert not can_accept_new_entry(state)


# ---------------------------------------------------------------------------
# RealTradeLifecycle com fakes scriptados (testes 13-22)
# ---------------------------------------------------------------------------

class _FakeGateOutcome:
    def __init__(self, submitted=True, sl=True, tp=True):
        self.orders_submitted = 1 if submitted else 0
        self.order_id = "FAKE-ORDER-1"
        self.client_order_id = "FAKE-CL-1"
        self.qty = 0.005
        self.post_session_check_summary = {
            "sl_attached": sl, "tp_attached": tp,
        }


def _make_lifecycle(
    *,
    gate=None,
    polls=None,
    flat=None,
    pnl=1.25,
    reduce_only=None,
    events=None,
    max_polls=5,
):
    """Lifecycle com fakes. polls = lista de dicts por poll."""
    polls = polls if polls is not None else [
        {"open_position_qty": 0.005, "mark_price": 100.0},
        {"open_position_qty": 0.0, "mark_price": 102.0},
    ]
    poll_iter = {"i": 0}

    def poll_fn(idx):
        i = min(poll_iter["i"], len(polls) - 1)
        poll_iter["i"] += 1
        return polls[i]

    def flat_fn(last_snap):
        return flat if flat is not None else {
            "is_flat": True, "open_orders_count": 0,
            "conditional_orders_count": 0,
        }

    def pnl_fn(*, record, exit_price, exit_reason):
        return pnl

    emitted = events if events is not None else []
    return RealTradeLifecycle(
        gate_callable=gate or (
            lambda **kw: _FakeGateOutcome()
        ),
        sl_tp_confirmed_fn=lambda oc: (
            oc.post_session_check_summary["sl_attached"] is True
            and oc.post_session_check_summary["tp_attached"] is True
        ),
        position_poll_fn=poll_fn,
        flat_check_fn=flat_fn,
        pnl_fetch_fn=pnl_fn,
        max_monitor_polls=max_polls,
        poll_interval_seconds=1.0,
        poll_sleep_fn=lambda s: None,   # fake sleep — NUNCA real
        reduce_only_close_fn=reduce_only,
        telemetry_emit=lambda et, **s: emitted.append((et, s)),
    ), emitted


def _buy_signal():
    from crypto_trading_bot.strategies.signal_model import (
        StrategySignal,
    )
    return StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="stub",
        entry_price=100.0, stop_loss_price=99.0,
        take_profit_price=102.0, position_size_usd=200.0,
    ).to_trading_signal()


class TestRealTradeLifecycle:

    def test_full_clean_cycle_completed(self):
        lc, events = _make_lifecycle()
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        d = record.to_dict()
        assert d["status"] == "completed"
        assert d["close_reason"] == "tp"   # exit 102 ~ tp 102
        assert d["realized_pnl"] == 1.25
        assert d["flat_check_after_trade"] is True
        assert d["opened_at"] and d["closed_at"]
        assert lc.state is MultiOrderExecutionState.TRADE_COMPLETED
        types = [e[0] for e in events]
        for expected in ("state_transition", "order_submitted",
                         "sl_tp_confirmed", "position_snapshot",
                         "exit_detected", "flat_check_done",
                         "pnl_recorded"):
            assert expected in types

    def test_sl_close_reason_derived(self):
        lc, _ = _make_lifecycle(polls=[
            {"open_position_qty": 0.005, "mark_price": 100.0},
            {"open_position_qty": 0.0, "mark_price": 99.0},
        ])
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.to_dict()["close_reason"] == "sl"

    def test_gate_not_submitting_means_manual_review(self):
        lc, _ = _make_lifecycle(
            gate=lambda **kw: _FakeGateOutcome(submitted=False),
        )
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "manual_review_required"
        assert lc.state is \
            MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED

    def test_sl_tp_not_confirmed_means_manual_review(self):
        lc, _ = _make_lifecycle(
            gate=lambda **kw: _FakeGateOutcome(sl=False),
        )
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "manual_review_required"
        assert record.notes == "sl_tp_not_confirmed"

    def test_position_open_after_budget_manual_review(self):
        # Posicao NUNCA fecha; sem reduceOnly -> manual review.
        lc, _ = _make_lifecycle(
            polls=[{"open_position_qty": 0.005, "mark_price": 100.0}],
            max_polls=3, reduce_only=None,
        )
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "manual_review_required"
        assert record.notes == "position_open_after_monitor_budget"

    def test_reduce_only_fallback_closes(self):
        lc, _ = _make_lifecycle(
            polls=[{"open_position_qty": 0.005, "mark_price": 100.5}],
            max_polls=2,
            reduce_only=lambda **kw: {"success": True, "reason": "ok"},
        )
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "completed"
        assert record.close_reason == "reduce_only"

    def test_flat_check_failure_manual_review(self):
        lc, _ = _make_lifecycle(
            flat={"is_flat": False, "open_orders_count": 1},
        )
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "manual_review_required"
        assert record.notes == "flat_check_failed_after_trade"

    def test_unresolved_pnl_marked(self):
        lc, _ = _make_lifecycle(pnl=None)
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
        )
        assert record.status == "unresolved"
        assert record.notes == "unresolved_pnl"

    def test_deadline_stops_monitoring(self):
        clock = FakeClock(_START)
        lc, _ = _make_lifecycle(
            polls=[{"open_position_qty": 0.005, "mark_price": 100.0}],
            max_polls=100,
        )
        lc._clock = clock
        lc._poll_sleep = clock.sleep
        record = lc.execute_trade(
            trade_idx=0, trading_signal=_buy_signal(),
            deadline=_START + timedelta(seconds=3),
        )
        # Deadline corta o monitor -> manual review (nunca clean aberto).
        assert record.status == "manual_review_required"


# ---------------------------------------------------------------------------
# Runner em modo real multi (testes 7, 15-18, 23-26)
# ---------------------------------------------------------------------------

class _ScriptedLifecycle:
    """Lifecycle fake: devolve records scriptados por chamada."""

    def __init__(self, records):
        self._records = list(records)
        self.calls = 0
        self.signals_seen = []

    def execute_trade(self, *, trade_idx, trading_signal,
                      latest_snapshot=None, deadline=None):
        self.signals_seen.append(trading_signal)
        rec = self._records[min(self.calls, len(self._records) - 1)]
        self.calls += 1
        out = RealTradeRecord(
            trade_idx=trade_idx, side="buy", symbol="BTCUSDT",
            entry_price=100.0, qty=0.005, notional=200.0,
            stop_loss_price=99.0, take_profit_price=102.0,
        )
        out.opened_at = "2026-06-11T12:00:00+00:00"
        out.closed_at = "2026-06-11T12:05:00+00:00"
        out.status = rec.get("status", "completed")
        out.close_reason = rec.get("close_reason", "tp")
        out.realized_pnl = rec.get("realized_pnl", 1.0)
        out.flat_check_after_trade = rec.get("flat", True)
        return out


def _make_real_runner(clock, *, lifecycle, max_real=2, profile=None,
                      strategy=None, flat_check=None):
    profile = profile or resolve_profile(
        "demo_multi_order_validation", capital=5000.0,
    )
    return DemoEnduranceRunner(
        profile=profile,
        duration=DurationSpec(
            duration_minutes=30, cycle_interval_seconds=60,
        ),
        limits=derive_endurance_limits(profile),
        symbol="BTCUSDT",
        strategy_name="trend_pullback_bidirectional",
        operator_token="OPTOK_TEST",
        market_data_callable=_fresh_candles(clock),
        feature_engine=StubFeatureEngine(),
        strategy=strategy or StubStrategyBuy(),
        risk_engine=StubRiskApprove(),
        real_time=True,
        clock=clock, sleep=clock.sleep,
        execute_real_multi=True,
        max_real_orders=max_real,
        real_trade_lifecycle=lifecycle,
        flat_check_callable=flat_check,
    )


class TestRunnerRealMulti:

    def test_constructor_guards(self):
        clock = FakeClock(_START)
        profile = resolve_profile(
            "demo_multi_order_validation", capital=5000.0,
        )
        common = dict(
            profile=profile,
            duration=DurationSpec(duration_minutes=30),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback",
            operator_token="T",
            market_data_callable=lambda **kw: [],
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyBuy(),
            risk_engine=StubRiskApprove(),
            clock=clock, sleep=clock.sleep,
        )
        # real multi + observacao => ValueError (teste 7)
        with pytest.raises(ValueError, match="incompativel"):
            DemoEnduranceRunner(
                **common, real_time=True, execute_real_multi=True,
                max_real_orders=2,
                real_trade_lifecycle=_ScriptedLifecycle([{}]),
                continue_after_would_order=True,
            )
        # exige real_time
        with pytest.raises(ValueError, match="real_time"):
            DemoEnduranceRunner(
                **common, real_time=False, execute_real_multi=True,
                max_real_orders=2,
                real_trade_lifecycle=_ScriptedLifecycle([{}]),
            )
        # max fora de [1,3]
        with pytest.raises(ValueError, match="max_real_orders"):
            DemoEnduranceRunner(
                **common, real_time=True, execute_real_multi=True,
                max_real_orders=5,
                real_trade_lifecycle=_ScriptedLifecycle([{}]),
            )
        # exige lifecycle
        with pytest.raises(ValueError, match="lifecycle"):
            DemoEnduranceRunner(
                **common, real_time=True, execute_real_multi=True,
                max_real_orders=2, real_trade_lifecycle=None,
            )
        # perfil sem permissao
        personal = resolve_profile("personal", capital=5000.0)
        with pytest.raises(ValueError, match="multi-order"):
            DemoEnduranceRunner(
                **{**common, "profile": personal,
                   "limits": derive_endurance_limits(personal)},
                real_time=True, execute_real_multi=True,
                max_real_orders=2,
                real_trade_lifecycle=_ScriptedLifecycle([{}]),
            )

    def test_sequential_two_trades_then_max_completed(self):
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([
            {"status": "completed", "close_reason": "tp",
             "realized_pnl": 2.0},
            {"status": "completed", "close_reason": "sl",
             "realized_pnl": -1.0},
        ])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, max_real=2,
        ).run()
        d = outcome.to_dict()
        assert d["execution_mode"] == "real_demo_multi_order"
        assert d["dry_run"] is False
        assert d["orders_submitted"] == 2
        assert d["orders_submitted"] <= 2  # teste 23
        assert d["trades_completed"] == 2
        assert d["trades_closed_by_tp"] == 1
        assert d["trades_closed_by_sl"] == 1
        assert d["total_realized_pnl"] == pytest.approx(1.0)
        assert d["ended_reason"] == "max_real_orders_completed"
        assert len(d["per_trade_records"]) == 2
        assert lifecycle.calls == 2

    def test_no_new_entry_while_trade_in_flight(self):
        # O lifecycle e BLOQUEANTE: enquanto execute_trade roda, o
        # runner NAO avalia novos sinais. Prova: 1 chamada por trade,
        # nunca em paralelo (calls == trades, nao == ciclos).
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([
            {"status": "completed"}, {"status": "completed"},
        ])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, max_real=2,
        ).run()
        assert lifecycle.calls == 2
        assert outcome.cycles_completed >= 2

    def test_manual_review_trade_ends_session(self):
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([
            {"status": "manual_review_required", "flat": None},
        ])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, max_real=2,
        ).run()
        d = outcome.to_dict()
        assert d["ended_reason"] == "manual_review_required"
        assert d["trades_manual_review"] == 1
        assert lifecycle.calls == 1  # NAO repete (regra da spec)

    def test_duration_completed_flat_when_time_ends(self):
        # 1 trade completo; estrategia para de sinalizar; tempo acaba.
        class OneShotStrategy:
            def __init__(self):
                self.fired = False

            def evaluate(self, features):
                from crypto_trading_bot.strategies.signal_model import (
                    StrategySignal,
                )
                if self.fired:
                    return StrategySignal.hold(
                        symbol="BTCUSDT", strategy_name="stub",
                        reason="no_setup",
                    )
                self.fired = True
                return StrategySignal.buy(
                    symbol="BTCUSDT", strategy_name="stub",
                    entry_price=100.0, stop_loss_price=99.0,
                    take_profit_price=102.0, position_size_usd=200.0,
                )
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([{"status": "completed"}])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, max_real=2,
            strategy=OneShotStrategy(),
        ).run()
        assert outcome.ended_reason is \
            EnduranceEndedReason.DURATION_COMPLETED_FLAT
        assert outcome.orders_submitted == 1

    def test_zero_signals_passed_zero_trades(self):
        from tests.test_phase30_demo_endurance import StubStrategyHold
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([{}])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, strategy=StubStrategyHold(),
        ).run()
        assert outcome.ended_reason is \
            EnduranceEndedReason.PASSED_ZERO_TRADES
        assert outcome.orders_submitted == 0
        assert lifecycle.calls == 0

    def test_residual_before_entry_blocks(self):
        # Regras 13-15: flat-check pre-entrada com residual.
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([{"status": "completed"}])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle,
            flat_check=lambda: {"is_flat": False,
                                "open_orders_count": 1},
        ).run()
        assert outcome.ended_reason is \
            EnduranceEndedReason.MANUAL_REVIEW_REQUIRED
        assert lifecycle.calls == 0   # entrada bloqueada
        assert "unexpected_residual_before_entry" in outcome.warnings

    def test_risk_rejection_means_no_order(self):
        # Teste 14: RiskEngine reprova -> lifecycle nunca chamado.
        class RiskReject:
            def validate_signal(self, signal):
                class _R:
                    approved = False
                    reason = "test fixture rejection"
                return _R()
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([{}])
        profile = resolve_profile(
            "demo_multi_order_validation", capital=5000.0,
        )
        outcome = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=10, cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="T",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyBuy(),
            risk_engine=RiskReject(),
            real_time=True, clock=clock, sleep=clock.sleep,
            execute_real_multi=True, max_real_orders=2,
            real_trade_lifecycle=lifecycle,
        ).run()
        assert lifecycle.calls == 0
        assert outcome.orders_submitted == 0

    def test_no_scale_in_no_position_sum_no_reversal(self):
        # Testes 16-18: outcome NUNCA permite scale-in/reversao nesta
        # fase (invariantes do dataclass) e o fluxo e sequencial puro.
        clock = FakeClock(_START)
        lifecycle = _ScriptedLifecycle([
            {"status": "completed"}, {"status": "completed"},
        ])
        outcome = _make_real_runner(
            clock, lifecycle=lifecycle, max_real=2,
        ).run()
        d = outcome.to_dict()
        assert d["scale_in_allowed"] is False
        assert d["auto_reversal_allowed"] is False
        # Cada trade tem registro proprio (sem soma de posicao).
        assert len(d["per_trade_records"]) == 2
        assert all(
            r["trade_idx"] == i
            for i, r in enumerate(d["per_trade_records"])
        )

    def test_outcome_forbids_scale_in_flag(self):
        with pytest.raises(ValueError, match="scale_in"):
            DemoEnduranceOutcome(
                session_id="s", profile_name="p", symbol="BTCUSDT",
                strategy_name="t", real_time_mode=True,
                time_compressed=False, dry_run=False,
                started_at=_START, ended_at=_START,
                elapsed_wall_clock_seconds=0.0,
                cycle_interval_seconds=60.0,
                configured_duration_minutes=30,
                configured_duration_days=None,
                cycles_completed=1, expected_cycles=30,
                ended_reason=(
                    EnduranceEndedReason.DURATION_COMPLETED_FLAT
                ),
                execution_mode="real_demo_multi_order",
                real_orders_enabled=True, max_real_orders=2,
                orders_submitted=1, orders_filled=1,
                scale_in_allowed=True,
            )

    def test_outcome_never_clean_with_open_position(self):
        # Teste 26-27: posicao residual + reason "completed" => erro.
        with pytest.raises(ValueError, match="residual"):
            DemoEnduranceOutcome(
                session_id="s", profile_name="p", symbol="BTCUSDT",
                strategy_name="t", real_time_mode=True,
                time_compressed=False, dry_run=False,
                started_at=_START, ended_at=_START,
                elapsed_wall_clock_seconds=0.0,
                cycle_interval_seconds=60.0,
                configured_duration_minutes=30,
                configured_duration_days=None,
                cycles_completed=1, expected_cycles=30,
                ended_reason=(
                    EnduranceEndedReason.MAX_REAL_ORDERS_COMPLETED
                ),
                execution_mode="real_demo_multi_order",
                real_orders_enabled=True, max_real_orders=2,
                orders_submitted=1, orders_filled=1,
                final_open_positions_count=1,
            )

    def test_dry_run_30_and_30_1_preserved(self):
        # Teste 33-34: sem execute_real_multi, comportamento identico.
        clock = FakeClock(_START)
        profile = resolve_profile("personal", capital=5000.0)
        outcome = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=10, cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="T",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyBuy(),
            risk_engine=StubRiskApprove(),
            real_time=True, clock=clock, sleep=clock.sleep,
        ).run()
        d = outcome.to_dict()
        assert d["execution_mode"] == "wired_dry_run"
        assert d["dry_run"] is True
        assert d["orders_submitted"] == 0
        assert d["would_orders"] == 1


# ---------------------------------------------------------------------------
# Pre-fixes da sessao real 002
# ---------------------------------------------------------------------------

class TestPreFixes:

    def test_telemetry_accepts_new_event_types(self):
        from crypto_trading_bot.demo_endurance import (
            SessionTelemetryRecorder,
        )
        rec = SessionTelemetryRecorder(operator_token="OPTOK_TEST")
        for et in (
            "stale_market_data", "would_order_recorded",
            "hourly_snapshot", "daily_summary",
            "phase29_short_gate_checked", "ai_advice_generated",
            "prediction_context_loaded", "state_transition",
            "order_submitted", "sl_tp_confirmed", "exit_detected",
            "flat_check_done", "pnl_recorded", "position_snapshot",
        ):
            rec.record(et, snapshot={"k": "v"})
        types = [e.event_type for e in rec.events]
        # NENHUM evento virou fallback api_failure.
        assert "api_failure" not in types
        assert "state_transition" in types

    def test_stale_threshold_accounts_for_timeframe(self):
        # Candle 15m com 10 min de idade NAO e stale; com 25 min e.
        from dataclasses import replace as dc_replace
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        clock = FakeClock(_START)
        base = generate_trending_candles(
            n=60, base_price=100.0, trend_pct_per_candle=0.001,
            volatility_pct=0.005, symbol="BTCUSDT", timeframe="15",
        )

        def feed_age(minutes):
            # Ultimo candle fica exatamente `minutes` de idade.
            def feed(**kw):
                n = len(base)
                return [
                    dc_replace(
                        c,
                        timestamp=clock.now - timedelta(
                            minutes=minutes + (n - 1 - i) * 15,
                        ),
                    )
                    for i, c in enumerate(base)
                ]
            return feed

        profile = resolve_profile("personal", capital=5000.0)

        def run_with(minutes):
            clk = FakeClock(_START)
            runner = DemoEnduranceRunner(
                profile=profile,
                duration=DurationSpec(
                    duration_minutes=3, cycle_interval_seconds=60,
                ),
                limits=derive_endurance_limits(profile),
                symbol="BTCUSDT",
                strategy_name="trend_pullback_bidirectional",
                operator_token="T",
                market_data_callable=feed_age(minutes),
                feature_engine=StubFeatureEngine(),
                strategy=StubStrategyBuy(),
                risk_engine=StubRiskApprove(),
                real_time=True, clock=clk, sleep=clk.sleep,
            )
            return runner.run()

        fresh = run_with(10)    # ultimo candle ~10min: OK (< 900+300s)
        assert "stale_market_data" not in fresh.warnings
        stale = run_with(25)    # ~25min: stale (> 1200s)
        assert "stale_market_data" in stale.warnings
