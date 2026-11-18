"""
Tests - FASE 25 Bloco 7: E2E signal exercise (paper, deterministic)
======================================================================
100% offline. ZERO network. ZERO secrets. ZERO order externa.

Garante que com feed sintetico + trend_pullback:
    - trades_opened >= 1
    - trades_closed == trades_opened
    - open_positions_end == 0
    - RiskEngine respeitado (risk_violations_count == 0)
    - safety_events_count == 0
    - final_safety_state == normal
    - feed_type / signal_exercise corretos no result + ui_snapshot

NAO exige PnL positivo. NAO eh evidencia de performance.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.challenge_readiness import (
    ChallengeEnduranceRunner, ChallengeReadinessConfig,
    ChallengeEnduranceStage,
)
from crypto_trading_bot.challenge_readiness.strategy_factory import (
    build_strategy_spec,
)
from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.paper_feed import build_synthetic_trend_pullback_feed
from crypto_trading_bot.session_runner import (
    SessionRunner, SessionRunnerConfig,
)


@pytest.fixture
def trend_pullback_feed():
    """Fixture com pullback explicito para gerar BUY em trend_pullback."""
    return build_synthetic_trend_pullback_feed(
        symbol="BTCUSDT", timeframe="15",
        base_price=65000.0,
        n_uptrend_warmup=80, n_pullback=8, n_continuation=30,
    )


def _build_clock_sleep():
    """clock/sleep injetaveis para deterministico (sem time.sleep real)."""
    return (
        lambda: datetime(2024, 1, 1, tzinfo=timezone.utc),
        lambda s: None,
    )


class TestSignalExerciseSessionRunner:
    """E2E direto no SessionRunner (sem ChallengeEnduranceRunner)."""

    def test_opens_and_closes_at_least_one_trade(self, trend_pullback_feed):
        prof = build_personal_profile(account_size_usd=5000.0)
        spec = build_strategy_spec("trend_pullback")
        clock, sleep = _build_clock_sleep()
        cfg = SessionRunnerConfig(
            profile=prof, spec=spec, capital=5000.0,
            symbol="BTCUSDT", timeframe="15",
            max_cycles=trend_pullback_feed.n_candles - 60,
            cycle_interval_seconds=0.0,
            feed_adapter=trend_pullback_feed,
            signal_exercise=True,
            clock=clock, sleep=sleep,
        )
        runner = SessionRunner(cfg)
        res = runner.run()
        assert res.trades_opened >= 1, (
            f"signal exercise nao gerou trade: opened={res.trades_opened}"
        )
        assert res.trades_closed >= 1
        # Sem residual
        assert res.trades_opened == res.trades_closed
        assert res.final_safety_state == "normal"

    def test_legacy_mode_unchanged_no_trades(self):
        """Sem feed_adapter e sem signal_exercise: comportamento legado.

        Determinismo: o MockExchange (random walk default) usa o modulo
        `random` GLOBAL; sem seed, a ordem de coleta dos testes alterava
        o estado do RNG e raramente abria um trade que nao fechava em 30
        ciclos (trades_opened != trades_closed). Fixamos a seed e
        restauramos o estado para isolar o teste (test-only; nao toca o
        MockExchange nem producao).
        """
        import random
        _rng_state = random.getstate()
        random.seed(20240101)
        try:
            prof = build_personal_profile(account_size_usd=5000.0)
            spec = build_strategy_spec("trend_pullback")
            clock, sleep = _build_clock_sleep()
            cfg = SessionRunnerConfig(
                profile=prof, spec=spec, capital=5000.0,
                symbol="BTCUSDT", timeframe="15",
                max_cycles=30,
                cycle_interval_seconds=0.0,
                clock=clock, sleep=sleep,
            )
            runner = SessionRunner(cfg)
            res = runner.run()
            # Random walk + trend_pullback conservadora = 0 trades
            # esperado (igual a PAPER_30_MIN aprovado da FASE 24).
            assert res.final_safety_state == "normal"
            assert res.trades_opened == res.trades_closed  # sem residual
        finally:
            random.setstate(_rng_state)


class TestSignalExerciseChallengeRunner:
    """E2E completo via ChallengeEnduranceRunner."""

    def test_e2e_paper_30_min_signal_exercise(self, trend_pullback_feed):
        prof = build_personal_profile(account_size_usd=5000.0)
        spec = build_strategy_spec("trend_pullback")
        rc = RiskConfig()
        clock, sleep = _build_clock_sleep()
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="BTCUSDT",
            ),
            strategy_spec=spec,
            feed_adapter=trend_pullback_feed,
            signal_exercise=True,
            clock=clock, sleep=sleep,
            cycle_interval_seconds=0.0,
            virtual_cycle_seconds=60.0,
        )
        result = runner.run()
        # Trades exercitados
        assert result.trades_opened >= 1
        assert result.trades_closed >= 1
        assert result.open_positions_end == 0
        # RiskEngine respeitado
        assert result.risk_violations_count == 0
        # Safety limpo
        assert result.safety_events_count == 0
        assert result.final_safety_state == "normal"
        # Identificacao do feed
        assert result.feed_type == "synthetic_trending"
        assert result.signal_exercise is True
        # Mode operacional
        assert result.mode == "operational_paper_run"
        assert result.strategy_name == "trend_pullback_default"

    def test_ui_snapshot_includes_feed_type_and_signal_exercise(
            self, trend_pullback_feed):
        prof = build_personal_profile(account_size_usd=5000.0)
        spec = build_strategy_spec("trend_pullback")
        rc = RiskConfig()
        clock, sleep = _build_clock_sleep()
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="BTCUSDT",
            ),
            strategy_spec=spec,
            feed_adapter=trend_pullback_feed,
            signal_exercise=True,
            clock=clock, sleep=sleep,
        )
        result = runner.run()
        snap = result.to_ui_snapshot()
        assert snap["stage_info"]["feed_type"] == "synthetic_trending"
        assert snap["stage_info"]["signal_exercise"] is True
        assert "feed_source_description" in snap["stage_info"]
        # Execution mostra open_positions_end
        assert snap["execution"]["open_positions_end"] == 0


class TestCrossValidationRejected:

    def test_signal_exercise_true_without_feed_rejected(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        spec = build_strategy_spec("trend_pullback")
        rc = RiskConfig()
        with pytest.raises(ValueError, match="signal_exercise=True"):
            ChallengeEnduranceRunner(
                profile=prof, risk_config=rc,
                readiness_config=ChallengeReadinessConfig(
                    target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                    symbol="BTCUSDT",
                ),
                strategy_spec=spec,
                feed_adapter=None,
                signal_exercise=True,
            )

    def test_nonlegacy_feed_without_signal_exercise_rejected(
            self, trend_pullback_feed):
        prof = build_personal_profile(account_size_usd=5000.0)
        spec = build_strategy_spec("trend_pullback")
        rc = RiskConfig()
        with pytest.raises(ValueError, match="signal_exercise"):
            ChallengeEnduranceRunner(
                profile=prof, risk_config=rc,
                readiness_config=ChallengeReadinessConfig(
                    target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                    symbol="BTCUSDT",
                ),
                strategy_spec=spec,
                feed_adapter=trend_pullback_feed,
                signal_exercise=False,
            )


class TestResultValidations:

    def test_signal_exercise_incompatible_with_mock_random_walk(self):
        from crypto_trading_bot.challenge_readiness.result import (
            ChallengeEnduranceResult,
        )
        # Tentativa de criar result invalido
        with pytest.raises(ValueError, match="signal_exercise"):
            ChallengeEnduranceResult(
                stage=ChallengeEnduranceStage.PAPER_30_MIN,
                profile_name="x", account_size_usd=5000.0,
                symbol="BTCUSDT", duration_planned_minutes=30,
                cycles_completed=0, trades_opened=0, trades_closed=0,
                open_positions_end=0, pnl_realized=0.0,
                pnl_unrealized=0.0, max_drawdown_observed=0.0,
                max_daily_loss_observed=0.0,
                risk_violations_count=0, safety_events_count=0,
                blockers=(), warnings=(),
                verdict="not_executable", next_recommended_stage=None,
                mode="preview_no_strategy",
                feed_type="mock_random_walk",
                signal_exercise=True,  # invalido
            )

    def test_invalid_feed_type_rejected(self):
        from crypto_trading_bot.challenge_readiness.result import (
            ChallengeEnduranceResult,
        )
        with pytest.raises(ValueError, match="feed_type"):
            ChallengeEnduranceResult(
                stage=ChallengeEnduranceStage.PAPER_30_MIN,
                profile_name="x", account_size_usd=5000.0,
                symbol="BTCUSDT", duration_planned_minutes=30,
                cycles_completed=0, trades_opened=0, trades_closed=0,
                open_positions_end=0, pnl_realized=0.0,
                pnl_unrealized=0.0, max_drawdown_observed=0.0,
                max_daily_loss_observed=0.0,
                risk_violations_count=0, safety_events_count=0,
                blockers=(), warnings=(),
                verdict="not_executable", next_recommended_stage=None,
                mode="preview_no_strategy",
                feed_type="invalid_feed_xyz",
            )
