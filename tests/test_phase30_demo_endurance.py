"""
Tests - FASE 30: demo endurance real-time (DurationSpec, runner,
preflight, outcome)
====================================================================
100% offline. ZERO rede. ZERO ordem real. Fake clock + fake sleep —
NUNCA sleep real em teste.
"""

from __future__ import annotations

from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    DemoEnduranceOutcome,
    DemoEnduranceRunner,
    DurationSpec,
    EnduranceEndedReason,
    EnduranceLimits,
    validate_endurance_preflight,
)
from crypto_trading_bot.operational_profile import (
    derive_endurance_limits,
    resolve_profile,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal


_START = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


class FakeClock:
    """Relogio virtual: sleep avanca o tempo SEM esperar de verdade."""

    def __init__(self, start: datetime = _START) -> None:
        self.now = start
        self.sleep_calls = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += timedelta(seconds=seconds)


class StubFeatureEngine:
    def compute(self, candles):
        return {"n_candles": len(candles)}


class StubStrategyHold:
    def evaluate(self, features):
        return StrategySignal.hold(
            symbol="BTCUSDT", strategy_name="stub",
            reason="no_valid_long_or_short_setup",
        )


class StubStrategyBuy:
    def evaluate(self, features):
        return StrategySignal.buy(
            symbol="BTCUSDT", strategy_name="stub",
            entry_price=100.0, stop_loss_price=99.0,
            take_profit_price=102.0, position_size_usd=200.0,
        )


class StubRiskApprove:
    def validate_signal(self, signal):
        class _R:
            approved = True
            reason = ""
        return _R()


def _fresh_candles(clock: FakeClock, n: int = 60):
    """Candles sinteticos com timestamp sempre fresco vs fake clock."""
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    base = generate_trending_candles(
        n=n, base_price=100.0, trend_pct_per_candle=0.001,
        volatility_pct=0.005, symbol="BTCUSDT", timeframe="15",
    )

    def feed(*, symbol, timeframe, limit):
        now = clock.now
        return [
            dc_replace(c, timestamp=now - timedelta(minutes=(n - i)))
            for i, c in enumerate(base)
        ]
    return feed


def _make_runner(
    clock: FakeClock, *, profile=None, duration=None, limits=None,
    strategy=None, risk=None, market_data=None, real_time=True,
    **kw,
):
    profile = profile or resolve_profile("personal", capital=5000.0)
    duration = duration or DurationSpec(
        duration_minutes=30, cycle_interval_seconds=60,
    )
    return DemoEnduranceRunner(
        profile=profile,
        duration=duration,
        limits=limits or derive_endurance_limits(profile),
        symbol="BTCUSDT",
        strategy_name="trend_pullback_bidirectional",
        operator_token="OPTOK",
        market_data_callable=market_data or _fresh_candles(clock),
        feature_engine=StubFeatureEngine(),
        strategy=strategy or StubStrategyHold(),
        risk_engine=risk or StubRiskApprove(),
        real_time=real_time,
        clock=clock, sleep=clock.sleep,
        **kw,
    )


# ---------------------------------------------------------------------------
# 1-3: DurationSpec
# ---------------------------------------------------------------------------

class TestDurationSpec:

    def test_accepts_minutes_xor_days(self):
        m = DurationSpec(duration_minutes=30)
        assert m.expected_cycles == 30
        assert m.kind == "short"
        d = DurationSpec(duration_days=7)
        assert d.kind == "long"
        assert d.expected_cycles == 7 * 24 * 60

    def test_rejects_both_and_neither(self):
        with pytest.raises(ValueError, match="EXATAMENTE"):
            DurationSpec(duration_minutes=30, duration_days=1)
        with pytest.raises(ValueError, match="EXATAMENTE"):
            DurationSpec()

    def test_rejects_invalid_values(self):
        with pytest.raises(ValueError):
            DurationSpec(duration_minutes=0)
        with pytest.raises(ValueError):
            DurationSpec(duration_days=-1)
        with pytest.raises(ValueError):
            DurationSpec(duration_minutes=30, cycle_interval_seconds=0.5)

    def test_expected_cycles_never_zero(self):
        # 1 min com intervalo de 90s: floor=0 -> clampa para 1.
        spec = DurationSpec(
            duration_minutes=1, cycle_interval_seconds=90,
        )
        assert spec.expected_cycles == 1

    def test_long_kinds(self):
        assert DurationSpec(duration_minutes=120).kind == "short"
        assert DurationSpec(duration_minutes=121).kind == "long"
        assert DurationSpec(duration_days=1).is_long


# ---------------------------------------------------------------------------
# 4-7: real-time com fake clock; time-compressed separado; report
# ---------------------------------------------------------------------------

class TestRealTimeClock:

    def test_30min_realtime_uses_fake_clock_in_test(self):
        clock = FakeClock()
        runner = _make_runner(clock, real_time=True)
        outcome = runner.run()
        # 30 ciclos consumiram 30 min VIRTUAIS (fake clock).
        assert outcome.cycles_completed == 30
        assert outcome.elapsed_wall_clock_minutes == pytest.approx(
            30.0, abs=0.5,
        )
        # sleep (fake) foi chamado a cada ciclo — NUNCA no-op em real-time.
        assert len(clock.sleep_calls) == 30
        assert all(s == 60.0 for s in clock.sleep_calls)

    def test_time_compressed_vs_real_time_flags(self):
        clock = FakeClock()
        rt = _make_runner(clock, real_time=True).run()
        assert rt.real_time_mode is True
        assert rt.time_compressed is False
        clock2 = FakeClock()
        tc = _make_runner(clock2, real_time=False).run()
        assert tc.real_time_mode is False
        assert tc.time_compressed is True

    def test_report_contains_mode_and_wall_clock(self):
        clock = FakeClock()
        d = _make_runner(clock).run().to_dict()
        for key in (
            "real_time_mode", "time_compressed",
            "elapsed_wall_clock_seconds", "elapsed_wall_clock_minutes",
            "cycle_interval_seconds", "configured_duration_minutes",
            "configured_duration_days", "cycles_completed",
            "expected_cycles", "ended_reason", "started_at", "ended_at",
            "signals_evaluated", "would_orders", "orders_submitted",
            "daily_summaries", "hourly_snapshots", "per_trade_records",
            "session_summary",
        ):
            assert key in d, f"campo obrigatorio ausente: {key}"
        assert d["elapsed_wall_clock_seconds"] == pytest.approx(
            1800.0, abs=60.0,
        )

    def test_default_realtime_sleep_is_time_sleep(self):
        # Producao real-time sem sleep injetado usa time.sleep REAL.
        import time as time_mod
        profile = resolve_profile("personal", capital=5000.0)
        runner = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(duration_minutes=30),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTOK",
            market_data_callable=lambda **kw: [],
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyHold(),
            risk_engine=StubRiskApprove(),
            real_time=True,
        )
        assert runner._sleep is time_mod.sleep
        # E sem real-time o no-op eh INTENCIONAL (time-compressed).
        runner_tc = DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(duration_minutes=30),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTOK",
            market_data_callable=lambda **kw: [],
            feature_engine=StubFeatureEngine(),
            strategy=StubStrategyHold(),
            risk_engine=StubRiskApprove(),
            real_time=False,
        )
        assert runner_tc._sleep is not time_mod.sleep


