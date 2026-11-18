"""
Tests - FASE 22 Final wiring: script uses strong post_session_check
=========================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Closes the FASE 22 ressalva: scripts/run_bybit_demo_session_gated.py
must wire executor.post_session_check (strong: balance + positions +
open_orders + residual detection) instead of the legacy
safe_check_only (only balance) in the real-attempted path.

Source-level test: inspects the script source to confirm the wiring
is present and the legacy-only fallback isn't the primary path for
real_attempted=True.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"


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
# Source-level: wiring uses post_session_check primary, safe_check_only fallback
# ---------------------------------------------------------------------------

class TestPostSessionCheckWiringSource:

    def test_source_references_post_session_check(self):
        src = _executable_lines(_read_src())
        # Must reference the strong post_session_check method.
        assert "post_session_check" in src

    def test_real_attempted_path_prefers_post_session_check(self):
        """When real_attempted=True, the script must call
        executor.post_session_check(symbol, dry_run=False) as PRIMARY
        post-check, with safe_check_only only as fallback."""
        src = _executable_lines(_read_src())
        # Anchor on the post_check_fn assignment block which is the
        # actual wiring location in main(); not the _footer printout.
        idx_anchor = src.find("post_check_fn = None")
        assert idx_anchor >= 0, "missing post_check_fn anchor in main()"
        window = src[idx_anchor:idx_anchor + 2000]
        post_idx = window.find("post_session_check")
        safe_idx = window.find("safe_check_only")
        assert post_idx >= 0, "real-attempted wiring must invoke post_session_check"
        # post_session_check must appear earlier than safe_check_only
        # (which is the fallback).
        if safe_idx >= 0:
            assert post_idx < safe_idx, (
                "post_session_check must be PRIMARY (appear before "
                "safe_check_only fallback)"
            )

    def test_post_session_check_called_with_dry_run_false_in_real_path(self):
        """The real path must invoke post_session_check(dry_run=False)."""
        src = _executable_lines(_read_src())
        # Look for the exact pattern (allowing whitespace variations).
        assert "post_session_check(" in src
        # In real branch, must be False; in dry-run branch, True.
        # Both must be present.
        # Real branch (dry_run=False)
        assert "dry_run=False" in src
        # Dry-run branch (dry_run=True)
        assert "dry_run=True" in src

    def test_hasattr_guard_for_compat(self):
        """Source must use hasattr(executor, 'post_session_check')
        before invoking it, for backward-compat with legacy fakes."""
        src = _executable_lines(_read_src())
        assert "hasattr(executor, \"post_session_check\")" in src or \
               "hasattr(executor, 'post_session_check')" in src

    def test_safe_check_only_still_present_as_fallback(self):
        """safe_check_only must remain as a fallback for executors that
        don't have post_session_check."""
        src = _executable_lines(_read_src())
        assert "safe_check_only" in src

    def test_dry_executor_does_not_break_wiring(self):
        """_DryExecutor lacks both safe_check_only and post_session_check;
        the script must handle that case without crashing (post_check_fn
        ends up None)."""
        src = _executable_lines(_read_src())
        # Both branches must guard hasattr; either method's absence is OK.
        # Verify presence of hasattr guards for both methods.
        assert ("hasattr(executor, \"post_session_check\")" in src or
                "hasattr(executor, 'post_session_check')" in src)
        assert ("hasattr(executor, \"safe_check_only\")" in src or
                "hasattr(executor, 'safe_check_only')" in src)


# ---------------------------------------------------------------------------
# Functional: load the script module and verify post_check_fn resolution
# ---------------------------------------------------------------------------

import importlib.util
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "run_bybit_demo_session_gated_p22final", str(_SCRIPT),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    src_path = str(_REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


class TestDryExecutorCompatibility:

    def test_dry_executor_has_no_post_session_check(self, script_module):
        """_DryExecutor only implements .execute() - confirming wiring
        must guard against missing post_session_check."""
        dry = script_module._DryExecutor()
        assert not hasattr(dry, "post_session_check")
        assert not hasattr(dry, "safe_check_only")
        # The script's post_check_fn ends up None in this case; the
        # gate code handles None gracefully.


# ---------------------------------------------------------------------------
# Audit: still no manual values allowed in real path (regression FASE 22)
# ---------------------------------------------------------------------------

import subprocess


def _run(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


_COMMAND_B_FLAGS = (
    "--execute-demo",
    "--confirm-demo-session",
    "--operator-token", "operator@example.com",
    "--i-understand-this-is-demo",
)


class TestCommandBManualValuesStillBlocked:

    def test_command_b_with_manual_entry_still_rejected(self):
        # Regressao FASE 22: manual values + real flags = block.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "67000",
            "--size", "200",
            *_COMMAND_B_FLAGS,
        )
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout

    def test_command_b_with_stale_blueprint_rejected(self, tmp_path):
        # Mock blueprint file thats malformed; load_from_json should reject.
        bp = tmp_path / "stale.json"
        bp.write_text("{}", encoding="utf-8")
        r = _run(
            "--profile", "personal",
            "--from-blueprint", str(bp),
            *_COMMAND_B_FLAGS,
        )
        # Loading malformed JSON -> BLUEPRINT LOAD REJECTED
        assert r.returncode == 1
        assert "BLUEPRINT LOAD REJECTED" in r.stdout


# ---------------------------------------------------------------------------
# Command A: --prepare-demo-blueprint cannot combine with --from-blueprint
# ---------------------------------------------------------------------------

class TestCommandAExclusivity:

    def test_prepare_and_from_blueprint_are_mutually_exclusive(self, tmp_path):
        out = tmp_path / "out.json"
        from_bp = tmp_path / "in.json"
        from_bp.write_text("{}", encoding="utf-8")
        r = _run(
            "--prepare-demo-blueprint",
            "--output", str(out),
            "--from-blueprint", str(from_bp),
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT",
        )
        assert r.returncode == 1
        assert "cannot combine" in r.stdout

    def test_prepare_requires_output(self):
        r = _run(
            "--prepare-demo-blueprint",
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
        )
        assert r.returncode == 1
        assert "--output" in r.stdout


# ---------------------------------------------------------------------------
# Output sanitization (regression for FASE 22 Final)
# ---------------------------------------------------------------------------

class TestOutputSanitizationRegression:

    def test_output_has_no_origin_string_token(self):
        # No real execution; just confirm pipeline doesn't leak tokens.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT", "--side", "buy",
            "--entry", "65000", "--sl", "64000", "--tp", "67000",
            "--size", "200",
            "--non-interactive-assume-no",
        )
        full = (r.stdout + r.stderr).lower()
        # origin_string substring should never appear
        assert "origin_string" not in full
        # No other secret-class tokens
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi-sign",
                    "authorization:", "sign="):
            assert tok not in full
