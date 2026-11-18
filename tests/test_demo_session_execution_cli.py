"""
Testes - CLI scripts/run_demo_session_gated.py (FASE 20)
==============================================================
100% offline. ZERO rede. ZERO API. ZERO secrets. ZERO ordem.

Garante:
    - ASCII-only no source.
    - Script roda sem rede.
    - Nao importa BybitClient/BybitDemoExecutor/httpx/requests no source.
    - Nao abre/imprime .env.
    - Output nao contem api_key/api_secret/Bearer/X-BAPI-SIGN/sign=.
    - --dry-run e o padrao.
    - Banner contem DRY-RUN DEFAULT / DOES NOT EXECUTE / READINESS IS NOT AUTHORIZATION.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_session_gated.py"


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=timeout,
        check=False,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


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


# ---------------------------------------------------------------------------
# ASCII-only no source
# ---------------------------------------------------------------------------

class TestAsciiOnly:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            if ord(ch) > 127:
                # mostra contexto para debug
                start = max(0, i - 20)
                end = min(len(src), i + 20)
                raise AssertionError(
                    f"Non-ASCII char {ord(ch)} at position {i}: "
                    f"...{src[start:end]!r}..."
                )


# ---------------------------------------------------------------------------
# Imports proibidos
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:

    def test_no_bybit_client_import(self):
        src = _executable_lines(_read_src())
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    def test_no_bybit_demo_executor_import(self):
        src = _executable_lines(_read_src())
        # CLI deliberadamente NAO importa nem instancia BybitDemoExecutor.
        # (a string pode aparecer em prints informativos, mas nao como
        # chamada/import.)
        assert "from crypto_trading_bot.execution.bybit_demo_executor" not in src
        assert "import crypto_trading_bot.execution.bybit_demo_executor" not in src
        assert "BybitDemoExecutor(" not in src

    def test_no_testnet_executor_import(self):
        src = _executable_lines(_read_src())
        assert "BybitTestnetExecutor" not in src

    def test_no_network_imports(self):
        src = _read_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_no_dotenv_open(self):
        # CLI nao abre/imprime .env diretamente.
        src = _executable_lines(_read_src())
        assert "load_dotenv" not in src
        assert "open('.env'" not in src
        assert 'open(".env"' not in src

    def test_no_session_runner_import(self):
        src = _executable_lines(_read_src())
        assert "SessionRunner" not in src


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------

_COMMON = (
    "--profile", "personal",
    "--capital", "5000",
    "--symbol", "BTCUSDT",
    "--side", "buy",
    "--entry", "65000",
    "--sl", "64000",
    "--tp", "67000",
    "--size", "200",
)


class TestExecution:

    def test_runs_default_dry_run(self):
        r = _run(*_COMMON)
        assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"

    def test_banner_contains_dry_run_default(self):
        r = _run(*_COMMON)
        assert "DRY-RUN DEFAULT" in r.stdout

    def test_banner_contains_does_not_execute(self):
        r = _run(*_COMMON)
        assert "DOES NOT EXECUTE" in r.stdout

    def test_banner_contains_readiness_not_authorization(self):
        r = _run(*_COMMON)
        assert "READINESS IS NOT AUTHORIZATION" in r.stdout

    def test_banner_contains_no_order_unless_explicit_flags(self):
        r = _run(*_COMMON)
        assert "NO ORDER UNLESS EXPLICIT FLAGS" in r.stdout

    def test_dry_run_default_true_in_output(self):
        r = _run(*_COMMON)
        assert "dry_run: True" in r.stdout

    def test_invalid_blueprint_blocks(self):
        # SL acima do entry para BUY -> blueprint rejeita -> exit 1.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "66000", "--tp", "67000",
            "--size", "200",
        )
        assert r.returncode == 1
        assert "ERROR" in r.stdout

    def test_real_demo_flags_without_executor_exits_1(self):
        # All 4 flags set, but CLI never wires a real executor.
        r = _run(
            *_COMMON,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", "operator@example.com",
            "--i-understand-this-is-demo",
        )
        # CLI should print and exit 1 to make clear no order was sent.
        assert r.returncode == 1
        assert "does NOT instantiate a real BybitDemoExecutor" in r.stdout

    def test_zero_capital_exits_1(self):
        r = _run(
            "--profile", "personal", "--capital", "0",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "67000",
            "--size", "200",
        )
        assert r.returncode == 1


# ---------------------------------------------------------------------------
# Sanitizacao do output
# ---------------------------------------------------------------------------

class TestOutputSanitization:

    def test_no_api_key_in_output(self):
        r = _run(*_COMMON)
        full = (r.stdout + r.stderr).lower()
        assert "api_key" not in full
        assert "api-key" not in full

    def test_no_api_secret_in_output(self):
        r = _run(*_COMMON)
        full = (r.stdout + r.stderr).lower()
        assert "api_secret" not in full

    def test_no_bearer_in_output(self):
        r = _run(*_COMMON)
        full = (r.stdout + r.stderr).lower()
        assert "bearer " not in full

    def test_no_x_bapi_sign(self):
        r = _run(*_COMMON)
        full = (r.stdout + r.stderr).lower()
        assert "x-bapi-sign" not in full
        assert "x-bapi" not in full

    def test_no_signature(self):
        r = _run(*_COMMON)
        full = (r.stdout + r.stderr).lower()
        assert "sign=" not in full
        assert "signature=" not in full