# ---------------------------------------------------------------------------
# 8-9: demo longa gera daily summary + hourly snapshot
# ---------------------------------------------------------------------------

class TestLongDemoSummaries:

    def test_long_demo_generates_daily_summary_and_hourly(self):
        clock = FakeClock()
        duration = DurationSpec(
            duration_days=2, cycle_interval_seconds=6 * 3600,
        )
        outcome = _make_runner(clock, duration=duration).run()
        # 2 dias / 6h = 8 ciclos; cruzou fronteira de dia 1 vez no meio
        # + summary final obrigatorio.
        assert outcome.cycles_completed == 8
        assert len(outcome.daily_summaries) >= 2
        assert len(outcome.hourly_snapshots) >= 1
        kinds = {s["kind"] for s in outcome.daily_summaries}
        assert "daily_final" in kinds

    def test_short_demo_still_has_final_summary(self):
        clock = FakeClock()
        outcome = _make_runner(clock).run()
        assert len(outcome.daily_summaries) == 1
        assert outcome.daily_summaries[0]["kind"] == "daily_final"


# ---------------------------------------------------------------------------
# 10-11: preflight bloqueia residual/ordens abertas
# ---------------------------------------------------------------------------

class TestEndurancePreflight:

    def _base(self, **kw):
        base = dict(
            open_positions_count=0, open_orders_count=0,
            conditional_orders_count=0, safety_state="normal",
            provider_id="bybit_demo_linear", environment="demo",
            demo_credentials_present=True,
        )
        base.update(kw)
        return validate_endurance_preflight(**base)

    def test_clean_state_approved(self):
        r = self._base()
        assert r.approved and not r.manual_review_required

    def test_blocked_with_residual_position(self):
        r = self._base(open_positions_count=1)
        assert not r.approved
        assert r.manual_review_required
        assert any("open_positions" in b for b in r.blockers)

    def test_blocked_with_open_orders(self):
        r = self._base(open_orders_count=2)
        assert not r.approved
        assert any("open_orders" in b for b in r.blockers)

    def test_blocked_with_conditional_orders(self):
        r = self._base(conditional_orders_count=1)
        assert not r.approved

    def test_blocked_with_bad_safety_state(self):
        r = self._base(safety_state="halted")
        assert not r.approved

    def test_blocked_with_wrong_provider(self):
        r = self._base(provider_id="bybit_mainnet")
        assert not r.approved

    def test_blocked_with_live_environment(self):
        r = self._base(environment="live")
        assert not r.approved
        assert any("mainnet/live" in b for b in r.blockers)

    def test_blocked_without_demo_credentials(self):
        r = self._base(demo_credentials_present=False)
        assert not r.approved

    def test_blocked_without_previous_report_when_required(self):
        r = self._base(
            require_previous_report=True,
            previous_report_path="reports/_does_not_exist_xyz.json",
        )
        assert not r.approved
        assert any("report anterior" in b for b in r.blockers)

    def test_api_probe_failure_blocks(self):
        r = self._base(api_probe=lambda: False)
        assert not r.approved


