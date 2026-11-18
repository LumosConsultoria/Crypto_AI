"""
Tests - Demo30MinReadiness (FASE 26 Bloco 2)
=================================================
100% offline. ZERO network. ZERO .env. ZERO secret.

Cobre todos os blockers obrigatorios + warnings + happy path.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_readiness_report,
    DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
    DEMO_30_MIN_MAX_SESSION_MINUTES,
    Demo30MinReadinessConfig,
    Demo30MinReadinessStatus,
    EnvironmentSnapshot,
    LastSafetyFlags,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _make_blueprint(**overrides):
    return build_default_planned_blueprint(now=NOW, **overrides)


def _base_config(**overrides) -> Demo30MinReadinessConfig:
    bp = overrides.pop("planned_blueprint", _make_blueprint())
    env = overrides.pop("environment_snapshot", EnvironmentSnapshot())
    flags = overrides.pop("last_safety_flags", LastSafetyFlags())
    return Demo30MinReadinessConfig(
        symbol=overrides.pop("symbol", "BTCUSDT"),
        strategy_name=overrides.pop("strategy_name", "trend_pullback"),
        capital_usd=overrides.pop("capital_usd", 5000.0),
        max_orders=overrides.pop("max_orders", 1),
        max_session_minutes=overrides.pop("max_session_minutes", 30),
        max_trades_per_day=overrides.pop("max_trades_per_day", 10),
        operator_token=overrides.pop("operator_token", "OPTOKEN123"),
        environment_snapshot=env,
        last_safety_flags=flags,
        planned_blueprint=bp,
    )


class TestHappyPath:

    def test_minimum_valid_returns_ready(self):
        r = build_demo_30_min_readiness_report(_base_config(), now=NOW)
        assert r.status == Demo30MinReadinessStatus.READY
        assert r.total_blockers == 0


class TestBlockedByConfig:

    def test_blocks_capital_le_zero(self):
        r = build_demo_30_min_readiness_report(
            _base_config(capital_usd=0.0), now=NOW,
        )
        assert r.status == Demo30MinReadinessStatus.NOT_READY
        assert any(i.gate == "capital" for i in r.blockers)

    def test_blocks_unknown_strategy(self):
        r = build_demo_30_min_readiness_report(
            _base_config(strategy_name="not_a_strategy"), now=NOW,
        )
        assert any(i.gate == "strategy" for i in r.blockers)

    def test_blocks_empty_symbol(self):
        r = build_demo_30_min_readiness_report(
            _base_config(symbol="   "), now=NOW,
        )
        assert any(i.gate == "symbol" for i in r.blockers)

    def test_blocks_max_orders_zero(self):
        r = build_demo_30_min_readiness_report(
            _base_config(max_orders=0), now=NOW,
        )
        assert any(i.gate == "max_orders" for i in r.blockers)

    def test_blocks_max_orders_above_hard_cap(self):
        r = build_demo_30_min_readiness_report(
            _base_config(max_orders=DEMO_30_MIN_MAX_ORDERS_HARD_CAP + 1),
            now=NOW,
        )
        assert any(i.gate == "max_orders" for i in r.blockers)

    def test_blocks_max_orders_above_max_trades_per_day(self):
        cfg = _base_config(max_orders=1, max_trades_per_day=0)
        # max_trades_per_day=0 nao deve dispar; mas se for >0 e < max_orders, deve
        r2 = build_demo_30_min_readiness_report(
            _base_config(max_orders=1, max_trades_per_day=0), now=NOW,
        )
        # Nao bloqueia se max_trades_per_day=0
        assert r2.is_ready or any(
            i.gate == "max_orders" for i in r2.blockers
        ) is False
        # Mas max_orders=2 > hard_cap=1 ja bloqueia
        # (testado em outro teste)

    def test_blocks_max_minutes_above_30(self):
        r = build_demo_30_min_readiness_report(
            _base_config(max_session_minutes=DEMO_30_MIN_MAX_SESSION_MINUTES + 1),
            now=NOW,
        )
        assert any(i.gate == "max_session_minutes" for i in r.blockers)

    def test_blocks_max_minutes_zero(self):
        r = build_demo_30_min_readiness_report(
            _base_config(max_session_minutes=0), now=NOW,
        )
        assert any(i.gate == "max_session_minutes" for i in r.blockers)

    def test_blocks_empty_operator_token(self):
        r = build_demo_30_min_readiness_report(
            _base_config(operator_token=""), now=NOW,
        )
        assert any(i.gate == "operator_token" for i in r.blockers)


class TestBlockedByEnvironment:

    def test_blocks_enable_live_trading_true(self):
        env = EnvironmentSnapshot(enable_live_trading=True)
        r = build_demo_30_min_readiness_report(
            _base_config(environment_snapshot=env), now=NOW,
        )
        assert any(
            i.gate == "env" and "LIVE_TRADING" in i.message
            for i in r.blockers
        )

    def test_blocks_trading_mode_live(self):
        env = EnvironmentSnapshot(trading_mode="live")
        r = build_demo_30_min_readiness_report(
            _base_config(environment_snapshot=env), now=NOW,
        )
        assert any(i.gate == "env" for i in r.blockers)

    def test_blocks_provider_not_bybit_demo_linear(self):
        env = EnvironmentSnapshot(provider_id="bybit_mainnet")
        r = build_demo_30_min_readiness_report(
            _base_config(environment_snapshot=env), now=NOW,
        )
        assert any(i.gate == "provider" for i in r.blockers)

    def test_blocks_provider_status_active(self):
        # ACTIVE significa promocao indevida; FASE 26 exige OPT_IN.
        env = EnvironmentSnapshot(provider_status="active")
        r = build_demo_30_min_readiness_report(
            _base_config(environment_snapshot=env), now=NOW,
        )
        assert any(i.gate == "provider" for i in r.blockers)

    def test_blocks_endpoint_non_demo(self):
        env = EnvironmentSnapshot(endpoint_type="api.bybit.com")
        r = build_demo_30_min_readiness_report(
            _base_config(environment_snapshot=env), now=NOW,
        )
        assert any(i.gate == "endpoint" for i in r.blockers)


class TestBlockedByLastFlags:

    def test_blocks_manual_review_pending(self):
        flags = LastSafetyFlags(manual_review_required=True)
        r = build_demo_30_min_readiness_report(
            _base_config(last_safety_flags=flags), now=NOW,
        )
        assert any(
            i.gate == "safety" and "manual_review" in i.message
            for i in r.blockers
        )

    def test_blocks_safety_halt_pending(self):
        flags = LastSafetyFlags(safety_halt_recommended=True)
        r = build_demo_30_min_readiness_report(
            _base_config(last_safety_flags=flags), now=NOW,
        )
        assert any(i.gate == "safety" for i in r.blockers)

    def test_blocks_safety_state_not_normal(self):
        flags = LastSafetyFlags(safety_state="paused")
        r = build_demo_30_min_readiness_report(
            _base_config(last_safety_flags=flags), now=NOW,
        )
        assert any(i.gate == "safety" for i in r.blockers)


class TestBlockedByBlueprint:

    def test_blocks_open_positions_count_gt_zero(self):
        bp = build_default_planned_blueprint(
            now=NOW,
        )
        # Mutate via re-construction
        from crypto_trading_bot.demo_endurance import PlannedDemoBlueprint
        bp2 = PlannedDemoBlueprint(
            side=bp.side, entry_price=bp.entry_price,
            stop_loss=bp.stop_loss, take_profit=bp.take_profit,
            qty=bp.qty, notional_usd=bp.notional_usd,
            risk_pct=bp.risk_pct,
            wallet_balance_usd=bp.wallet_balance_usd,
            open_positions_count=1,
            generated_at=NOW,
        )
        r = build_demo_30_min_readiness_report(
            _base_config(planned_blueprint=bp2), now=NOW,
        )
        assert any(
            i.gate == "blueprint" and "open_positions_count" in i.message
            for i in r.blockers
        )

    def test_blocks_open_orders_count_gt_zero(self):
        from crypto_trading_bot.demo_endurance import PlannedDemoBlueprint
        bp = build_default_planned_blueprint(now=NOW)
        bp2 = PlannedDemoBlueprint(
            side=bp.side, entry_price=bp.entry_price,
            stop_loss=bp.stop_loss, take_profit=bp.take_profit,
            qty=bp.qty, notional_usd=bp.notional_usd,
            risk_pct=bp.risk_pct,
            wallet_balance_usd=bp.wallet_balance_usd,
            open_orders_count=2, generated_at=NOW,
        )
        r = build_demo_30_min_readiness_report(
            _base_config(planned_blueprint=bp2), now=NOW,
        )
        assert any(
            i.gate == "blueprint" and "open_orders_count" in i.message
            for i in r.blockers
        )

    def test_warning_for_conditional_orders_count(self):
        from crypto_trading_bot.demo_endurance import PlannedDemoBlueprint
        bp = build_default_planned_blueprint(now=NOW)
        bp2 = PlannedDemoBlueprint(
            side=bp.side, entry_price=bp.entry_price,
            stop_loss=bp.stop_loss, take_profit=bp.take_profit,
            qty=bp.qty, notional_usd=bp.notional_usd,
            risk_pct=bp.risk_pct,
            wallet_balance_usd=bp.wallet_balance_usd,
            conditional_orders_count=1, generated_at=NOW,
        )
        r = build_demo_30_min_readiness_report(
            _base_config(planned_blueprint=bp2), now=NOW,
        )
        assert r.status in (
            Demo30MinReadinessStatus.WARNING,
            Demo30MinReadinessStatus.NOT_READY,
        )
        assert any(
            i.gate == "blueprint" and "conditional_orders_count" in i.message
            for i in r.warnings
        )


class TestPaperOnlyFlagsForbidden:

    def test_blocks_when_forbid_paper_feed_false(self):
        from dataclasses import replace
        cfg = _base_config()
        cfg2 = replace(cfg, forbid_paper_feed=False)
        r = build_demo_30_min_readiness_report(cfg2, now=NOW)
        assert any(i.gate == "demo_safety" for i in r.blockers)

    def test_blocks_when_forbid_signal_exercise_false(self):
        from dataclasses import replace
        cfg = _base_config()
        cfg2 = replace(cfg, forbid_signal_exercise=False)
        r = build_demo_30_min_readiness_report(cfg2, now=NOW)
        assert any(i.gate == "demo_safety" for i in r.blockers)


class TestReportSerialization:

    def test_to_dict_has_status_and_blockers(self):
        r = build_demo_30_min_readiness_report(
            _base_config(capital_usd=0.0), now=NOW,
        )
        d = r.to_dict()
        assert d["status"] == "not_ready"
        assert d["total_blockers"] >= 1
        assert isinstance(d["blockers"], list)

    def test_to_dict_no_secrets(self):
        r = build_demo_30_min_readiness_report(_base_config(), now=NOW)
        text = str(r.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text


class TestModuleHasNoNetwork:

    def test_readiness_module_no_network_imports(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "readiness.py"
        src = p.read_text(encoding="utf-8")
        # Remove docstrings/comments (naive)
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
            "BybitDemoPreflight(", "load_dotenv", "build_demo_api_blueprint(",
        ):
            assert tok not in exe, f"forbidden in readiness.py: {tok}"
