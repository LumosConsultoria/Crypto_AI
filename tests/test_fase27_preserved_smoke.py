"""
Tests - FASE 28 regression: FASE 27 preserved + ordens nao enviadas
======================================================================
Smoke estrutural garantindo que FASE 27 + FASE 26 + FASE 22 modules
nao foram tocados em codigo executavel e que primeira ordem real
continua bloqueada.
"""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent


def _strip_doc_and_comments(src: str) -> str:
    in_doc = False
    out = []
    for line in src.splitlines():
        s = line.strip()
        if in_doc:
            if s.endswith('"""') or s.endswith("'''"):
                in_doc = False
            continue
        if s.startswith('"""') or s.startswith("'''"):
            if not (s.endswith('"""') and len(s) > 3):
                in_doc = True
            continue
        if s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


class TestFase22ModulesIntact:

    def test_bybit_demo_executor_intact_imports(self):
        from crypto_trading_bot.execution.bybit_demo_executor import (
            BybitDemoExecutor,
        )
        assert BybitDemoExecutor is not None

    def test_bybit_demo_preflight_intact_imports(self):
        from crypto_trading_bot.execution.bybit_demo_preflight import (
            BybitDemoPreflight,
        )
        assert BybitDemoPreflight is not None

    def test_bybit_client_intact_imports(self):
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        assert BybitClient is not None
        assert hasattr(BybitClient, "BASE_URL_DEMO")
        assert BybitClient.BASE_URL_DEMO == "https://api-demo.bybit.com"

    def test_demo_session_execution_intact(self):
        from crypto_trading_bot.demo_session_execution.gate import (
            execute_demo_session_gated, DemoSessionRejected,
        )
        from crypto_trading_bot.demo_session_execution.outcome import (
            RecommendedNextAction,
        )
        assert callable(execute_demo_session_gated)
        assert RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION


class TestFase26ModulesIntact:

    def test_dry_run_simulator_still_works(self):
        from datetime import datetime, timezone
        from crypto_trading_bot.demo_endurance import (
            Demo30MinDryRunSimulator,
            build_default_planned_blueprint,
            build_demo_30_min_plan,
            Demo30MinVerdict,
        )
        now = datetime(2026, 6, 4, tzinfo=timezone.utc)
        bp = build_default_planned_blueprint(now=now)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp, operator_token="OPTOK", now=now,
        )
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: now, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK
        assert out.mode == "dry_run_planned"
        # FASE 27/28 fields default safe
        assert out.apply_demo_real_invoked is False


class TestFase27ModulesIntact:

    def test_live_provider_imports(self):
        from crypto_trading_bot.demo_endurance import (
            LiveDemoBlueprintProvider, LiveDemoBlueprintError,
        )
        assert LiveDemoBlueprintProvider is not None

    def test_prompt_io_imports(self):
        from crypto_trading_bot.demo_endurance import (
            prompt_yes_or_abort, is_tty, TTYRequired, envvar_present,
        )
        assert callable(prompt_yes_or_abort)

    def test_real_runner_imports(self):
        from crypto_trading_bot.demo_endurance import Demo30MinRealRunner
        assert Demo30MinRealRunner is not None


class TestScriptsIntact:

    def test_run_bybit_demo_session_gated_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"
        src = p.read_text(encoding="utf-8")
        assert "from crypto_trading_bot.demo_endurance" not in src
        assert "Demo30MinRealRunner" not in src
        assert "production_wiring" not in src
        assert "SessionTelemetryRecorder" not in src

    def test_run_demo_30_min_planned_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "run_demo_30_min_planned.py"
        src = p.read_text(encoding="utf-8")
        assert "Demo30MinRealRunner" not in src
        assert "LiveDemoBlueprintProvider" not in src
        assert "production_wiring" not in src
        assert "SessionTelemetryRecorder" not in src

    def test_run_challenge_endurance_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "run_challenge_endurance.py"
        src = p.read_text(encoding="utf-8")
        assert "from crypto_trading_bot.demo_endurance" not in src


class TestApplyDemoRealHardDefault:
    """Garantia estrutural: CLI mantem apply_demo_real=False
    hard-coded na branch wired FASE 28."""

    def test_constant_present(self):
        p = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"
        src = p.read_text(encoding="utf-8")
        assert (
            "_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28 = False" in src
        )

    def test_constant_used_in_runner_instantiation(self):
        p = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"
        src = p.read_text(encoding="utf-8")
        # A constante deve ser passada para o runner.
        assert (
            "apply_demo_real=_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28"
            in src
        )


class TestFirstRealOrderRemainsBlocked:
    """Confirma que primeira ordem real continua bloqueada na FASE 28."""

    def test_apply_demo_real_final_is_stub(self):
        p = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"
        src = p.read_text(encoding="utf-8")
        # Stub deve estar presente
        assert "--apply-demo-real-final is a STUB in FASE 28" in src
        assert "FASE 29" in src