class _FakeModeGuard:
    """Espelha as properties REAIS do ModeGuard (is_live / is_safe)."""

    def __init__(self, *, is_live: bool) -> None:
        self._is_live = is_live

    @property
    def is_live(self) -> bool:
        return self._is_live

    @property
    def is_safe(self) -> bool:
        return not self._is_live


class TestPreflightModeGuardHotfix:
    """FASE 30 hotfix: preflight le is_safe/is_live REAIS do ModeGuard.

    Bug original: getattr(mode_guard, 'is_safe_mode', False) — nome
    inexistente no ModeGuard — bloqueava demo safe contradizendo o
    log safe=True do proprio guard.
    """

    def _base(self, **kw):
        base = dict(
            open_positions_count=0, open_orders_count=0,
            conditional_orders_count=0, safety_state="normal",
            provider_id="bybit_demo_linear", environment="demo",
            demo_credentials_present=True,
        )
        base.update(kw)
        return validate_endurance_preflight(**base)

    def test_real_mode_guard_demo_safe_approves(self, monkeypatch):
        # ModeGuard REAL em demo safe (cenario do operador):
        # mode=demo, live_enabled=False, demo_exec_enabled=True.
        monkeypatch.setenv("TRADING_MODE", "demo")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
        monkeypatch.setenv("ENABLE_DEMO_EXECUTION", "true")
        from crypto_trading_bot.core.mode_guard import ModeGuard
        guard = ModeGuard()
        assert guard.is_safe is True  # pre-condicao do cenario
        r = self._base(
            mode_guard=guard,
            endpoint_url="https://api-demo.bybit.com",
        )
        assert r.approved, r.blockers

    def test_demo_exec_enabled_alone_does_not_block(self, monkeypatch):
        # demo_exec_enabled=True NAO eh unsafe quando live=False.
        monkeypatch.setenv("TRADING_MODE", "demo")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
        monkeypatch.setenv("ENABLE_DEMO_EXECUTION", "true")
        from crypto_trading_bot.core.mode_guard import ModeGuard
        r = self._base(mode_guard=ModeGuard())
        assert not any("ModeGuard" in b for b in r.blockers)

    def test_live_mode_guard_blocks(self):
        r = self._base(mode_guard=_FakeModeGuard(is_live=True))
        assert not r.approved
        assert any("is_live=True" in b for b in r.blockers)

    def test_real_mode_guard_live_enabled_blocks(self, monkeypatch):
        monkeypatch.setenv("TRADING_MODE", "live")
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        from crypto_trading_bot.core.mode_guard import ModeGuard
        guard = ModeGuard()
        assert guard.is_live is True  # pre-condicao
        r = self._base(mode_guard=guard)
        assert not r.approved
        assert any("live/mainnet proibido" in b for b in r.blockers)

    def test_guard_without_safe_properties_blocks(self):
        class Unknown:
            pass
        r = self._base(mode_guard=Unknown())
        assert not r.approved
        assert any("modo seguro" in b for b in r.blockers)

    def test_mainnet_endpoint_blocks(self):
        r = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            endpoint_url="https://api.bybit.com",
        )
        assert not r.approved
        assert any("endpoint nao-demo" in b for b in r.blockers)

    def test_demo_endpoint_approves(self):
        r = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            endpoint_url="https://api-demo.bybit.com",
        )
        assert r.approved, r.blockers

    def test_residual_still_blocks_with_safe_guard(self):
        # Hotfix nao afrouxa os demais blockers.
        r = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            open_positions_count=1,
        )
        assert not r.approved
        r2 = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            open_orders_count=1,
        )
        assert not r2.approved
        r3 = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            conditional_orders_count=1,
        )
        assert not r3.approved

    def test_wrong_provider_environment_still_block(self):
        r = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            provider_id="bybit_mainnet",
        )
        assert not r.approved
        r2 = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            environment="live",
        )
        assert not r2.approved

    def test_missing_credentials_still_block(self):
        r = self._base(
            mode_guard=_FakeModeGuard(is_live=False),
            demo_credentials_present=False,
        )
        assert not r.approved


