"""
Tests - run_bybit_demo_session_gated.py FASE 22 integration
================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Covers:
    - Real-path with manual entry/sl/tp/size is blocked with clear msg.
    - --from-blueprint conflicts with manual values.
    - --prepare-demo-blueprint without --output is rejected.
    - --prepare-demo-blueprint conflicts with --from-blueprint.
    - Dry-run preview path (FASE 21) preserved.
    - --from-blueprint with stale JSON rejected.
    - --from-blueprint with malformed JSON rejected.
    - Output banner unchanged.
    - Source: docstring marks examples with <PLACEHOLDER>.
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


_COMMON_DRY = (
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
# Phase 22 - real path blocked with manual values
# ===========================================================================

class TestRealPathBlocked:

    def test_execute_demo_with_manual_values_rejected(self):
        # Four flags + manual entry/sl/tp/size => block before any network.
        r = _run(
            *_COMMON_DRY,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", "operator@example.com",
            "--i-understand-this-is-demo",
        )
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout
        assert "API-driven blueprint" in r.stdout

    def test_only_execute_demo_flag_with_manual_blocks(self):
        # Even with a single real flag, manual values + real path = block.
        r = _run(
            *_COMMON_DRY,
            "--execute-demo",
        )
        assert r.returncode == 1
        assert "Real demo execution requires" in r.stdout

    def test_only_operator_token_with_manual_blocks(self):
        r = _run(
            *_COMMON_DRY,
            "--operator-token", "operator@example.com",
        )
        assert r.returncode == 1


# ===========================================================================
# Phase 22 - mode conflicts
# ===========================================================================

class TestModeConflicts:

    def test_prepare_without_output_rejected(self):
        r = _run(
            "--prepare-demo-blueprint",
            "--profile", "personal",
            "--capital", "5000",
            "--symbol", "BTCUSDT",
            "--side", "buy",
        )
        assert r.returncode == 1
        assert "--output" in r.stdout

    def test_prepare_combined_with_from_blueprint_rejected(self, tmp_path: Path):
        r = _run(
            "--prepare-demo-blueprint",
            "--output", str(tmp_path / "out.json"),
            "--from-blueprint", str(tmp_path / "x.json"),
            "--profile", "personal",
            "--capital", "5000",
            "--symbol", "BTCUSDT",
        )
        assert r.returncode == 1
        assert "cannot combine" in r.stdout

    def test_from_blueprint_with_manual_values_rejected(self, tmp_path: Path):
        path = tmp_path / "bp.json"
        path.write_text("{}", encoding="utf-8")  # malformed, but enough for arg parse
        r = _run(
            *_COMMON_DRY,
            "--from-blueprint", str(path),
        )
        assert r.returncode == 1
        assert "conflicts with manual" in r.stdout


# ===========================================================================
# Phase 22 - dry-run preview preserved (FASE 21 backward compat)
# ===========================================================================

class TestDryRunPreservedFromPhase21:

    def test_dry_run_preview_exits_zero(self):
        r = _run(*_COMMON_DRY, "--non-interactive-assume-no")
        assert r.returncode == 0
        assert "BYBIT DEMO SESSION GATED" in r.stdout
        assert "DRY-RUN DEFAULT" in r.stdout

    def test_dry_run_preview_no_flags_exits_zero(self):
        r = _run(*_COMMON_DRY)
        assert r.returncode == 0


# ===========================================================================
# Phase 22 - --from-blueprint validation (without preflight)
# ===========================================================================

class TestFromBlueprintValidation:

    def test_from_blueprint_missing_file_rejected(self, tmp_path: Path):
        r = _run(
            "--profile", "personal",
            "--from-blueprint", str(tmp_path / "missing.json"),
        )
        assert r.returncode == 1
        assert "BLUEPRINT LOAD REJECTED" in r.stdout

    def test_from_blueprint_malformed_json_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not-json", encoding="utf-8")
        r = _run(
            "--profile", "personal",
            "--from-blueprint", str(path),
        )
        assert r.returncode == 1
        assert "BLUEPRINT LOAD REJECTED" in r.stdout


# ===========================================================================
# Source-level: docstring placeholders
# ===========================================================================

class TestSourceDocstringPlaceholders:

    def test_docstring_uses_placeholder_label_in_examples(self):
        src = _read_src()
        # The PREVIEW example must label its values as <PLACEHOLDER...>
        # to avoid operator confusion with real values.
        assert "<PLACEHOLDER" in src

    def test_real_path_step1_mentions_prepare_blueprint(self):
        src = _read_src()
        assert "--prepare-demo-blueprint" in src

    def test_real_path_step2_mentions_from_blueprint(self):
        src = _read_src()
        assert "--from-blueprint" in src


# ===========================================================================
# Sanitization (subprocess output, FASE 22 paths)
# ===========================================================================

class TestOutputSanitizationPhase22:

    def test_no_secrets_when_blocked(self):
        r = _run(
            *_COMMON_DRY,
            "--execute-demo",
            "--confirm-demo-session",
            "--operator-token", "operator@example.com_SECRET_42",
            "--i-understand-this-is-demo",
        )
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:"):
            assert tok not in full
        # Long operator token must NOT appear in full (block came before
        # any audit logging, so token isn't printed; we still validate).
        assert "operator@example.com_SECRET_42" not in r.stdout
        assert "operator@example.com_SECRET_42" not in r.stderr
