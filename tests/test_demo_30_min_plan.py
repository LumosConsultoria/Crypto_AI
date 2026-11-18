"""
Tests - Demo30MinPlan + PlannedDemoBlueprint (FASE 26 Bloco 4)
================================================================
100% offline. ZERO network. ZERO secrets. ZERO ordem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
    DEMO_30_MIN_MAX_SESSION_MINUTES,
    DEMO_30_MIN_SCHEMA_VERSION,
    Demo30MinPlan,
    Demo30MinPlanRejected,
    DemoEnduranceStage,
    PlannedDemoBlueprint,
    PlannedDemoBlueprintRejected,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


class TestPlannedDemoBlueprint:

    def test_default_blueprint_valid(self):
        bp = build_default_planned_blueprint(now=NOW)
        assert bp.side == "buy"
        assert bp.entry_price > bp.stop_loss
        assert bp.take_profit > bp.entry_price
        assert bp.schema_version == DEMO_30_MIN_SCHEMA_VERSION

    def test_invariant_buy_stop_lt_entry_lt_tp(self):
        with pytest.raises(PlannedDemoBlueprintRejected):
            PlannedDemoBlueprint(
                side="buy", entry_price=65000.0,
                stop_loss=66000.0,  # invalido: stop > entry
                take_profit=67000.0,
                qty=0.003, notional_usd=195.0, risk_pct=0.01,
                wallet_balance_usd=5000.0,
            )

    def test_invariant_sell_tp_lt_entry_lt_stop(self):
        with pytest.raises(PlannedDemoBlueprintRejected):
            PlannedDemoBlueprint(
                side="sell", entry_price=65000.0,
                stop_loss=66000.0,
                take_profit=66500.0,  # invalido: tp > entry
                qty=0.003, notional_usd=195.0, risk_pct=0.01,
                wallet_balance_usd=5000.0,
            )

    def test_sell_happy_path(self):
        bp = PlannedDemoBlueprint(
            side="sell", entry_price=65000.0,
            stop_loss=65650.0, take_profit=63700.0,
            qty=0.003, notional_usd=195.0, risk_pct=0.01,
            wallet_balance_usd=5000.0,
        )
        assert bp.side == "sell"

    def test_rejects_invalid_side(self):
        with pytest.raises(PlannedDemoBlueprintRejected):
            PlannedDemoBlueprint(
                side="long", entry_price=65000.0, stop_loss=64000.0,
                take_profit=66000.0, qty=0.003, notional_usd=195.0,
                risk_pct=0.01, wallet_balance_usd=5000.0,
            )

    def test_rejects_negative_qty(self):
        with pytest.raises(PlannedDemoBlueprintRejected):
            PlannedDemoBlueprint(
                side="buy", entry_price=65000.0, stop_loss=64000.0,
                take_profit=66000.0, qty=-1.0, notional_usd=195.0,
                risk_pct=0.01, wallet_balance_usd=5000.0,
            )

    def test_rejects_non_demo_endpoint(self):
        with pytest.raises(PlannedDemoBlueprintRejected):
            PlannedDemoBlueprint(
                side="buy", entry_price=65000.0, stop_loss=64000.0,
                take_profit=66000.0, qty=0.003, notional_usd=195.0,
                risk_pct=0.01, wallet_balance_usd=5000.0,
                endpoint_type="api.bybit.com",
            )

    def test_ttl_remaining_decays_to_zero(self):
        bp = build_default_planned_blueprint(now=NOW)
        # No exato momento de generated_at: TTL full
        assert bp.ttl_seconds_remaining(NOW) == bp.ttl_seconds
        # Apos TTL: zero
        later = NOW + timedelta(seconds=bp.ttl_seconds + 1)
        assert bp.ttl_seconds_remaining(later) == 0
        assert bp.is_expired(later) is True

    def test_to_dict_contains_planned_only_warning(self):
        bp = build_default_planned_blueprint(now=NOW)
        d = bp.to_dict()
        assert "_planned_only_warning" in d
        assert "FASE 22" in d["_planned_only_warning"]

    def test_to_dict_no_secrets(self):
        bp = build_default_planned_blueprint(now=NOW)
        text = str(bp.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text


class TestBuildDemo30MinPlan:

    def test_happy_path(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={"max_daily_loss_pct": 0.05},
            planned_blueprint=bp,
            operator_token="OPTOKEN1234567",
            now=NOW,
        )
        assert plan.stage == DemoEnduranceStage.DEMO_30_MIN
        assert plan.mode == "dry_run_planned"
        assert plan.apply_demo_real is False
        assert plan.max_orders == 1
        assert plan.max_session_minutes == 30
        assert plan.schema_version == DEMO_30_MIN_SCHEMA_VERSION

    def test_session_id_sanitized(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
            session_id="abc/def\\xyz",
        )
        # Caracteres especiais sao convertidos para "_"
        assert "/" not in plan.session_id
        assert "\\" not in plan.session_id

    def test_token_always_sanitized_in_to_dict(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="VERYLONGSECRETOPERATORTOKEN12345",
            now=NOW,
        )
        d = plan.to_dict()
        assert "operator_token_sanitized" in d
        assert "VERYLONGSECRET" not in str(d)
        # Apenas primeiros 8 + ...
        assert d["operator_token_sanitized"].endswith("...")

    def test_to_dict_no_secrets(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={"max_daily_loss_pct": 0.05},
            planned_blueprint=bp,
            operator_token="OPTOKEN", now=NOW,
        )
        text = str(plan.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text

    def test_apply_demo_real_cannot_be_true(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
        )
        # Tentar forcar apply_demo_real=True via __init__ direto
        from dataclasses import replace
        with pytest.raises(ValueError, match="apply_demo_real"):
            replace(plan, apply_demo_real=True)


class TestBuildDemo30MinPlanRejects:

    def test_max_orders_zero_rejected(self):
        bp = build_default_planned_blueprint(now=NOW)
        with pytest.raises(Demo30MinPlanRejected):
            build_demo_30_min_plan(
                symbol="BTCUSDT", strategy_name="trend_pullback",
                max_orders=0, max_session_minutes=30,
                risk_thresholds_snapshot={},
                planned_blueprint=bp,
                operator_token="OPTOK", now=NOW,
            )

    def test_max_orders_above_hard_cap_rejected(self):
        bp = build_default_planned_blueprint(now=NOW)
        with pytest.raises(Demo30MinPlanRejected):
            build_demo_30_min_plan(
                symbol="BTCUSDT", strategy_name="trend_pullback",
                max_orders=DEMO_30_MIN_MAX_ORDERS_HARD_CAP + 1,
                max_session_minutes=30,
                risk_thresholds_snapshot={},
                planned_blueprint=bp,
                operator_token="OPTOK", now=NOW,
            )

    def test_max_minutes_above_30_rejected(self):
        bp = build_default_planned_blueprint(now=NOW)
        with pytest.raises(Demo30MinPlanRejected):
            build_demo_30_min_plan(
                symbol="BTCUSDT", strategy_name="trend_pullback",
                max_orders=1,
                max_session_minutes=DEMO_30_MIN_MAX_SESSION_MINUTES + 1,
                risk_thresholds_snapshot={},
                planned_blueprint=bp,
                operator_token="OPTOK", now=NOW,
            )

    def test_empty_operator_token_rejected(self):
        bp = build_default_planned_blueprint(now=NOW)
        with pytest.raises(Demo30MinPlanRejected):
            build_demo_30_min_plan(
                symbol="BTCUSDT", strategy_name="trend_pullback",
                max_orders=1, max_session_minutes=30,
                risk_thresholds_snapshot={},
                planned_blueprint=bp,
                operator_token="", now=NOW,
            )


class TestModuleHasNoNetwork:

    def test_plan_module_no_network_imports(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "plan.py"
        src = p.read_text(encoding="utf-8")
        in_doc = False
        out = []
        for line in src.splitlines():
            s = line.strip()
            if in_doc:
                if s.endswith('"""'):
                    in_doc = False
                continue
            if s.startswith('"""'):
                if not (s.endswith('"""') and len(s) > 3):
                    in_doc = True
                continue
            if s.startswith("#"):
                continue
            out.append(line)
        exe = "\n".join(out)
        for tok in (
            "import httpx", "from httpx", "import requests",
            "from requests", "BybitClient(", "BybitDemoExecutor(",
            "BybitDemoPreflight(", "load_dotenv",
            "build_demo_api_blueprint(",
        ):
            assert tok not in exe, f"forbidden in plan.py: {tok}"
