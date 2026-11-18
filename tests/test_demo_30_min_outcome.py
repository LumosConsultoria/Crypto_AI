"""
Tests - Demo30MinOutcome + Demo30MinVerdict (FASE 26 Bloco 5)
================================================================
100% offline. ZERO network. ZERO secret.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    Demo30MinOutcome,
    Demo30MinVerdict,
    DemoEnduranceStage,
    default_recommended_next_action,
)
from crypto_trading_bot.demo_session_execution.outcome import (
    RecommendedNextAction,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _make_outcome(**overrides) -> Demo30MinOutcome:
    base = dict(
        stage=DemoEnduranceStage.DEMO_30_MIN,
        mode="dry_run_planned",
        session_id="DEMO30M-TEST",
        provider_id="bybit_demo_linear",
        environment="demo",
        symbol="BTCUSDT",
        strategy_name="trend_pullback",
        max_session_minutes=30,
        elapsed_minutes=30,
        cycles_completed=30,
        max_orders=1,
        orders_planned=1,
        orders_submitted=0,
        orders_filled=0,
        open_positions_count=0,
        open_orders_count=0,
        conditional_orders_count=0,
        current_position_qty=0.0,
        sl_attached=None,
        tp_attached=None,
        risk_pct_planned=0.01,
        notional_usd_planned=195.0,
        wallet_balance_usd=5000.0,
        safety_state="normal",
        risk_violations_count=0,
        safety_events_count=0,
        manual_review_required=False,
        safety_halt_recommended=False,
        verdict=Demo30MinVerdict.PLANNED_DRY_RUN_OK,
        recommended_next_action=RecommendedNextAction.RETURN_TO_PAPER,
        outcome_reason="dry-run completed",
        started_at=NOW,
        ended_at=NOW,
    )
    base.update(overrides)
    return Demo30MinOutcome(**base)


class TestDemo30MinVerdict:

    def test_all_verdicts_exist(self):
        names = {v.name for v in Demo30MinVerdict}
        assert "PLANNED_DRY_RUN_OK" in names
        assert "PLANNED_DRY_RUN_BLOCKED" in names
        assert "PASSED_ZERO_TRADES" in names
        assert "PASSED_ONE_TRADE" in names
        assert "FAILED" in names
        assert "MANUAL_REVIEW_REQUIRED" in names
        assert "SAFETY_HALT_ACK_NEEDED" in names
        assert "NOT_EXECUTABLE" in names

    def test_default_recommended_for_planned_dry_run_ok(self):
        a = default_recommended_next_action(Demo30MinVerdict.PLANNED_DRY_RUN_OK)
        assert a == RecommendedNextAction.RETURN_TO_PAPER

    def test_default_recommended_for_one_trade(self):
        a = default_recommended_next_action(Demo30MinVerdict.PASSED_ONE_TRADE)
        assert a == RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION

    def test_default_recommended_for_manual_review(self):
        a = default_recommended_next_action(
            Demo30MinVerdict.MANUAL_REVIEW_REQUIRED
        )
        assert a == RecommendedNextAction.MANUAL_REVIEW_REQUIRED

    def test_default_recommended_for_safety_halt(self):
        a = default_recommended_next_action(
            Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED
        )
        assert a == RecommendedNextAction.SAFETY_HALT_ACK_NEEDED

    def test_default_recommended_rejects_invalid(self):
        with pytest.raises(TypeError):
            default_recommended_next_action("not_a_verdict")


class TestOutcomeConsistency:

    def test_dry_run_planned_ok_valid(self):
        out = _make_outcome()
        assert out.is_dry_run is True
        assert out.passed is True

    def test_dry_run_cannot_declare_passed_one_trade(self):
        with pytest.raises(ValueError, match="incompativel"):
            _make_outcome(
                verdict=Demo30MinVerdict.PASSED_ONE_TRADE,
                recommended_next_action=(
                    RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
                ),
            )

    def test_dry_run_cannot_declare_failed(self):
        with pytest.raises(ValueError, match="incompativel"):
            _make_outcome(
                verdict=Demo30MinVerdict.FAILED,
                recommended_next_action=(
                    RecommendedNextAction.MANUAL_REVIEW_REQUIRED
                ),
            )

    def test_planned_dry_run_blocked_is_valid(self):
        out = _make_outcome(
            verdict=Demo30MinVerdict.PLANNED_DRY_RUN_BLOCKED,
            recommended_next_action=RecommendedNextAction.RETURN_TO_PAPER,
            outcome_reason="readiness blocked",
            blockers=("capital must be > 0",),
        )
        assert out.passed is False  # blocked, nao eh passed


class TestOutcomeSerialization:

    def test_to_dict_contains_all_required_fields(self):
        out = _make_outcome()
        d = out.to_dict()
        required = (
            "stage", "mode", "session_id", "provider_id", "environment",
            "symbol", "strategy_name", "max_session_minutes",
            "elapsed_minutes", "cycles_completed", "max_orders",
            "orders_planned", "orders_submitted", "orders_filled",
            "open_positions_count", "open_orders_count",
            "conditional_orders_count", "current_position_qty",
            "sl_attached", "tp_attached", "risk_pct_planned",
            "notional_usd_planned", "wallet_balance_usd",
            "safety_state", "risk_violations_count",
            "safety_events_count", "manual_review_required",
            "safety_halt_recommended", "verdict",
            "recommended_next_action", "outcome_reason", "blockers",
            "warnings", "notes", "started_at", "ended_at", "metadata",
        )
        for f in required:
            assert f in d, f"missing field: {f}"

    def test_to_dict_no_secrets(self):
        out = _make_outcome()
        text = str(out.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text

    def test_notes_truncated_at_200_chars(self):
        long = "x" * 500
        out = _make_outcome(notes=long)
        assert len(out.notes) <= 203  # 200 + "..."
        assert out.notes.endswith("...")