# ---------------------------------------------------------------------------
# 12-13: wired dry-run -> would_orders; nunca order_completed
# ---------------------------------------------------------------------------

class TestWouldOrders:

    def test_would_order_recorded_and_orders_submitted_zero(self):
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
        ).run()
        assert outcome.would_orders == 1
        assert outcome.orders_submitted == 0
        assert outcome.orders_filled == 0
        assert len(outcome.per_trade_records) == 1
        rec = outcome.per_trade_records[0]
        assert rec["kind"] == "would_order"
        assert rec["dry_run"] is True

    def test_ended_reason_is_dry_run_would_order(self):
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
        ).run()
        assert outcome.ended_reason is \
            EnduranceEndedReason.DRY_RUN_WOULD_ORDER_COMPLETED
        assert outcome.ended_reason.value != "order_completed"

    def test_outcome_rejects_order_completed_in_dry_run(self):
        clock = FakeClock()
        good = _make_runner(clock, strategy=StubStrategyBuy()).run()
        with pytest.raises(ValueError, match="would_order"):
            DemoEnduranceOutcome(
                **{
                    **{
                        f: getattr(good, f) for f in (
                            "session_id", "profile_name", "symbol",
                            "strategy_name", "real_time_mode",
                            "time_compressed", "dry_run", "started_at",
                            "ended_at", "elapsed_wall_clock_seconds",
                            "cycle_interval_seconds",
                            "configured_duration_minutes",
                            "configured_duration_days",
                            "cycles_completed", "expected_cycles",
                        )
                    },
                    "ended_reason":
                        EnduranceEndedReason.ORDER_COMPLETED,
                }
            )

    def test_outcome_rejects_submitted_orders_in_dry_run(self):
        with pytest.raises(ValueError, match="orders_submitted"):
            DemoEnduranceOutcome(
                session_id="s", profile_name="p", symbol="BTCUSDT",
                strategy_name="t", real_time_mode=True,
                time_compressed=False, dry_run=True,
                started_at=_START, ended_at=_START,
                elapsed_wall_clock_seconds=0.0,
                cycle_interval_seconds=60.0,
                configured_duration_minutes=30,
                configured_duration_days=None,
                cycles_completed=1, expected_cycles=30,
                ended_reason=EnduranceEndedReason.DURATION_COMPLETED,
                orders_submitted=1,
            )


