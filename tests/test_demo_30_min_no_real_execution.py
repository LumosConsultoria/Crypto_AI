"""
Tests - FASE 26 regression: no real execution path active
================================================================
Garante invariante estrutural: nenhum modulo de demo_endurance
chama BybitClient/BybitDemoExecutor/BybitDemoPreflight/
execute_demo_session_gated/build_demo_api_blueprint em codigo
executavel; nenhum import de httpx/requests; nada de .env.

Tambem garante que FASE 22 modules + challenge_endurance permanecem
intocados (smoke import; nao re-testa logica deles).
"""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_DEMO_ENDURANCE_DIR = (
    _REPO_ROOT / "src" / "crypto_trading_bot" / "demo_endurance"
)


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


_FORBIDDEN_TOKENS = (
    "import httpx", "from httpx",
    "import requests", "from requests",
    "BybitClient(",
    "BybitDemoExecutor(",
    "BybitDemoPreflight(",
    "execute_demo_session_gated(",
    "build_demo_api_blueprint(",
    "load_dotenv",
)


class TestDemoEnduranceModuleHasNoRealExecutionImports:

    def test_all_modules_clean(self):
        py_files = sorted(_DEMO_ENDURANCE_DIR.glob("*.py"))
        assert len(py_files) >= 1
        for f in py_files:
            src = f.read_text(encoding="utf-8")
            exe = _strip_doc_and_comments(src)
            for tok in _FORBIDDEN_TOKENS:
                assert tok not in exe, (
                    f"forbidden token {tok!r} in {f.name}"
                )


class TestCLIHasNoRealExecutionImports:

    def test_cli_clean(self):
        cli = _REPO_ROOT / "scripts" / "run_demo_30_min_planned.py"
        src = cli.read_text(encoding="utf-8")
        exe = _strip_doc_and_comments(src)
        for tok in _FORBIDDEN_TOKENS:
            assert tok not in exe, (
                f"forbidden token {tok!r} in scripts/run_demo_30_min_planned.py"
            )


class TestFase22ModulesUnchangedSmoke:
    """Smoke: imports de FASE 22 nao quebram; estrutura preservada."""

    def test_demo_session_readiness_imports(self):
        from crypto_trading_bot.demo_session_readiness.readiness_check import (
            DemoSessionReadinessCheck,
        )
        assert DemoSessionReadinessCheck is not None

    def test_demo_session_execution_imports(self):
        from crypto_trading_bot.demo_session_execution.outcome import (
            RecommendedNextAction,
        )
        from crypto_trading_bot.demo_session_execution.plan import (
            DemoSessionPlan, SignalBlueprint,
        )
        from crypto_trading_bot.demo_session_execution.api_blueprint import (
            DemoApiBlueprint, build_demo_api_blueprint,
        )
        from crypto_trading_bot.demo_session_execution.gate import (
            execute_demo_session_gated,
        )
        assert RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION

    def test_bybit_demo_executor_imports(self):
        from crypto_trading_bot.execution.bybit_demo_executor import (
            BybitDemoExecutor,
        )
        assert BybitDemoExecutor is not None

    def test_bybit_demo_preflight_imports(self):
        from crypto_trading_bot.execution.bybit_demo_preflight import (
            BybitDemoPreflight,
        )
        assert BybitDemoPreflight is not None


class TestChallengeEnduranceDemoStillPlannedOnly:

    def test_demo_30_min_planned_in_challenge_stages(self):
        from crypto_trading_bot.challenge_readiness.stages import (
            ChallengeEnduranceStage, is_demo_planned_stage,
        )
        assert is_demo_planned_stage(
            ChallengeEnduranceStage.DEMO_30_MIN_PLANNED
        )

    def test_run_challenge_endurance_script_unchanged_shape(self):
        # Smoke: arquivo ainda existe e nao importa demo_endurance.
        p = _REPO_ROOT / "scripts" / "run_challenge_endurance.py"
        assert p.is_file()
        src = p.read_text(encoding="utf-8")
        assert "from crypto_trading_bot.demo_endurance" not in src
        assert "Demo30MinDryRunSimulator" not in src
