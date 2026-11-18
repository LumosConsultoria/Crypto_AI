"""
Tests - Challenge Readiness types (FASE 23)
=================================================
100% offline. ZERO network. ZERO secrets.

Covers ChallengeEnduranceStage, ChallengeReadinessConfig,
ChallengeReadinessBlocker, ChallengeReadinessReport, stage definitions.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.challenge_readiness import (
    STAGE_ORDER,
    ChallengeEnduranceStage,
    ChallengeReadinessBlocker,
    ChallengeReadinessConfig,
    ChallengeReadinessReport,
    ChallengeReadinessStatus,
    get_stage_definition,
    is_demo_planned_stage,
    is_paper_stage,
    next_recommended_stage,
)


# ---------------------------------------------------------------------------
# ChallengeEnduranceStage
# ---------------------------------------------------------------------------

class TestStages:

    def test_six_stages_defined(self):
        assert len(list(ChallengeEnduranceStage)) == 6

    def test_stage_values_stable(self):
        assert ChallengeEnduranceStage.PAPER_30_MIN.value == "paper_30_min"
        assert ChallengeEnduranceStage.PAPER_60_MIN.value == "paper_60_min"
        assert ChallengeEnduranceStage.PAPER_1_DAY.value == "paper_1_day"
        assert ChallengeEnduranceStage.DEMO_30_MIN_PLANNED.value == \
            "demo_30_min_planned"

    def test_stage_order_chronological(self):
        assert STAGE_ORDER[0] == ChallengeEnduranceStage.PAPER_30_MIN
        assert STAGE_ORDER[-1] == ChallengeEnduranceStage.DEMO_1_DAY_PLANNED

    def test_paper_stages_have_paper_provider(self):
        for stage in (
            ChallengeEnduranceStage.PAPER_30_MIN,
            ChallengeEnduranceStage.PAPER_60_MIN,
            ChallengeEnduranceStage.PAPER_1_DAY,
        ):
            sd = get_stage_definition(stage)
            assert sd.provider_allowed == "paper"
            assert sd.mode_allowed == "paper"
            assert sd.can_call_external_api is False
            assert sd.can_send_external_order is False
            assert is_paper_stage(stage) is True
            assert is_demo_planned_stage(stage) is False

    def test_demo_stages_are_planned_only(self):
        for stage in (
            ChallengeEnduranceStage.DEMO_30_MIN_PLANNED,
            ChallengeEnduranceStage.DEMO_60_MIN_PLANNED,
            ChallengeEnduranceStage.DEMO_1_DAY_PLANNED,
        ):
            sd = get_stage_definition(stage)
            assert sd.mode_allowed == "demo_planned"
            # PLANNED-ONLY: no external API/order in this phase.
            assert sd.can_call_external_api is False
            assert sd.can_send_external_order is False
            assert is_demo_planned_stage(stage) is True
            assert is_paper_stage(stage) is False

    def test_paper_60_requires_paper_30(self):
        sd = get_stage_definition(ChallengeEnduranceStage.PAPER_60_MIN)
        assert sd.required_previous_stage == \
            ChallengeEnduranceStage.PAPER_30_MIN

    def test_paper_1_day_requires_paper_60(self):
        sd = get_stage_definition(ChallengeEnduranceStage.PAPER_1_DAY)
        assert sd.required_previous_stage == \
            ChallengeEnduranceStage.PAPER_60_MIN

    def test_demo_30_requires_paper_1_day(self):
        sd = get_stage_definition(
            ChallengeEnduranceStage.DEMO_30_MIN_PLANNED,
        )
        assert sd.required_previous_stage == \
            ChallengeEnduranceStage.PAPER_1_DAY

    def test_next_recommended_paper_30_is_60(self):
        nxt = next_recommended_stage(ChallengeEnduranceStage.PAPER_30_MIN)
        assert nxt == ChallengeEnduranceStage.PAPER_60_MIN

    def test_next_recommended_demo_1_day_is_none(self):
        assert next_recommended_stage(
            ChallengeEnduranceStage.DEMO_1_DAY_PLANNED,
        ) is None

    def test_duration_minutes_correct(self):
        assert get_stage_definition(
            ChallengeEnduranceStage.PAPER_30_MIN,
        ).duration_minutes == 30
        assert get_stage_definition(
            ChallengeEnduranceStage.PAPER_60_MIN,
        ).duration_minutes == 60
        assert get_stage_definition(
            ChallengeEnduranceStage.PAPER_1_DAY,
        ).duration_minutes == 1440


# ---------------------------------------------------------------------------
# ChallengeReadinessConfig
# ---------------------------------------------------------------------------

class TestReadinessConfig:

    def test_minimal_config_accepted(self):
        cfg = ChallengeReadinessConfig(
            target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
            symbol="BTCUSDT",
        )
        assert cfg.target_stage == ChallengeEnduranceStage.PAPER_30_MIN
        assert cfg.challenge_target_usd is None
        assert cfg.drawdown_to_daily_ratio_min == 1.0

    def test_frozen(self):
        cfg = ChallengeReadinessConfig(
            target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
            symbol="BTCUSDT",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.symbol = "ETHUSDT"  # type: ignore[misc]

    def test_empty_symbol_rejected(self):
        with pytest.raises(ValueError):
            ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="",
            )

    def test_invalid_target_stage_rejected(self):
        with pytest.raises(TypeError):
            ChallengeReadinessConfig(
                target_stage="paper_30_min",  # type: ignore[arg-type]
                symbol="BTCUSDT",
            )

    def test_negative_ratio_rejected(self):
        with pytest.raises(ValueError):
            ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="BTCUSDT",
                drawdown_to_daily_ratio_min=-1.0,
            )

    def test_challenge_target_usd_accepted(self):
        # KPI only: any numeric value accepted (no range validation).
        cfg = ChallengeReadinessConfig(
            target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
            symbol="BTCUSDT",
            challenge_target_usd=400.0,
        )
        assert cfg.challenge_target_usd == 400.0


# ---------------------------------------------------------------------------
# ChallengeReadinessBlocker
# ---------------------------------------------------------------------------

class TestReadinessBlocker:

    def test_valid_severity(self):
        for sev in ("error", "warning", "info"):
            b = ChallengeReadinessBlocker("x", sev, "msg")
            assert b.severity == sev

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValueError):
            ChallengeReadinessBlocker("x", "critical", "msg")

    def test_empty_message_rejected(self):
        with pytest.raises(ValueError):
            ChallengeReadinessBlocker("x", "error", "  ")

    def test_is_blocking(self):
        assert ChallengeReadinessBlocker("x", "error", "m").is_blocking
        assert not ChallengeReadinessBlocker("x", "warning", "m").is_blocking
        assert not ChallengeReadinessBlocker("x", "info", "m").is_blocking

    def test_to_dict_serializable(self):
        b = ChallengeReadinessBlocker("foo", "error", "bar")
        json.dumps(b.to_dict())


# ---------------------------------------------------------------------------
# ChallengeReadinessReport
# ---------------------------------------------------------------------------

class TestReadinessReport:

    def _make(self, status, blockers=()):
        cfg = ChallengeReadinessConfig(
            target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
            symbol="BTCUSDT",
        )
        return ChallengeReadinessReport(
            config=cfg,
            profile_name="p",
            target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
            status=status,
            blockers=tuple(blockers),
            snapshot={"k": "v"},
            challenge_target_kpi_only=True,
        )

    def test_ready_no_blockers(self):
        r = self._make(ChallengeReadinessStatus.READY)
        assert r.is_ready is True
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_not_ready_requires_error_blocker(self):
        with pytest.raises(ValueError):
            self._make(ChallengeReadinessStatus.NOT_READY, blockers=())

    def test_ready_with_error_rejected(self):
        # READY with warning should fail consistency check.
        with pytest.raises(ValueError):
            self._make(
                ChallengeReadinessStatus.READY,
                blockers=(ChallengeReadinessBlocker("x", "warning", "m"),),
            )

    def test_to_dict_json_serializable(self):
        r = self._make(ChallengeReadinessStatus.READY)
        json.dumps(r.to_dict())

    def test_to_ui_snapshot_subset(self):
        r = self._make(ChallengeReadinessStatus.READY)
        snap = r.to_ui_snapshot()
        assert "summary" in snap
        assert "counts" in snap
        assert "blockers" in snap
        assert "snapshot_metrics" in snap
        assert "kpi" in snap
        assert snap["kpi"]["challenge_target_kpi_only"] is True