# ---------------------------------------------------------------------------
# Modo OBSERVACAO dry-run (continue_after_would_order)
# ---------------------------------------------------------------------------

class TestObservationMode:
    """Observacao continua apos would-order. Dry-run APENAS:
    orders_submitted=0 sempre; nao exige gate multi-order real."""

    def test_continues_after_first_would_order(self, monkeypatch):
        # Sem gate multi-order real (env ausente de proposito).
        monkeypatch.delenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", raising=False,
        )
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
            continue_after_would_order=True,
        ).run()
        # Continuou ate o fim da janela registrando 1 would-order/ciclo.
        assert outcome.would_orders == 30
        assert outcome.cycles_completed == 30
        assert outcome.ended_reason is \
            EnduranceEndedReason.DURATION_COMPLETED
        assert outcome.orders_submitted == 0
        assert outcome.orders_filled == 0
        assert all(
            r["dry_run"] is True for r in outcome.per_trade_records
        )

    def test_max_would_orders_stops_with_own_reason(self, monkeypatch):
        monkeypatch.delenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", raising=False,
        )
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
            continue_after_would_order=True, max_would_orders=3,
        ).run()
        assert outcome.would_orders == 3
        assert outcome.ended_reason is \
            EnduranceEndedReason.MAX_WOULD_ORDERS_REACHED
        assert outcome.orders_submitted == 0

    def test_max_would_orders_requires_continue_flag(self):
        clock = FakeClock()
        with pytest.raises(ValueError, match="continue_after"):
            _make_runner(
                clock, strategy=StubStrategyBuy(),
                max_would_orders=3,
            )

    def test_invalid_max_would_orders_rejected(self):
        clock = FakeClock()
        with pytest.raises(ValueError, match=">= 1"):
            _make_runner(
                clock, strategy=StubStrategyBuy(),
                continue_after_would_order=True, max_would_orders=0,
            )

    def test_default_behavior_unchanged_without_flag(self):
        # Sem observacao: para na 1a would-order (single-order default).
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
        ).run()
        assert outcome.would_orders == 1
        assert outcome.ended_reason is \
            EnduranceEndedReason.DRY_RUN_WOULD_ORDER_COMPLETED

    def test_observation_recorded_in_session_summary(self):
        clock = FakeClock()
        outcome = _make_runner(
            clock, strategy=StubStrategyBuy(),
            continue_after_would_order=True, max_would_orders=2,
        ).run()
        summary = dict(outcome.session_summary)
        assert summary["observation_mode"] is True
        assert summary["max_would_orders"] == 2
        assert summary["orders_submitted"] == 0

    def test_outcome_accepts_max_would_orders_reached_in_dry_run(self):
        out = DemoEnduranceOutcome(
            session_id="s", profile_name="p", symbol="BTCUSDT",
            strategy_name="t", real_time_mode=True,
            time_compressed=False, dry_run=True,
            started_at=_START, ended_at=_START,
            elapsed_wall_clock_seconds=0.0,
            cycle_interval_seconds=60.0,
            configured_duration_minutes=30,
            configured_duration_days=None,
            cycles_completed=5, expected_cycles=30,
            ended_reason=(
                EnduranceEndedReason.MAX_WOULD_ORDERS_REACHED
            ),
            would_orders=3,
        )
        assert out.to_dict()["ended_reason"] == \
            "max_would_orders_reached"


