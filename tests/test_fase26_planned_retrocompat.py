"""
Tests - FASE 27 retrocompat com FASE 26 dry-run planned
============================================================
Garante que aditivos opcionais em Demo30MinPlan/Demo30MinOutcome/
ui_snapshot nao quebram o caminho FASE 26 (dry-run planned).
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    Demo30MinDryRunSimulator,
    Demo30MinPlan,
    Demo30MinVerdict,
    to_ui_snapshot,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


class TestPlanRetrocompat:

    def test_plan_without_live_blueprint_id_works(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
        )
        assert plan.live_blueprint_id is None
        # to_dict deve incluir o campo (sempre)
        d = plan.to_dict()
        assert "live_blueprint_id" in d
        assert d["live_blueprint_id"] is None

    def test_plan_with_live_blueprint_id_works(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
            live_blueprint_id="BP-ABCDEF123456",
        )
        assert plan.live_blueprint_id == "BP-ABCDEF123456"


class TestDryRunPlannedStillProducesOk:

    def test_dry_run_planned_ok_via_simulator(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
        )
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK
        assert out.mode == "dry_run_planned"
        # FASE 27 - apply_demo_real_invoked default False
        assert out.apply_demo_real_invoked is False


class TestUiSnapshotRetrocompat:

    def test_ui_snapshot_works_without_fase27_fields(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
        )
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        # Blocos antigos preservados
        for k in ("stage_info", "plan", "session", "risk_health",
                  "safety", "verdict", "audit", "readiness"):
            assert k in snap
        # Campos FASE 27 opcionais devem existir mas com valores seguros.
        assert snap["stage_info"]["mode"] == "dry_run_planned"
        assert snap["stage_info"]["real_vs_dry_run"] == "dry_run"
        assert snap["verdict"]["apply_demo_real_invoked"] is False
        assert snap["audit"]["live_blueprint_id"] is None

    def test_ui_snapshot_real_endurance_marks_real(self):
        # Constroi outcome com mode="real_endurance" para validar
        from crypto_trading_bot.demo_endurance.outcome import (
            Demo30MinOutcome,
        )
        from crypto_trading_bot.demo_endurance.stage import (
            DemoEnduranceStage,
        )
        from crypto_trading_bot.demo_session_execution.outcome import (
            RecommendedNextAction,
        )
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
            live_blueprint_id="BP-XYZ",
        )
        out = Demo30MinOutcome(
            stage=DemoEnduranceStage.DEMO_30_MIN,
            mode="real_endurance",
            session_id=plan.session_id,
            provider_id=plan.provider_id, environment=plan.environment,
            symbol=plan.symbol, strategy_name=plan.strategy_name,
            max_session_minutes=30, elapsed_minutes=30,
            cycles_completed=30,
            max_orders=1, orders_planned=1, orders_submitted=0,
            orders_filled=0, open_positions_count=0,
            open_orders_count=0, conditional_orders_count=0,
            current_position_qty=0.0,
            sl_attached=None, tp_attached=None,
            risk_pct_planned=0.01, notional_usd_planned=195.0,
            wallet_balance_usd=5000.0,
            safety_state="normal", risk_violations_count=0,
            safety_events_count=0, manual_review_required=False,
            safety_halt_recommended=False,
            verdict=Demo30MinVerdict.PASSED_ZERO_TRADES,
            recommended_next_action=RecommendedNextAction.RETURN_TO_PAPER,
            outcome_reason="no signal",
            started_at=NOW, ended_at=NOW,
            live_blueprint_id="BP-XYZ",
            apply_demo_real_invoked=True,
        )
        snap = to_ui_snapshot(plan=plan, outcome=out, last_check_at=NOW)
        assert snap["stage_info"]["mode"] == "real_endurance"
        assert snap["stage_info"]["real_vs_dry_run"] == "real"
        assert snap["verdict"]["apply_demo_real_invoked"] is True
        assert snap["audit"]["live_blueprint_id"] == "BP-XYZ"
