"""
Tests - Demo30MinDryRunSimulator (FASE 26 Bloco 6)
======================================================
100% offline. ZERO network. ZERO executor real. ZERO ordem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    Demo30MinDryRunSimulator,
    Demo30MinVerdict,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _make_plan():
    bp = build_default_planned_blueprint(now=NOW)
    return build_demo_30_min_plan(
        symbol="BTCUSDT", strategy_name="trend_pullback",
        max_orders=1, max_session_minutes=30,
        risk_thresholds_snapshot={"max_daily_loss_pct": 0.05},
        planned_blueprint=bp,
        operator_token="OPTOK", now=NOW,
    )


class TestSimulateHappyPath:

    def test_returns_planned_dry_run_ok(self):
        plan = _make_plan()
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK
        assert out.mode == "dry_run_planned"

    def test_orders_submitted_filled_are_zero(self):
        plan = _make_plan()
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.orders_submitted == 0
        assert out.orders_filled == 0

    def test_orders_planned_is_one(self):
        plan = _make_plan()
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.orders_planned == 1

    def test_cycles_completed_matches_minutes(self):
        plan = _make_plan()
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
            virtual_cycle_seconds=60.0,
        )
        out = sim.simulate()
        # 30 min / 60s = 30 cycles
        assert out.cycles_completed == 30

    def test_open_positions_count_is_zero(self):
        plan = _make_plan()
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.open_positions_count == 0


class TestSimulatorIsOffline:

    def test_does_not_import_bybit_client(self):
        # Patch o BybitClient.__init__ para falhar se for chamado.
        import crypto_trading_bot.exchange.bybit_client as bcm
        original = bcm.BybitClient.__init__

        def _fail(*args, **kwargs):
            raise RuntimeError("BybitClient should NOT be instantiated")

        with patch.object(bcm.BybitClient, "__init__", _fail):
            plan = _make_plan()
            sim = Demo30MinDryRunSimulator(
                plan, clock=lambda: NOW, sleep=lambda s: None,
            )
            out = sim.simulate()
            assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK

    def test_does_not_call_execute_demo_session_gated(self):
        import crypto_trading_bot.demo_session_execution.gate as gate_mod
        original = gate_mod.execute_demo_session_gated
        call_count = {"n": 0}

        def _counting(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        with patch.object(
            gate_mod, "execute_demo_session_gated", _counting
        ):
            plan = _make_plan()
            sim = Demo30MinDryRunSimulator(
                plan, clock=lambda: NOW, sleep=lambda s: None,
            )
            out = sim.simulate()
            assert call_count["n"] == 0

    def test_does_not_call_bybit_demo_executor(self):
        import crypto_trading_bot.execution.bybit_demo_executor as exe_mod
        original = exe_mod.BybitDemoExecutor.__init__

        def _fail(*args, **kwargs):
            raise RuntimeError(
                "BybitDemoExecutor should NOT be instantiated in dry-run"
            )

        with patch.object(
            exe_mod.BybitDemoExecutor, "__init__", _fail
        ):
            plan = _make_plan()
            sim = Demo30MinDryRunSimulator(
                plan, clock=lambda: NOW, sleep=lambda s: None,
            )
            out = sim.simulate()
            assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK

    def test_does_not_call_bybit_demo_preflight(self):
        import crypto_trading_bot.execution.bybit_demo_preflight as pf_mod
        original = pf_mod.BybitDemoPreflight.__init__

        def _fail(*args, **kwargs):
            raise RuntimeError(
                "BybitDemoPreflight should NOT be instantiated in dry-run"
            )

        with patch.object(
            pf_mod.BybitDemoPreflight, "__init__", _fail
        ):
            plan = _make_plan()
            sim = Demo30MinDryRunSimulator(
                plan, clock=lambda: NOW, sleep=lambda s: None,
            )
            out = sim.simulate()
            assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK

    def test_simulator_module_no_network_imports(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "dry_run.py"
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
            "BybitDemoPreflight(", "execute_demo_session_gated(",
            "build_demo_api_blueprint(", "load_dotenv",
        ):
            assert tok not in exe, f"forbidden in dry_run.py: {tok}"


class TestSimulatorTypeChecks:

    def test_rejects_non_plan(self):
        with pytest.raises(TypeError):
            Demo30MinDryRunSimulator("not a plan")

    def test_rejects_invalid_virtual_cycle_seconds(self):
        plan = _make_plan()
        with pytest.raises(ValueError):
            Demo30MinDryRunSimulator(
                plan, virtual_cycle_seconds=0,
            )

    def test_sleep_is_injectable(self):
        plan = _make_plan()
        calls = []
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: NOW, sleep=lambda s: calls.append(s),
        )
        sim.simulate()
        # sleep eh chamado por ciclo virtual (default 30 ciclos)
        assert len(calls) == 30
