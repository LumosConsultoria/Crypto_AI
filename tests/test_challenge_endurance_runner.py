"""
Tests - ChallengeEnduranceRunner + ChallengeEnduranceResult (FASE 23)
===========================================================================
100% offline. ZERO network. ZERO secrets. ZERO order.

Covers endurance orchestrator: DEMO_* nao executavel, readiness gate,
paper SessionRunner via runner_factory fake, veredito passed/failed,
to_ui_snapshot.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.challenge_readiness import (
    ChallengeEnduranceResult,
    ChallengeEnduranceRunner,
    ChallengeEnduranceStage,
    ChallengeReadinessConfig,
    EnduranceReadinessRejected,
    StageNotExecutableInThisPhase,
)
from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import build_personal_profile


def _cfg(symbol="BTCUSDT", stage=None, target=None):
    return ChallengeReadinessConfig(
        target_stage=stage or ChallengeEnduranceStage.PAPER_30_MIN,
        symbol=symbol,
        challenge_target_usd=target,
    )


def _fake_session_result(
    *,
    cycles=10, trades_opened=2, trades_closed=2,
    pnl=0.0, dd=0.0, safety="normal", stopped="max_cycles",
    blocks_by_risk=0, blocks_by_safety=0,
):
    return SimpleNamespace(
        total_cycles_completed=cycles,
        trades_opened=trades_opened,
        trades_closed=trades_closed,
        pnl_paper=pnl,
        drawdown_paper=dd,
        consecutive_losses_final=0,
        blocks_by_safety=blocks_by_safety,
        blocks_by_profile=0,
        blocks_by_risk=blocks_by_risk,
        final_safety_state=safety,
        stopped_reason=SimpleNamespace(value=stopped),
    )


def _runner_factory(session_result):
    """Returns a factory that produces an object with .run() -> session_result."""
    def _factory(**kw):
        runner = MagicMock()
        runner.run.return_value = session_result
        return runner
    return _factory


# ---------------------------------------------------------------------------
# Stage enforcement
# ---------------------------------------------------------------------------

class TestStageEnforcement:

    def test_demo_planned_stage_rejected(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        rc = RiskConfig()
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=_cfg(
                stage=ChallengeEnduranceStage.DEMO_30_MIN_PLANNED,
            ),
        )
        with pytest.raises(StageNotExecutableInThisPhase):
            runner.run()

    def test_paper_30_min_runs(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        rc = RiskConfig()
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=_cfg(),
            runner_factory=_runner_factory(_fake_session_result()),
        )
        result = runner.run()
        assert isinstance(result, ChallengeEnduranceResult)
        assert result.stage == ChallengeEnduranceStage.PAPER_30_MIN


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

class TestVerdictLogic:

    def _runner(self, sr, *, profile=None, cfg=None):
        prof = profile or build_personal_profile(account_size_usd=5000.0)
        return ChallengeEnduranceRunner(
            profile=prof, risk_config=RiskConfig(),
            readiness_config=cfg or _cfg(),
            runner_factory=_runner_factory(sr),
        )

    def test_clean_paper_passes(self):
        sr = _fake_session_result(
            cycles=30, trades_opened=3, trades_closed=3, pnl=10.0,
        )
        result = self._runner(sr).run()
        assert result.passed is True
        assert result.verdict == "passed"
        assert not result.blockers
        assert result.next_recommended_stage == \
            ChallengeEnduranceStage.PAPER_60_MIN

    def test_residual_open_position_fails(self):
        sr = _fake_session_result(trades_opened=3, trades_closed=2)
        result = self._runner(sr).run()
        assert result.verdict == "failed"
        assert result.open_positions_end == 1
        assert any("residual" in b for b in result.blockers)

    def test_safety_halt_fails(self):
        sr = _fake_session_result(safety="safety_halt_active")
        result = self._runner(sr).run()
        assert result.verdict == "failed"
        assert any("safety_state" in b for b in result.blockers)

    def test_max_trades_per_day_exceeded_fails(self):
        # default RiskConfig.max_trades_per_day = 10; force 15 trades.
        sr = _fake_session_result(
            trades_opened=15, trades_closed=15,
        )
        result = self._runner(sr).run()
        assert result.verdict == "failed"
        assert any("max_trades_per_day" in b for b in result.blockers)

    def test_daily_loss_exceeded_fails(self):
        # account_size=5000, max_daily_loss_pct default = 0.05 -> 250 USD.
        sr = _fake_session_result(pnl=-500.0)
        result = self._runner(sr).run()
        assert result.verdict == "failed"
        assert any("max_daily_loss_pct" in b for b in result.blockers)

    def test_drawdown_exceeded_fails(self):
        sr = _fake_session_result(dd=-1000.0)  # default max_total = 0.10 -> 500
        result = self._runner(sr).run()
        assert result.verdict == "failed"
        assert any("max_total_loss_pct" in b for b in result.blockers)


# ---------------------------------------------------------------------------
# Readiness gate
# ---------------------------------------------------------------------------

class TestReadinessGate:

    def test_not_ready_aborts(self):
        prof = build_personal_profile(
            account_size_usd=5000.0,
            allowed_symbols=("ETHUSDT",),
        )
        rc = RiskConfig()
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=_cfg(symbol="BTCUSDT"),
            runner_factory=_runner_factory(_fake_session_result()),
        )
        with pytest.raises(EnduranceReadinessRejected):
            runner.run()


# ---------------------------------------------------------------------------
# ChallengeEnduranceResult shape + to_ui_snapshot
# ---------------------------------------------------------------------------

class TestResultShape:

    def _build(self, **overrides):
        prof = build_personal_profile(account_size_usd=5000.0)
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=RiskConfig(),
            readiness_config=_cfg(target=400.0),
            runner_factory=_runner_factory(_fake_session_result(pnl=100.0)),
        )
        return runner.run()

    def test_frozen(self):
        r = self._build()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.verdict = "failed"  # type: ignore[misc]

    def test_to_dict_json_serializable(self):
        r = self._build()
        json.dumps(r.to_dict())

    def test_to_ui_snapshot_keys(self):
        r = self._build()
        snap = r.to_ui_snapshot()
        for k in ("stage_info", "execution", "risk_health",
                  "safety", "verdict", "kpi", "timing"):
            assert k in snap
        assert snap["kpi"]["is_kpi_only"] is True

    def test_target_kpi_computed(self):
        r = self._build()
        # 100 pnl / 400 target * 100 = 25%
        assert r.challenge_target_progress_pct == pytest.approx(25.0)

    def test_target_kpi_none_when_no_target(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=RiskConfig(),
            readiness_config=_cfg(),
            runner_factory=_runner_factory(_fake_session_result(pnl=100.0)),
        )
        r = runner.run()
        assert r.challenge_target_progress_pct is None


# ---------------------------------------------------------------------------
# Result serialization safety
# ---------------------------------------------------------------------------

class TestResultNoSecrets:

    def test_result_serialization_no_secrets(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=RiskConfig(),
            readiness_config=_cfg(),
            runner_factory=_runner_factory(_fake_session_result()),
        )
        result = runner.run()
        full = json.dumps(result.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full
