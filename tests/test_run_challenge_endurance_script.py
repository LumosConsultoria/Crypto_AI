"""
Tests - scripts/run_challenge_endurance.py (FASE 23)
==========================================================
100% offline. ZERO network. ZERO secrets.

Covers CLI: ASCII-only, paper-only execution, DEMO_* planned-only
returns 0 without network, --output gravacao sanitizada.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_challenge_endurance.py"


def _run(*args: str, timeout: int = 60):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Source-level guards
# ---------------------------------------------------------------------------

class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, (
                f"Non-ASCII char {ord(ch)} at position {i}"
            )

    def test_no_bybit_client_import(self):
        src = _read_src()
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    def test_no_demo_executor_import(self):
        src = _read_src()
        assert "BybitDemoExecutor" not in src
        assert "BybitTestnetExecutor" not in src

    def test_no_dotenv_read(self):
        src = _read_src()
        assert "load_dotenv" not in src
        assert ".env" not in src

    def test_no_network_imports(self):
        src = _read_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

class TestExecution:

    def test_paper_30_min_exits_zero(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN")
        assert r.returncode == 0
        assert "CHALLENGE ENDURANCE - PAPER ONLY" in r.stdout
        assert "Readiness:" in r.stdout

    def test_paper_60_min_exits_zero(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_60_MIN")
        assert r.returncode == 0

    def test_paper_1_day_exits_zero(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_1_DAY")
        assert r.returncode == 0

    def test_demo_planned_stage_does_not_call_network(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "DEMO_30_MIN_PLANNED",
        )
        # Planned-only, exit 0 without touching the network.
        assert r.returncode == 0
        assert "PLANNED ONLY" in r.stdout
        # No order placed, no api error surface, no demo execution.
        assert "Comando A + B" in r.stdout

    def test_readiness_only_skips_endurance(self):
        r = _run(
            "--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN",
            "--readiness-only",
        )
        assert r.returncode == 0
        # Endurance preview block should not appear.
        assert "Endurance UI snapshot" not in r.stdout

    def test_invalid_capital_exits_1(self):
        r = _run(
            "--profile", "personal", "--capital", "0",
            "--stage", "PAPER_30_MIN",
        )
        assert r.returncode == 1

    def test_help_exit_zero(self):
        r = _run("--help")
        assert r.returncode == 0

    def test_unknown_profile_rejected_by_argparse(self):
        r = _run(
            "--profile", "unknown", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
        )
        assert r.returncode != 0


# ---------------------------------------------------------------------------
# Output sanitization
# ---------------------------------------------------------------------------

class TestOutputSanitization:

    def test_no_secrets_in_stdout(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN")
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full

    def test_output_json_written(self, tmp_path):
        out = tmp_path / "endurance.json"
        r = _run(
            "--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN",
            "--output", str(out),
        )
        assert r.returncode == 0
        assert out.exists()
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert "readiness" in payload
        assert "endurance" in payload
        assert "ui_snapshot" in payload

    def test_output_json_path_traversal_rejected(self, tmp_path):
        # Path with '..' refused.
        bad = Path("..") / "endurance.json"
        r = _run(
            "--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN",
            "--output", str(bad),
        )
        # Script still exits 0/2 (depending verdict) but writes nothing.
        # The presence of the rejection message proves the guard fired.
        assert "ERROR --output path contains '..'" in r.stdout or \
               "ERROR refusing to write output" in r.stdout

    def test_challenge_target_appears_as_kpi(self):
        r = _run(
            "--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN",
            "--challenge-target-usd", "300",
        )
        assert r.returncode == 0
        assert "informational only" in r.stdout or "Challenge KPI" in r.stdout
