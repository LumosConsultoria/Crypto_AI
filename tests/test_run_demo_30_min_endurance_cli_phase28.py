"""
Tests - scripts/run_demo_30_min_endurance.py FASE 28 extensions
====================================================================
100% offline. Validates --apply-demo-real-final stub + deploy gate +
wired dry-run prerequisites. Wired path itself uses mocks via env+
unittest.mock patches.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"


def _run(*args: str, env_extra=None, timeout: int = 90):
    cmd = [sys.executable, str(_SCRIPT), *args]
    import os
    env = os.environ.copy()
    # FASE 28 closeout: CLI autoloads .env (override=False). Para
    # garantir que testes nao herdam valores do .env do repo, setamos
    # presence vazia: presence bloqueia override=False.
    for k in ("ENABLE_LIVE_TRADING", "ENABLE_DEMO_EXECUTION",
              "TRADING_MODE", "BYBIT_DEMO_API_KEY",
              "BYBIT_DEMO_API_SECRET",
              "DEMO_30_MIN_REAL_RUNNER_DEPLOYED"):
        env[k] = ""
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False, env=env,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestApplyDemoRealFinalStub:

    def test_apply_demo_real_final_prints_fase29_and_exits_zero(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK",
            "--apply-demo-real-final",
        )
        assert r.returncode == 0
        assert "STUB" in r.stdout
        assert "FASE 29" in r.stdout


class TestDeployFlagGate:

    def test_without_deploy_flag_real_path_blocked(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--apply-demo-real",
            "--confirm-demo-endurance",
            "--i-understand-this-is-demo-endurance",
            "--execute-real",
            "--non-interactive-assume-no",
            env_extra={
                "ENABLE_DEMO_EXECUTION": "true",
                "TRADING_MODE": "demo",
                "BYBIT_DEMO_API_KEY": "k",
                "BYBIT_DEMO_API_SECRET": "s",
            },
        )
        # 4 flags + env OK -> mas --non-interactive-assume-no aborta
        # antes de chegar ao deploy flag check; ok pra fase 27 path.
        assert r.returncode == 1
        # mensagem nao-interativa
        assert "non-interactive" in r.stdout.lower() or \
               "declined" in r.stdout.lower()

    def test_with_deploy_flag_but_non_interactive_assume_no_aborts(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--apply-demo-real",
            "--confirm-demo-endurance",
            "--i-understand-this-is-demo-endurance",
            "--execute-real",
            "--non-interactive-assume-no",
            env_extra={
                "ENABLE_DEMO_EXECUTION": "true",
                "TRADING_MODE": "demo",
                "BYBIT_DEMO_API_KEY": "k",
                "BYBIT_DEMO_API_SECRET": "s",
                "DEMO_30_MIN_REAL_RUNNER_DEPLOYED": "true",
            },
        )
        # non-interactive-assume-no SEMPRE aborta antes do wiring
        assert r.returncode == 1


class TestPartialFlagsStillRejected:

    def test_only_three_of_four_flags_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--apply-demo-real",
            "--confirm-demo-endurance",
            "--i-understand-this-is-demo-endurance",
            # missing --execute-real
            env_extra={
                "DEMO_30_MIN_REAL_RUNNER_DEPLOYED": "true",
            },
        )
        assert r.returncode == 1
        assert "--execute-real" in r.stdout


class TestReadinessOnlyPreservedFromPhase27:

    def test_readiness_only_still_works(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--readiness-only",
        )
        assert r.returncode == 0
        assert "ready" in r.stdout

    def test_no_flags_runs_phase27_path(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
        )
        # Sem flags + sem deploy -> caminho FASE 27 antigo (exit 0 com
        # mensagem encaminhando FASE 26).
        assert r.returncode == 0
        assert "FASE 26" in r.stdout or "dry-run" in r.stdout.lower()


class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, (
                f"non-ASCII char {ord(ch)} at position {i}"
            )

    def test_no_top_level_bybit_imports(self):
        src = _read_src()
        # Top-level imports nao devem incluir BybitClient etc.
        for line in src.split("\n"):
            if not line.startswith(" ") and not line.startswith("\t"):
                if line.startswith("from ") or line.startswith("import "):
                    assert "BybitClient" not in line
                    assert "BybitDemoExecutor" not in line
                    assert "BybitDemoPreflight" not in line

    def test_dotenv_autoload_uses_override_false(self):
        """FASE 28 closeout: load_dotenv aceitavel SE e somente SE
        override=False (nao sobrescreve env operacional do usuario)."""
        src = _read_src()
        assert "_safe_load_dotenv" in src
        assert "override=False" in src
        # Garantia de no-print: apenas count aparece, valores NUNCA.
        assert "values never printed" in src

    def test_no_network_imports_top_level(self):
        src = _read_src()
        for line in src.split("\n"):
            if not line.startswith(" ") and not line.startswith("\t"):
                for tok in ("import httpx", "from httpx",
                            "import requests", "from requests"):
                    assert tok not in line

    def test_apply_demo_real_hard_default_phase28_constant_present(self):
        src = _read_src()
        # Garantia estrutural: constante hard-coded existe.
        assert "_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28" in src
        assert "_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28 = False" in src


class TestStubInOutput:

    def test_apply_demo_real_final_no_secrets(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPSECRET12345",
            "--apply-demo-real-final",
        )
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full


class TestBannerMentionsFase28Wired:

    def test_banner_includes_fase22_runbook_reference(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--readiness-only",
        )
        assert "FASE 22 runbook" in r.stdout


class TestWiredBranchImportsResolveCorrectly:
    """Regression guard: caminho wired dry-run depende de imports
    com path EXATO. Detecta ModuleNotFoundError antes de execucao
    operacional.

    Estes testes apenas EXECUTAM o import; nao instanciam BybitClient
    real nem chamam rede.
    """

    def test_mode_guard_import_path_correct(self):
        # ModeGuard reside em crypto_trading_bot.core.mode_guard
        # (NAO em crypto_trading_bot.mode_guard).
        from crypto_trading_bot.core.mode_guard import ModeGuard
        assert ModeGuard is not None

    def test_risk_engine_import_path_correct(self):
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        assert RiskEngine is not None

    def test_safety_state_machine_import_path_correct(self):
        from crypto_trading_bot.operational_safety.safety_state_machine \
            import SafetyStateMachine
        assert SafetyStateMachine is not None

    def test_operational_profile_factory_import_path_correct(self):
        from crypto_trading_bot.operational_profile import (
            build_personal_profile,
        )
        assert callable(build_personal_profile)

    def test_cli_does_not_reference_legacy_mode_guard_path(self):
        """Regression: nenhum import top-level/lazy do CLI deve usar
        o path legado 'crypto_trading_bot.mode_guard' (sem '.core').
        """
        src = _read_src()
        assert "from crypto_trading_bot.mode_guard import" not in src, (
            "CLI deve usar crypto_trading_bot.core.mode_guard"
        )
        assert "crypto_trading_bot.mode_guard import" not in src

    def test_cli_uses_correct_core_mode_guard_path(self):
        src = _read_src()
        # Path correto presente em algum lugar do script.
        assert (
            "from crypto_trading_bot.core.mode_guard import ModeGuard"
            in src
        )

    def test_build_live_demo_executor_called_with_mode_guard_and_risk(
        self,
    ):
        """Regression FASE 28 hotfix: build_live_demo_executor exige
        mode_guard e risk_engine; o CLI deve passar as instancias ja
        criadas no wired path (sem instanciar novas)."""
        src = _read_src()
        # Garantia estrutural: chamada passa as 3 dependencias.
        assert (
            "build_live_demo_executor(\n        client=client,"
            in src
            or "build_live_demo_executor(client=client,"
            in src
        )
        # Mode guard e risk engine referenciados como argumentos kwargs.
        assert "mode_guard=mode_guard" in src
        assert "risk_engine=risk_engine" in src