# ---------------------------------------------------------------------------
# Single-order default + gate multi-order independente
# ---------------------------------------------------------------------------

class TestSingleOrderDefault:

    def test_stops_at_first_would_order_without_gate(self, monkeypatch):
        monkeypatch.delenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", raising=False,
        )
        clock = FakeClock()
        profile = resolve_profile(
            "personal", capital=5000.0,
            allow_multi_order_demo=True,       # perfil permite...
            max_orders_per_session=3,
        )
        outcome = _make_runner(
            clock, profile=profile, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile),
        ).run()
        # ...mas SEM gate ENV continua single-order.
        assert outcome.would_orders == 1

    def test_multi_order_requires_profile_and_gate(self, monkeypatch):
        monkeypatch.setenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", "true",
        )
        clock = FakeClock()
        profile = resolve_profile(
            "personal", capital=5000.0,
            allow_multi_order_demo=True,
            max_orders_per_session=3, max_orders_per_day=5,
        )
        outcome = _make_runner(
            clock, profile=profile, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile),
        ).run()
        assert outcome.would_orders == 3
        # Gate sozinho (sem perfil) tambem nao libera.
        clock2 = FakeClock()
        profile2 = resolve_profile(
            "personal", capital=5000.0,
            allow_multi_order_demo=False, max_orders_per_session=3,
        )
        outcome2 = _make_runner(
            clock2, profile=profile2, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile2),
        ).run()
        assert outcome2.would_orders == 1


# ---------------------------------------------------------------------------
# Perfil soberano no runner (teste 19: nada hardcoded)
# ---------------------------------------------------------------------------

class TestProfileSovereignInRunner:

    def test_runner_rejects_symbol_not_in_profile(self):
        clock = FakeClock()
        profile = resolve_profile("personal", capital=5000.0)
        with pytest.raises(ValueError, match="nao permitido"):
            DemoEnduranceRunner(
                profile=profile,
                duration=DurationSpec(duration_minutes=30),
                limits=derive_endurance_limits(profile),
                symbol="DOGEUSDT",   # fora de allowed_symbols
                strategy_name="trend_pullback",
                operator_token="OPTOK",
                market_data_callable=lambda **kw: [],
                feature_engine=StubFeatureEngine(),
                strategy=StubStrategyHold(),
                risk_engine=StubRiskApprove(),
                clock=clock, sleep=clock.sleep,
            )

    def test_runner_rejects_strategy_not_in_profile(self):
        clock = FakeClock()
        profile = resolve_profile("personal", capital=5000.0)
        with pytest.raises(ValueError, match="nao permitida"):
            DemoEnduranceRunner(
                profile=profile,
                duration=DurationSpec(duration_minutes=30),
                limits=derive_endurance_limits(profile),
                symbol="BTCUSDT",
                strategy_name="fake_strategy_xyz",
                operator_token="OPTOK",
                market_data_callable=lambda **kw: [],
                feature_engine=StubFeatureEngine(),
                strategy=StubStrategyHold(),
                risk_engine=StubRiskApprove(),
                clock=clock, sleep=clock.sleep,
            )

    def test_side_blocked_by_long_only_profile(self):
        # Perfil long_only: sinal SELL nunca vira would-order.
        class StubStrategySell:
            def evaluate(self, features):
                return StrategySignal.sell(
                    symbol="BTCUSDT", strategy_name="stub",
                    entry_price=100.0, stop_loss_price=101.0,
                    take_profit_price=98.0, position_size_usd=200.0,
                )
        clock = FakeClock()
        profile = resolve_profile(
            "long_only", capital=5000.0, allowed_symbols=("BTCUSDT",),
        )
        outcome = _make_runner(
            clock, profile=profile, strategy=StubStrategySell(),
            limits=derive_endurance_limits(profile),
        ).run()
        assert outcome.would_orders == 0


# ---------------------------------------------------------------------------
# Limites: api failures
# ---------------------------------------------------------------------------

