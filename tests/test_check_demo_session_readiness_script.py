"""
Testes — CLI scripts/check_demo_session_readiness.py (FASE 19)
==================================================================
⚠️  100% offline. ZERO rede. ZERO API. ZERO secrets. ZERO ordem.

Garante:
    - Script roda sem rede.
    - Não importa BybitClient, BybitDemoExecutor, BybitTestnetExecutor,
      httpx, requests, DemoExecutionResult, SessionRunner, BotEngine,
      RiskEngine no source.
    - Output não contém api_key/api_secret/Bearer/X-BAPI-SIGN.
    - Não abre/imprime .env.
    - Exit 0 quando ready; exit 1 quando há blocking.
    - Aceita 4 profile choices.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_demo_session_readiness.py"


def _run_script(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Roda o script via subprocess. Sem rede. Sem env extra."""
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=timeout,
        check=False,
    )


def _executable_lines(src: str) -> str:
    out: list[str] = []
    in_block = False
    block_quote: str | None = None
    for line in src.splitlines():
        stripped = line.strip()
        if in_block:
            if block_quote and block_quote in line:
                in_block = False
                block_quote = None
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) == 1:
                    in_block = True
                    block_quote = q
                break
        else:
            if stripped.startswith("#"):
                continue
            out.append(line)
            continue
    return "\n".join(out)


def _read_script_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Imports proibidos no source do script
# ---------------------------------------------------------------------------

class TestScriptNoForbiddenImports:

    def test_no_bybit_client_import(self):
        src = _executable_lines(_read_script_src())
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    def test_no_demo_executor_import(self):
        src = _executable_lines(_read_script_src())
        assert "BybitDemoExecutor" not in src
        assert "BybitTestnetExecutor" not in src

    def test_no_demo_execution_result_import(self):
        src = _executable_lines(_read_script_src())
        assert "DemoExecutionResult" not in src

    def test_no_session_runner_import(self):
        src = _executable_lines(_read_script_src())
        assert "SessionRunner" not in src

    def test_no_bot_engine_import(self):
        src = _executable_lines(_read_script_src())
        assert "BotEngine" not in src

    def test_no_risk_engine_import(self):
        src = _executable_lines(_read_script_src())
        assert "RiskEngine" not in src

    def test_no_network_imports(self):
        src = _read_script_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_no_apply_overrides_call(self):
        src = _executable_lines(_read_script_src())
        assert "apply_profile_overrides_with_gate(" not in src

    def test_no_dotenv_read(self):
        # Script NÃO deve abrir/imprimir .env diretamente.
        src = _executable_lines(_read_script_src())
        assert ".env" not in src
        assert "load_dotenv" not in src


# ---------------------------------------------------------------------------
# Execução end-to-end
# ---------------------------------------------------------------------------

class TestScriptExecution:

    def test_runs_with_personal_profile(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        assert r.returncode == 0, (
            f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )

    def test_runs_with_prop_challenge(self):
        r = _run_script("--profile", "prop_challenge", "--capital", "10000")
        assert r.returncode == 0

    def test_runs_with_hyrotrader_template(self):
        r = _run_script(
            "--profile", "hyrotrader_demo_template", "--capital", "5000"
        )
        assert r.returncode == 0

    def test_runs_with_custom(self):
        r = _run_script("--profile", "custom", "--capital", "5000")
        assert r.returncode == 0

    def test_output_contains_banner(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        assert "DOES NOT EXECUTE" in r.stdout
        assert "PREVIEW ONLY" in r.stdout

    def test_output_contains_footer(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        assert "NO ORDER SENT" in r.stdout

    def test_output_shows_provider_id(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        assert "bybit_demo_linear" in r.stdout

    def test_output_shows_is_ready(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        assert "is_ready_for_gated_demo" in r.stdout

    def test_zero_capital_exits_nonzero(self):
        r = _run_script("--profile", "personal", "--capital", "0")
        assert r.returncode != 0

    def test_negative_capital_exits_nonzero(self):
        r = _run_script("--profile", "personal", "--capital", "-100")
        assert r.returncode != 0

    def test_open_position_blocks(self):
        r = _run_script(
            "--profile", "personal", "--capital", "5000",
            "--has-open-position",
        )
        assert r.returncode == 1
        assert "is_ready_for_gated_demo: False" in r.stdout

    def test_open_orders_blocks(self):
        r = _run_script(
            "--profile", "personal", "--capital", "5000",
            "--has-open-orders",
        )
        assert r.returncode == 1
        assert "is_ready_for_gated_demo: False" in r.stdout


# ---------------------------------------------------------------------------
# Sanitização de output
# ---------------------------------------------------------------------------

class TestScriptOutputSanitization:

    def test_no_api_key_in_output(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        full = (r.stdout + r.stderr).lower()
        assert "api_key" not in full
        assert "api-key" not in full

    def test_no_api_secret_in_output(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        full = (r.stdout + r.stderr).lower()
        assert "api_secret" not in full
        assert "api-secret" not in full

    def test_no_bearer_in_output(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        full = (r.stdout + r.stderr).lower()
        assert "bearer " not in full

    def test_no_x_bapi_sign_in_output(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        full = (r.stdout + r.stderr).lower()
        assert "x-bapi-sign" not in full
        assert "x-bapi" not in full

    def test_no_signature_in_output(self):
        r = _run_script("--profile", "personal", "--capital", "5000")
        full = (r.stdout + r.stderr).lower()
        assert "sign=" not in full
        assert "signature=" not in full
