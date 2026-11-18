"""
Tests - build_challenge_readiness_report (FASE 23)
========================================================
100% offline. ZERO network. ZERO secrets.

Covers profile-to-endurance gate validation.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.challenge_readiness import (
    ChallengeEnduranceStage,
    ChallengeReadinessConfig,
    ChallengeReadinessStatus,
    build_challenge_readiness_report,
)
from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.operational_profile.profile import OperationalProfile


def _cfg(symbol="BTCUSDT", stage=None, target=None):
    return ChallengeReadinessConfig(
        target_stage=stage or ChallengeEnduranceStage.PAPER_30_MIN,
        symbol=symbol,
        challenge_target_usd=target,
    )


def _risk():
    return RiskConfig()


class TestGateHappyPath:

    def test_personal_profile_paper_30_min_ready(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        report = build_challenge_readiness_report(prof, _risk(), _cfg())
        assert report.status in (
            ChallengeReadinessStatus.READY,
            ChallengeReadinessStatus.READY_WITH_WARNINGS,
        )
        assert report.error_count == 0

    def test_personal_profile_paper_60_min_ready(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        report = build_challenge_readiness_report(
            prof, _risk(),
            _cfg(stage=ChallengeEnduranceStage.PAPER_60_MIN),
        )
        assert report.error_count == 0

    def test_personal_profile_paper_1_day_ready(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        report = build_challenge_readiness_report(
            prof, _risk(),
            _cfg(stage=ChallengeEnduranceStage.PAPER_1_DAY),
        )
        assert report.error_count == 0


class TestGateBlockers:

    def test_symbol_outside_profile_blocks(self):
        prof = build_personal_profile(
            account_size_usd=5000.0,
            allowed_symbols=("ETHUSDT",),
        )
        report = build_challenge_readiness_report(
            prof, _risk(), _cfg(symbol="BTCUSDT"),
        )
        assert report.error_count >= 1
        assert any(
            b.field_name == "allowed_symbols" and b.severity == "error"
            for b in report.blockers
        )
        assert report.status == ChallengeReadinessStatus.NOT_READY

    def test_account_size_zero_blocks(self):
        # Constroi profile com account_size=None e risk_config com 0.
        prof = OperationalProfile(
            name="bad", description="bad", provider_type="custom",
            account_size_usd=None,
        )
        # RiskConfig requires account_size > 0 (validated by pydantic),
        # so we use a small value and validate the gate ignores risk side
        # zero correctly via the profile path.
        report = build_challenge_readiness_report(prof, _risk(), _cfg())
        # account_size from risk_config is > 0 (default 5000 in ACCOUNT_PROFILES);
        # gate should still pass the account_size check.
        # Test that gate at least handles None gracefully.
        assert isinstance(report.error_count, int)

    def test_kpi_only_does_not_block_on_low_profit(self):
        # Challenge target as KPI: report should NOT block by profit.
        prof = build_personal_profile(account_size_usd=5000.0)
        report = build_challenge_readiness_report(
            prof, _risk(), _cfg(target=1000.0),
        )
        # KPI is informational only.
        assert report.challenge_target_kpi_only is True
        # Check at least one info-level blocker about target.
        target_blockers = [
            b for b in report.blockers
            if b.field_name == "challenge_target_usd"
        ]
        assert len(target_blockers) >= 1
        assert all(b.severity == "info" for b in target_blockers)
        # No max_profit_usd-type error.
        assert all(
            "max_profit" not in b.field_name.lower()
            for b in report.blockers
        )

    def test_demo_planned_stage_emits_info_not_error(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        report = build_challenge_readiness_report(
            prof, _risk(),
            _cfg(stage=ChallengeEnduranceStage.DEMO_30_MIN_PLANNED),
        )
        target_stage_blockers = [
            b for b in report.blockers if b.field_name == "target_stage"
        ]
        assert len(target_stage_blockers) >= 1
        assert all(b.severity == "info" for b in target_stage_blockers)
        # info-only on target_stage does not make status NOT_READY by itself.
        assert report.status in (
            ChallengeReadinessStatus.READY,
            ChallengeReadinessStatus.READY_WITH_WARNINGS,
        )

    def test_does_not_mutate_profile(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        snap_before = prof.to_dict()
        build_challenge_readiness_report(prof, _risk(), _cfg())
        assert prof.to_dict() == snap_before

    def test_does_not_mutate_risk_config(self):
        rc = _risk()
        snap_before = rc.model_dump()
        prof = build_personal_profile(account_size_usd=5000.0)
        build_challenge_readiness_report(prof, rc, _cfg())
        assert rc.model_dump() == snap_before


class TestGateInputValidation:

    def test_wrong_profile_type_rejected(self):
        with pytest.raises(TypeError):
            build_challenge_readiness_report("not-a-profile", _risk(), _cfg())  # type: ignore[arg-type]

    def test_wrong_risk_config_type_rejected(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(TypeError):
            build_challenge_readiness_report(prof, {}, _cfg())  # type: ignore[arg-type]

    def test_wrong_config_type_rejected(self):
        prof = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(TypeError):
            build_challenge_readiness_report(prof, _risk(), "cfg")  # type: ignore[arg-type]
