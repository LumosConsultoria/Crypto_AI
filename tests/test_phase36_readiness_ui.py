"""
Tests - FASE 36 Blocos F/G: readiness verdicts novos + UI snapshots
====================================================================
100% offline. Readiness continua consultivo (nunca autoriza).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.readiness import (
    ReadinessEvidence,
    ReadinessVerdict,
    evaluate_supervised_readiness,
)
from crypto_trading_bot.ui_contracts import (
    build_decision_trace_snapshot,
    build_operator_dashboard_snapshot,
    build_position_management_snapshot,
    build_readiness_snapshot,
    build_session_snapshot,
)

_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


def _good_evidence(**kw):
    base = dict(
        total_sessions=3, short_demo_clean_count=1,
        short_demo_completed_count=2, long_demo_completed_count=1,
    )
    base.update(kw)
    return ReadinessEvidence(**base)


class TestNewReadinessVerdicts:

    def test_blocked_missing_operator_input_takes_precedence(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
            operator_inputs_blocking=True,
            operator_inputs_missing=7,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_MISSING_OPERATOR_INPUT
        assert any("operator inputs" in b for b in report.blockers)

    def test_blocked_missing_credentials(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
            demo_credentials_present=False,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_MISSING_CREDENTIALS

    def test_blocked_unresolved_position(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(), unresolved_position=True,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_UNRESOLVED_POSITION

    def test_blocked_unresolved_risk_policy(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(), risk_policy_unresolved=True,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_UNRESOLVED_RISK_POLICY

    def test_blocked_stale_data(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(), stale_data_detected=True,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_STALE_DATA

    def test_precedence_order(self):
        # inputs > credentials > position > risk policy > stale.
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
            operator_inputs_blocking=True,
            demo_credentials_present=False,
            unresolved_position=True,
            stale_data_detected=True,
        )
        assert report.verdict is \
            ReadinessVerdict.BLOCKED_MISSING_OPERATOR_INPUT

    def test_fase35_behavior_preserved_without_new_args(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
        )
        assert report.verdict is ReadinessVerdict.READY

    def test_decision_trace_unavailable_warning(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
            decision_trace_available=False,
        )
        assert report.verdict is ReadinessVerdict.READY
        assert "decision_trace_unavailable" in report.warnings

    def test_readiness_never_authorizes(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
        )
        assert "NAO habilita" in report.to_dict()["note"]


class TestUISnapshots:

    def _outcome_dict(self):
        return {
            "session_id": "s1", "symbol": "BTCUSDT",
            "strategy_name": "trend_pullback_bidirectional",
            "execution_mode": "wired_dry_run",
            "real_time_mode": True, "ended_reason": "passed_zero_trades",
            "cycles_completed": 5, "expected_cycles": 30,
            "signals_evaluated": 5, "would_orders": 0,
            "orders_submitted": 0, "trades_completed": 0,
            "total_realized_pnl": None,
            "final_flat_check_passed": None,
            "warnings": [],
            "session_summary": {
                "ai_enabled": False,
                "ai_not_used_reason": "ai_disabled_by_profile",
                "prediction_market_context": {"enabled": False},
            },
        }

    def test_session_snapshot_fields(self):
        from crypto_trading_bot.operational_profile import (
            resolve_profile,
        )
        snap = build_session_snapshot(
            outcome=self._outcome_dict(),
            profile=resolve_profile("personal", capital=5000.0),
        )
        for key in (
            "session_id", "provider", "environment", "profile",
            "strategy", "status", "execution_mode",
            "ai_enabled", "ai_not_used_reason",
            "prediction_market_context", "warnings",
        ):
            assert key in snap, key
        assert snap["schema"] == "session_snapshot_v1"

    def test_decision_trace_snapshot_with_narrative(self):
        traces = [{
            "trace_id": "trace-x", "cycle_idx": 1,
            "timestamp": _NOW.isoformat(), "session_id": "s",
            "final_decision": "hold", "final_reason": "no_uptrend",
            "strategy_name": "tp", "symbol": "BTCUSDT",
            "indicators": {}, "gates_approved": [],
            "gates_blocked": [], "mi_sources_used": [],
            "mi_sources_stale": [], "mi_sources_unavailable": [],
            "mi_risk_flags": [],
        }]
        snap = build_decision_trace_snapshot(traces=traces)
        assert snap["total_traces"] == 1
        assert snap["recent_human"]
        assert "Ciclo 1" in snap["recent_human"][0]

    def test_position_mgmt_snapshot_defaults_safe(self):
        snap = build_position_management_snapshot()
        assert snap["scale_in_enabled"] is False
        assert snap["scale_in_allowed_this_phase"] is False
        assert snap["auto_reversal_allowed"] is False
        assert snap["reversal_policy"] == "blocked"

    def test_dashboard_snapshot_allowed_vs_blocked(self):
        from crypto_trading_bot.operational_options import (
            OperationalOptionsRegistry,
        )
        from crypto_trading_bot.operational_profile import (
            resolve_profile,
        )
        dash = build_operator_dashboard_snapshot(
            session=build_session_snapshot(
                outcome=self._outcome_dict(),
                profile=resolve_profile("personal", capital=5000.0),
            ),
            decision_traces=[],
            readiness={"verdict": "not_ready", "blockers": ["x"],
                       "warnings": [], "reports_scanned": 0,
                       "note": "n"},
            options_registry=OperationalOptionsRegistry(),
            now=_NOW,
        )
        assert dash["schema"] == "operator_dashboard_snapshot_v1"
        assert dash["options_total"] >= 30
        blocked_ids = {
            a["option_id"] for a in dash["blocked_actions"]
        }
        # Perigosas aparecem BLOQUEADAS com motivo explicito.
        assert "scale_in" in blocked_ids
        assert "live_mainnet" in blocked_ids
        scale_row = next(
            a for a in dash["blocked_actions"]
            if a["option_id"] == "scale_in"
        )
        assert scale_row["blocked_reason"]
        # Disponiveis default aparecem permitidas.
        allowed_ids = {
            a["option_id"] for a in dash["allowed_actions"]
        }
        assert "paper_trading" in allowed_ids

    def test_readiness_snapshot(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(),
            operator_inputs_blocking=True,
        )
        snap = build_readiness_snapshot(
            readiness_report=report.to_dict(),
        )
        assert snap["verdict"] == "blocked_missing_operator_input"
        assert snap["blockers"]
