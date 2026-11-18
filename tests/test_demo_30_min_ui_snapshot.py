"""
Tests - Demo30Min UI snapshot (FASE 26 Bloco 8)
====================================================
100% offline. ZERO secrets em snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    build_demo_30_min_readiness_report,
    Demo30MinDryRunSimulator,
    Demo30MinReadinessConfig,
    Demo30MinVerdict,
    to_ui_snapshot,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _make_plan_and_outcome():
    bp = build_default_planned_blueprint(now=NOW)
    plan = build_demo_30_min_plan(
        symbol="BTCUSDT", strategy_name="trend_pullback",
        max_orders=1, max_session_minutes=30,
        risk_thresholds_snapshot={"max_daily_loss_pct": 0.05},
        planned_blueprint=bp,
        operator_token="OPSECRETLONGTOKEN", now=NOW,
    )
    sim = Demo30MinDryRunSimulator(
        plan, clock=lambda: NOW, sleep=lambda s: None,
    )
    out = sim.simulate()
    return plan, out, bp


class TestSnapshotStructure:

    def test_has_all_required_blocks(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        required_blocks = (
            "stage_info", "readiness", "plan", "session",
            "risk_health", "safety", "verdict", "audit",
        )
        for b in required_blocks:
            assert b in snap, f"missing block: {b}"

    def test_stage_info_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        si = snap["stage_info"]
        for f in ("stage", "mode", "provider", "environment",
                  "endpoint_type", "symbol", "strategy_name",
                  "session_id", "schema_version"):
            assert f in si

    def test_plan_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        p = snap["plan"]
        for f in ("max_session_minutes", "max_orders",
                  "max_open_positions",
                  "blueprint_ttl_seconds_remaining",
                  "planned_signal_blueprint"):
            assert f in p
        pb = p["planned_signal_blueprint"]
        for f in ("side", "entry_price", "stop_loss",
                  "take_profit", "qty", "notional_usd"):
            assert f in pb

    def test_session_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        s = snap["session"]
        for f in ("elapsed_minutes", "cycles_completed",
                  "orders_planned", "orders_submitted", "orders_filled",
                  "open_positions_count", "open_orders_count",
                  "conditional_orders_count", "current_position_qty",
                  "sl_attached", "tp_attached"):
            assert f in s

    def test_risk_health_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        rh = snap["risk_health"]
        for f in ("risk_pct_planned", "notional_usd_planned",
                  "wallet_balance_usd", "equity_usd",
                  "risk_violations_count"):
            assert f in rh

    def test_safety_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        sa = snap["safety"]
        for f in ("safety_state", "safety_events_count",
                  "manual_review_required", "safety_halt_recommended"):
            assert f in sa

    def test_verdict_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        v = snap["verdict"]
        for f in ("verdict", "recommended_next_action", "next_stage",
                  "outcome_reason"):
            assert f in v

    def test_audit_fields(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        a = snap["audit"]
        for f in ("operator_token_sanitized", "last_check_at",
                  "data_freshness_seconds", "evaluated_at"):
            assert f in a


class TestSnapshotSecurity:

    def test_no_secrets_in_snapshot(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        text = str(snap).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text

    def test_operator_token_full_never_appears(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        # plan foi criado com 'OPSECRETLONGTOKEN'
        assert "OPSECRETLONGTOKEN" not in str(snap)
        # apenas 8 primeiros + '...'
        assert snap["audit"]["operator_token_sanitized"].endswith("...")


class TestSnapshotIncludesReadiness:

    def test_readiness_block_filled_when_provided(self):
        plan, out, bp = _make_plan_and_outcome()
        cfg = Demo30MinReadinessConfig(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            capital_usd=5000.0, max_orders=1, max_session_minutes=30,
            max_trades_per_day=10, operator_token="OPTOK",
            planned_blueprint=bp,
        )
        r = build_demo_30_min_readiness_report(cfg, now=NOW)
        snap = to_ui_snapshot(
            plan=plan, outcome=out, readiness=r, last_check_at=NOW,
        )
        assert snap["readiness"]["status"] == "ready"
        assert isinstance(snap["readiness"]["blockers"], list)

    def test_readiness_block_default_when_absent(self):
        plan, out, _ = _make_plan_and_outcome()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        # Sem readiness fornecido, bloco eh default ready/vazio.
        assert snap["readiness"]["status"] == "ready"
        assert snap["readiness"]["blockers"] == []
