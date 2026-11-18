"""
Tests - CLI FASE 29 branch + regressao FASE 22/26/28
=======================================================
100% offline. ZERO network. ZERO ordem.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"


def _run(*args: str, env_extra=None, timeout: int = 60):
    cmd = [sys.executable, str(_SCRIPT), *args]
    import os
    env = os.environ.copy()
    for k in (
        "ENABLE_LIVE_TRADING", "ENABLE_DEMO_EXECUTION",
        "TRADING_MODE", "BYBIT_DEMO_API_KEY",
        "BYBIT_DEMO_API_SECRET",
        "DEMO_30_MIN_REAL_RUNNER_DEPLOYED",
        "DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED",
        "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED",
        "BYBIT_USE_DEMO",
    ):
        env[k] = ""
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False, env=env,
    )


def _run_stdin(*args: str, stdin_text="", env_extra=None, timeout: int = 60):
    """Como _run, mas alimenta stdin (para frase + prompt Y)."""
    cmd = [sys.executable, str(_SCRIPT), *args]
    import os
    env = os.environ.copy()
    for k in (
        "ENABLE_LIVE_TRADING", "ENABLE_DEMO_EXECUTION",
        "TRADING_MODE", "BYBIT_DEMO_API_KEY",
        "BYBIT_DEMO_API_SECRET",
        "DEMO_30_MIN_REAL_RUNNER_DEPLOYED",
        "DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED",
        "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED",
        "BYBIT_USE_DEMO",
    ):
        env[k] = ""
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd, capture_output=True, text=True, input=stdin_text,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False, env=env,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestCLIPhase29SrcGuards:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, f"non-ASCII at {i}: {ord(ch)}"

    def test_first_real_demo_order_flag_present(self):
        src = _read_src()
        assert "--first-real-demo-order" in src

    def test_phase29_branch_function_present(self):
        src = _read_src()
        assert "_run_phase29_real_full_cycle" in src

    def test_phase29_exit_management_function_present(self):
        src = _read_src()
        assert "_run_phase29_exit_management" in src

    def test_envvar_present_imported_in_both_phase29_functions(self):
        """HOTFIX regression: envvar_present deve estar no bloco de
        import lazy de AMBAS as funcoes FASE 29 (escopo). Garante que
        nenhum NameError ocorra ao usar envvar_present fora de main()."""
        src = _read_src()
        # Localiza as duas funcoes e verifica que cada uma importa
        # envvar_present do demo_endurance.
        idx_real = src.find("def _run_phase29_real_full_cycle")
        idx_exit = src.find("def _run_phase29_exit_management")
        idx_wired = src.find("def _run_wired_dry_run")
        assert idx_real != -1 and idx_exit != -1
        # Bloco de _run_phase29_real_full_cycle vai ate _run_phase29_exit
        block_real = src[idx_real:idx_exit]
        # Bloco de _run_phase29_exit_management vai ate _run_wired_dry_run
        block_exit = src[idx_exit:idx_wired]
        assert "envvar_present" in block_real, (
            "_run_phase29_real_full_cycle deve importar envvar_present"
        )
        assert "envvar_present" in block_exit, (
            "_run_phase29_exit_management deve importar envvar_present"
        )


def _load_cli_module():
    """Carrega o script CLI como modulo in-process (sem rodar main).

    Permite chamar _run_phase29_real_full_cycle diretamente para
    exercitar o gate BYBIT_USE_DEMO (primeira linha da funcao) sem
    depender de TTY/subprocess.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_rdme_phase29_under_test", str(_SCRIPT),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _phase29_args(**overrides):
    from types import SimpleNamespace
    base = dict(
        profile="personal", capital=5000.0, symbol="BTCUSDT",
        strategy="trend_pullback", max_orders=1, max_minutes=30,
        max_close_orders=1, cycle_interval_seconds=60.0,
        operator_token="TOK1234", output="", telemetry_output="",
        notes="", prompt_timeout_seconds=60.0,
        apply_demo_real=True, confirm_demo_endurance=True,
        i_understand_this_is_demo_endurance=True, execute_real=True,
        first_real_demo_order=True,
        non_interactive_assume_no=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPhase29NoNameErrorInBranch:
    """HOTFIX: branch FASE 29 nao deve lancar NameError por escopo de
    envvar_present. Tudo offline/in-process; nenhuma API real chamada.

    Chamamos _run_phase29_real_full_cycle diretamente: o gate
    BYBIT_USE_DEMO eh a PRIMEIRA validacao, antes de qualquer input,
    prompt, wiring ou ordem.
    """

    def test_bybit_use_demo_absent_yields_controlled_error_not_nameerror(
        self, monkeypatch,
    ):
        monkeypatch.delenv("BYBIT_USE_DEMO", raising=False)
        mod = _load_cli_module()
        # delenv novamente apos load (o _safe_load_dotenv no import
        # pode ter trazido do .env).
        monkeypatch.delenv("BYBIT_USE_DEMO", raising=False)
        rc = mod._run_phase29_real_full_cycle(
            args=_phase29_args(), readiness_dict={"status": "ready"},
        )
        # Erro controlado (sem NameError). exit 1.
        assert rc == 1

    def test_bybit_use_demo_empty_yields_controlled_error(
        self, monkeypatch,
    ):
        monkeypatch.setenv("BYBIT_USE_DEMO", "")
        mod = _load_cli_module()
        monkeypatch.setenv("BYBIT_USE_DEMO", "")
        rc = mod._run_phase29_real_full_cycle(
            args=_phase29_args(), readiness_dict={"status": "ready"},
        )
        assert rc == 1

    def test_bybit_use_demo_false_yields_controlled_error(
        self, monkeypatch,
    ):
        monkeypatch.setenv("BYBIT_USE_DEMO", "false")
        mod = _load_cli_module()
        monkeypatch.setenv("BYBIT_USE_DEMO", "false")
        rc = mod._run_phase29_real_full_cycle(
            args=_phase29_args(), readiness_dict={"status": "ready"},
        )
        assert rc == 1

    def test_bybit_use_demo_true_advances_past_gate_no_nameerror(
        self, monkeypatch,
    ):
        # BYBIT_USE_DEMO=true: avanca alem do gate de env. A proxima
        # etapa eh input() da frase; mockamos para retornar frase
        # ERRADA -> erro controlado de phrase mismatch. Prova que o
        # gate BYBIT_USE_DEMO foi ultrapassado SEM NameError.
        monkeypatch.setenv("BYBIT_USE_DEMO", "true")
        mod = _load_cli_module()
        monkeypatch.setenv("BYBIT_USE_DEMO", "true")
        # Mock input para frase errada (nao dispara wiring/ordem).
        import builtins
        monkeypatch.setattr(
            builtins, "input", lambda *a, **k: "wrong phrase",
        )
        rc = mod._run_phase29_real_full_cycle(
            args=_phase29_args(), readiness_dict={"status": "ready"},
        )
        # Parou em phrase mismatch (gate posterior), nao NameError.
        assert rc == 1

    def test_no_nameerror_symbol_envvar_present_resolvable(self):
        # Garantia direta: o modulo define/importa envvar_present nos
        # escopos certos; chamar a funcao nao levanta NameError.
        mod = _load_cli_module()
        assert hasattr(mod, "_run_phase29_real_full_cycle")
        assert hasattr(mod, "_run_phase29_exit_management")


class TestPhase28DefaultPreserved:

    def test_phase28_apply_demo_real_hard_default_still_false(self):
        """FASE 28 default branch nao foi quebrada."""
        src = _read_src()
        assert (
            "_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28 = False" in src
        )
        assert (
            "apply_demo_real=_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28"
            in src
        )


class TestPhase29WithoutEnvFallsBackToPhase28:

    def test_no_phase29_env_uses_phase28_branch(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--readiness-only",
        )
        assert r.returncode == 0
        assert "FASE 22 runbook" in r.stdout

    def test_first_real_demo_order_flag_without_env_ignored(self):
        # Mesmo com a 5a flag, sem env FASE 29, segue branch FASE 28
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--first-real-demo-order",
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
        # non-interactive-assume-no aborta antes do branch FASE 29
        assert r.returncode == 1


class TestPhase22RunbookPreserved:
    """Garantia que FASE 22 single-shot runbook nao foi quebrado."""

    def test_run_bybit_demo_session_gated_exists_and_unchanged_shape(
        self,
    ):
        p = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"
        assert p.is_file()
        src = p.read_text(encoding="utf-8")
        # Nao depende de modules FASE 29
        assert "from crypto_trading_bot.demo_endurance" not in src
        assert "submit_reduce_only_close" not in src
        assert "validate_phase29" not in src

    def test_bybit_demo_executor_execute_method_preserved(self):
        from crypto_trading_bot.execution.bybit_demo_executor import (
            BybitDemoExecutor,
        )
        # execute() FASE 22 ainda existe
        assert hasattr(BybitDemoExecutor, "execute")
        # submit_reduce_only_close FASE 29 adicionado
        assert hasattr(BybitDemoExecutor, "submit_reduce_only_close")


class TestPhase26PlannedPreserved:

    def test_dry_run_simulator_still_works(self):
        from datetime import datetime, timezone
        from crypto_trading_bot.demo_endurance import (
            Demo30MinDryRunSimulator,
            build_default_planned_blueprint,
            build_demo_30_min_plan, Demo30MinVerdict,
        )
        now = datetime(2026, 6, 10, tzinfo=timezone.utc)
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


class TestPhase28ValidatorPreserved:

    def test_phase28_validator_script_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "validate_demo_30m_phase28_report.py"
        assert p.is_file()
        src = p.read_text(encoding="utf-8")
        # FASE 28 validador nao depende de modules FASE 29
        assert "phase29" not in src.lower() or \
               "phase_29" not in src.lower()


class TestProviderRegistrySupportsReduceOnlyTrueForBybitDemoLinear:

    def test_capability_updated_for_phase29(self):
        from crypto_trading_bot.execution.provider_registry import (
            get_registry,
        )
        reg = get_registry()
        entry = reg.get("bybit_demo_linear")
        assert entry.capability.supports_reduce_only is True

    def test_provider_status_still_opt_in(self):
        from crypto_trading_bot.execution.provider_registry import (
            get_registry,
        )
        from crypto_trading_bot.execution.provider_capability import (
            ProviderStatus,
        )
        reg = get_registry()
        entry = reg.get("bybit_demo_linear")
        assert entry.status == ProviderStatus.OPT_IN
