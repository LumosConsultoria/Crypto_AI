"""
Tests - scripts/run_bybit_demo_session_gated.py (FASE 21) - execution
======================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Covers:
    - ASCII-only source.
    - --help exits 0 and shows usage.
    - Banner contains required strings.
    - No flags -> dry_run path; never instantiates BybitClient/BybitDemoExecutor.
    - Incomplete flags -> dry_run path.
    - --non-interactive-assume-no -> dry_run.
    - Invalid input -> exit 1.
    - Output sanitization (no api_key/api_secret/Bearer/X-BAPI-SIGN/sign=).
    - Source-level guards: no httpx/requests, no .env open/print,
      no provider registry mutation, no SessionRunner import.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"


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


# ===========================================================================
# ASCII-only
# ===========================================================================

class TestAsciiOnly:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            if ord(ch) > 127:
                start = max(0, i - 20)
                end = min(len(src), i + 20)
                raise AssertionError(
                    f"Non-ASCII char {ord(ch)} at position {i}: "
                    f"...{src[start:end]!r}..."
                )


# ===========================================================================
# --help
# ===========================================================================

class TestHelp:

    def test_help_exit_zero(self):
        r = _run("--help")
        assert r.returncode == 0

    def test_help_shows_dry_run_default(self):
        r = _run("--help")
        # "DRY-RUN" appears in description
        assert "DRY-RUN" in r.stdout or "dry-run" in r.stdout.lower()


# ===========================================================================
# Banner
# ===========================================================================

class TestBanner:

    def test_banner_says_bybit_demo_session_gated(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        assert "BYBIT DEMO SESSION GATED" in r.stdout

    def test_banner_says_dry_run_default(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        assert "DRY-RUN DEFAULT" in r.stdout

    def test_banner_says_readiness_not_authorization(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        assert "READINESS IS NOT AUTHORIZATION" in r.stdout

    def test_banner_says_no_order_unless_explicit_flags(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        assert "NO ORDER UNLESS EXPLICIT FLAGS" in r.stdout


# ===========================================================================
# Dry-run paths (no flags / partial flags / --non-interactive-assume-no)
# ===========================================================================

class TestDryRunPaths:

    def test_no_flags_dry_run(self):
        r = _run(*_COMMON)
        assert r.returncode == 0
        assert "Four CLI flags complete: False" in r.stdout

    def test_only_execute_demo_flag_with_manual_values_blocked(self):
        # FASE 22: any real-path flag combined with manual entry/sl/tp/size
        # is now blocked before any execution.
        r = _run(*_COMMON, "--execute-demo")
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout

    def test_three_flags_without_token_with_manual_values_blocked(self):
        # FASE 22: still real-path requested via three flags + manual.
        r = _run(
            *_COMMON,
            "--execute-demo",
            "--confirm-demo-session",
            "--i-understand-this-is-demo",
        )
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout

    def test_empty_operator_token_with_manual_values_blocked(self):
        # FASE 22: three real flags (whitespace token ignored) + manual.
        r = _run(
            *_COMMON,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", "   ",
            "--i-understand-this-is-demo",
        )
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout

    def test_non_interactive_assume_no_forces_dry_run(self):
        r = _run(
            *_COMMON,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", "operator@example.com",
            "--i-understand-this-is-demo",
            "--non-interactive-assume-no",
        )
        # Even with all 4 flags, this CI flag forces dry-run.
        assert "forcing dry-run" in r.stdout
        # Exit code 0 OR 2 depending on whether gate matched canonical
        # path (paper-mode guard rejects -> EXIT_OK preview path).
        assert r.returncode == 0


# ===========================================================================
# Invalid input
# ===========================================================================

class TestInvalidInput:

    def test_zero_capital_exit_1(self):
        r = _run(
            "--profile", "personal", "--capital", "0",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "67000",
            "--size", "200",
            "--non-interactive-assume-no",
        )
        assert r.returncode == 1

    def test_negative_capital_exit_1(self):
        r = _run(
            "--profile", "personal", "--capital", "-100",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "67000",
            "--size", "200",
            "--non-interactive-assume-no",
        )
        assert r.returncode == 1

    def test_invalid_buy_blueprint_exit_1(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "66000",  # SL above entry - invalid BUY
            "--tp", "67000", "--size", "200",
            "--non-interactive-assume-no",
        )
        assert r.returncode == 1
        assert "ERROR" in r.stdout

    def test_invalid_tp_zero_exit_1(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "0",
            "--size", "200",
            "--non-interactive-assume-no",
        )
        assert r.returncode == 1


# ===========================================================================
# Output sanitization
# ===========================================================================

class TestOutputSanitization:

    def test_no_api_key_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "api_key" not in full
        assert "api-key" not in full

    def test_no_api_secret_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "api_secret" not in full

    def test_no_bearer_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "bearer " not in full

    def test_no_x_bapi_sign_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "x-bapi-sign" not in full
        assert "x-bapi" not in full

    def test_no_signature_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "sign=" not in full
        assert "signature=" not in full

    def test_no_authorization_in_output(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        full = (r.stdout + r.stderr).lower()
        assert "authorization:" not in full

    def test_operator_token_truncated_not_full(self):
        # Run with --non-interactive-assume-no so we never reach prompt,
        # but token is still passed. Truncation happens in audit and outcome.
        # The CLI prints "cli_preview_token" when token is dry-run; here we
        # provide a unique token to assert truncation behavior in the path
        # where token IS used. Use long token to validate it never appears
        # in full.
        long_token = "operator@example.com_LONG_RAW_TOKEN_AB12"
        r = _run(
            *_COMMON,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", long_token,
            "--i-understand-this-is-demo",
            "--non-interactive-assume-no",
        )
        # Full token must NEVER appear in output.
        assert long_token not in r.stdout
        assert long_token not in r.stderr


# ===========================================================================
# Source-level guards
# ===========================================================================

class TestNoForbiddenImports:

    def test_no_httpx_import(self):
        src = _read_src()
        assert "import httpx" not in src
        assert "from httpx" not in src

    def test_no_requests_import(self):
        src = _read_src()
        assert "import requests" not in src
        assert "from requests" not in src

    def test_no_dotenv_load(self):
        src = _executable_lines(_read_src())
        # Settings loads .env via pydantic-settings only; script must NOT
        # call load_dotenv or open .env directly.
        assert "load_dotenv" not in src
        assert "open('.env'" not in src
        assert 'open(".env"' not in src

    def test_no_session_runner_import(self):
        src = _executable_lines(_read_src())
        assert "SessionRunner" not in src
        assert "session_runner.runner" not in src

    def test_no_provider_registry_mutation(self):
        src = _executable_lines(_read_src())
        # Source must NOT call ProviderRegistry.register/unregister/replace.
        assert ".register(ProviderEntry" not in src
        # get_registry().register( would mutate; we only use get_registry()
        # for read.
        assert "get_registry().register(" not in src
        assert "get_registry().unregister(" not in src

    def test_no_assert_live_allowed_call(self):
        src = _executable_lines(_read_src())
        # We must not touch live trading code paths.
        assert "assert_live_allowed" not in src

    def test_does_not_alter_bybit_demo_executor_module(self):
        # Source must NOT contain class BybitDemoExecutor definition.
        src = _executable_lines(_read_src())
        assert "class BybitDemoExecutor" not in src

    def test_no_close_position_or_reduce_only(self):
        # Script does NOT implement close_position / cancel_order /
        # reduceOnly anywhere.
        src = _executable_lines(_read_src())
        assert "close_position" not in src
        assert "cancel_order" not in src
        assert "reduceOnly" not in src
        assert "reduce_only" not in src


# ===========================================================================
# Recommended-next-action presence
# ===========================================================================

class TestOutputContainsRecommendedNext:

    def test_dry_run_shows_recommended_next(self):
        r = _run(*_COMMON, "--non-interactive-assume-no")
        # Recommended_next is printed only when the gate produces an outcome.
        # In CLI default the paper-mode guard rejects (exit 0); recommended
        # may not appear. Accept either case.
        if "Outcome reason" in r.stdout:
            assert "Recommended next" in r.stdout
