"""
Tests - scripts/run_demo_30_min_planned.py (FASE 26 Bloco 7)
================================================================
100% offline. ZERO network. ZERO secret. ZERO ordem.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_30_min_planned.py"


def _run(*args: str, timeout: int = 60):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, f"non-ASCII char at {i}"

    def test_no_bybit_client_import(self):
        src = _read_src()
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    def test_no_demo_executor_or_preflight_import(self):
        src = _read_src()
        assert "BybitDemoExecutor" not in src
        assert "BybitDemoPreflight" not in src

    def test_no_build_demo_api_blueprint_import(self):
        src = _read_src()
        assert "build_demo_api_blueprint" not in src
        assert "execute_demo_session_gated" not in src

    def test_no_network_imports(self):
        src = _read_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_no_dotenv_load(self):
        src = _read_src()
        assert "load_dotenv" not in src


class TestApplyDemoRealStub:

    def test_apply_demo_real_prints_stub_and_exits_zero(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
            "--apply-demo-real",
        )
        assert r.returncode == 0
        assert "STUB" in r.stdout
        assert "FASE 27" in r.stdout
        assert "FASE 22 runbook" in r.stdout

    def test_apply_demo_real_does_not_print_planned_dry_run_complete(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
            "--apply-demo-real",
        )
        assert r.returncode == 0
        assert "PLANNED DRY-RUN COMPLETE" not in r.stdout


class TestArgparseRequired:

    def test_cli_without_capital_rejected(self):
        r = _run(
            "--profile", "personal",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
        )
        assert r.returncode != 0
        assert "--capital" in (r.stdout + r.stderr)

    def test_cli_without_operator_token_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
        )
        assert r.returncode != 0
        assert "--operator-token" in (r.stdout + r.stderr)

    def test_cli_with_negative_capital_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "0",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
        )
        assert r.returncode == 1
        assert "must be > 0" in r.stdout


class TestPromptAndDryRun:

    def test_yes_flag_runs_dry_run_and_exits_zero(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK1234",
            "--yes",
        )
        assert r.returncode == 0
        assert "PLANNED DRY-RUN COMPLETE" in r.stdout
        assert "planned_dry_run_ok" in r.stdout

    def test_dry_run_prints_no_real_order_message(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
            "--yes",
        )
        assert "No real demo order was sent" in r.stdout
        assert "FASE 22 runbook" in r.stdout

    def test_prompt_non_Y_aborts(self):
        # Sem --yes, prompt eh interativo; EOF (sem input) => != "Y"
        # subprocess sem stdin = empty -> input() raises EOFError ->
        # script trata como ans=""
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
        )
        # Sem --yes: prompt sem input -> Confirmation declined -> exit 1
        assert r.returncode == 1
        assert "Confirmation declined" in r.stdout


class TestOutputJson:

    def test_output_json_written_with_yes(self, tmp_path):
        out = tmp_path / "demo30.json"
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK1234",
            "--yes",
            "--output", str(out),
        )
        assert r.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert "readiness" in data
        assert "plan" in data
        assert "outcome" in data
        assert "ui_snapshot" in data

    def test_output_json_no_secrets(self, tmp_path):
        out = tmp_path / "demo30.json"
        _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPSECRETXYZ1234",
            "--yes",
            "--output", str(out),
        )
        text = out.read_text(encoding="utf-8").lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in text
        # Token completo nunca aparece
        assert "OPSECRETXYZ1234" not in out.read_text(encoding="utf-8")

    def test_output_path_with_dotdot_rejected(self):
        bad = "../demo30.json"
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK",
            "--yes",
            "--output", bad,
        )
        # Script exit 0 mas grava nada
        assert "'..'" in r.stdout or "contains '..'" in r.stdout


class TestStdoutSanitization:

    def test_no_secrets_in_stdout(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK1234",
            "--yes",
        )
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full

    def test_banner_mentions_no_real_order(self):
        r = _run("--help")
        # --help nao chega ao banner; rodar normal
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "OPTOK1234",
            "--yes",
        )
        assert "NO real API" in r.stdout
        assert "NO real order" in r.stdout