class TestApiFailureLimit:

    def test_consecutive_api_failures_end_session(self):
        clock = FakeClock()
        profile = resolve_profile(
            "personal", capital=5000.0, max_api_failures=2,
        )

        def failing_feed(**kw):
            raise ConnectionError("simulated offline failure")

        outcome = _make_runner(
            clock, profile=profile, market_data=failing_feed,
            limits=derive_endurance_limits(profile),
        ).run()
        assert outcome.ended_reason is EnduranceEndedReason.API_FAILURE
        assert outcome.api_failures == 2


# ---------------------------------------------------------------------------
# Integracao IA (consultiva) + prediction no runner
# ---------------------------------------------------------------------------

class TestRunnerAIIntegration:

    def test_ai_veto_blocks_cycle_no_would_order(self):
        from crypto_trading_bot.ai_assistant import (
            AIDecisionSupport, AIAdviceStatus, MockAIAdvisor,
        )
        clock = FakeClock()
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(forced_status=AIAdviceStatus.VETO),
        )
        outcome = _make_runner(
            clock, profile=profile, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile),
            ai_decision_support=ds,
        ).run()
        # IA vetou TODOS os ciclos -> zero would-orders, sessao completa.
        assert outcome.would_orders == 0
        assert outcome.ended_reason is \
            EnduranceEndedReason.PASSED_ZERO_TRADES

    def test_ai_manual_review_ends_session(self, monkeypatch):
        from crypto_trading_bot.ai_assistant import (
            AIDecisionSupport, AIAdviceStatus, MockAIAdvisor,
        )
        monkeypatch.setenv("DEMO_ALLOW_AI_MANUAL_REVIEW", "true")
        clock = FakeClock()
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(
                forced_status=AIAdviceStatus.MANUAL_REVIEW,
            ),
        )
        outcome = _make_runner(
            clock, profile=profile, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile),
            ai_decision_support=ds,
        ).run()
        assert outcome.ended_reason is \
            EnduranceEndedReason.MANUAL_REVIEW_REQUIRED

    def test_ai_disabled_by_profile_never_called(self):
        from crypto_trading_bot.ai_assistant import (
            AIDecisionSupport, MockAIAdvisor,
        )
        clock = FakeClock()
        profile = resolve_profile("demo_validation", capital=5000.0)
        advisor = MockAIAdvisor()
        ds = AIDecisionSupport(advisor=advisor)
        _make_runner(
            clock, profile=profile, strategy=StubStrategyBuy(),
            limits=derive_endurance_limits(profile),
            ai_decision_support=ds,
        ).run()
        assert advisor.calls == 0

    def test_prediction_requires_profile_and_env_gate(self, monkeypatch):
        from crypto_trading_bot.prediction_markets import (
            build_prediction_context, normalize_raw_events,
        )
        raw = [{
            "market_id": "m1", "title": "Fed rate decision",
            "probability": 0.6, "probability_change_24h": 9.0,
            "volume": 1000000, "category": "fed",
            "btc_relevance_score": 0.9,
        }]
        calls = {"n": 0}

        def provider():
            calls["n"] += 1
            return build_prediction_context(
                events=normalize_raw_events(raw), mode="advisory",
                fetched_at=clock.now,
            )

        # SEM env gate: provider nem eh chamado.
        monkeypatch.delenv(
            "ENABLE_PREDICTION_MARKET_CONTEXT", raising=False,
        )
        clock = FakeClock()
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        _make_runner(
            clock, profile=profile,
            limits=derive_endurance_limits(profile),
            prediction_context_provider=provider,
        ).run()
        assert calls["n"] == 0
        # COM env gate + perfil: provider chamado.
        monkeypatch.setenv("ENABLE_PREDICTION_MARKET_CONTEXT", "true")
        clock2 = FakeClock()
        clock = clock2
        _make_runner(
            clock2, profile=profile,
            limits=derive_endurance_limits(profile),
            prediction_context_provider=provider,
        ).run()
        assert calls["n"] > 0
