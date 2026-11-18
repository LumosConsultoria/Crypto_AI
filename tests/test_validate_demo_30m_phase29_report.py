"""
Tests - scripts/validate_demo_30m_phase29_report.py
========================================================
100% offline. Validador FASE 29.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "validate_demo_30m_phase29_report.py"


def _run(*args: str, timeout: int = 30):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


def _make_clean_report() -> dict:
    return {
        "phase": "29",
        "real_demo_full_cycle": True,
        "readiness": {"status": "ready"},
        "outcome": {
            "mode": "real_endurance",
            "verdict": "demo_full_cycle_clean",
            "orders_submitted": 1,
            "orders_filled": 1,
            "open_positions_count": 0,
            "safety_state": "normal",
            "manual_review_required": False,
            "safety_halt_recommended": False,
            "apply_demo_real_invoked": True,
            "first_real_demo_order": True,
            "phrase_confirmation": True,
            "demo_finalized": True,
            "demo_finalization_scenario": "A_clean",
            "exit_management_path": "tp_sl_server_side",
            "exit_reason": "exited_by_take_profit",
            "close_orders_submitted": 0,
            "close_orders_filled": 0,
            "pnl_realized_usd": 1.23,
            "pnl_source": "api_execution_list",
            "flat_check_result": {
                "is_flat": True, "positions_count": 0,
                "open_orders_count": 0,
                "conditional_orders_count": 0,
                "residual_qty": 0.0, "blockers": [],
            },
        },
    }


def _make_zero_trade_report() -> dict:
    return {
        "phase": "29",
        "real_demo_full_cycle": True,
        "readiness": {"status": "ready"},
        "outcome": {
            "mode": "real_endurance",
            "verdict": "passed_zero_trades",
            "orders_submitted": 0,
            "orders_filled": 0,
            "open_positions_count": 0,
            "safety_state": "normal",
            "manual_review_required": False,
            "safety_halt_recommended": False,
            "apply_demo_real_invoked": True,
            "first_real_demo_order": True,
            "phrase_confirmation": True,
            "demo_finalized": False,
            "demo_finalization_scenario": "B_zero",
            "exit_management_path": "none",
            "exit_reason": None,
            "close_orders_submitted": 0,
            "close_orders_filled": 0,
            "pnl_realized_usd": None,
            "pnl_source": None,
            "flat_check_result": None,
        },
    }


def _make_telemetry_clean() -> list:
    return [
        {"event_type": "session_start", "cycle_idx": None,
         "timestamp": "2026-06-10T12:00:00Z", "snapshot": {}},
        {"event_type": "preflight_done", "cycle_idx": None,
         "timestamp": "2026-06-10T12:00:01Z", "snapshot": {}},
        {"event_type": "gate_invoked", "cycle_idx": 0,
         "timestamp": "2026-06-10T12:01:00Z",
         "snapshot": {"dry_run": False}},
        {"event_type": "exit_monitoring_started", "cycle_idx": None,
         "timestamp": "2026-06-10T12:02:00Z", "snapshot": {}},
        {"event_type": "exit_detected", "cycle_idx": 5,
         "timestamp": "2026-06-10T12:10:00Z",
         "snapshot": {"exit_path": "tp_sl_server_side"}},
        {"event_type": "session_end", "cycle_idx": None,
         "timestamp": "2026-06-10T12:30:00Z", "snapshot": {}},
    ]


def _write_jsonl(events, path: Path) -> None:
    path.write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in events)
        + "\n",
        encoding="utf-8",
    )


class TestHappyPaths:

    def test_clean_scenario(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps(_make_clean_report()),
                          encoding="utf-8")
        tel = tmp_path / "t.jsonl"
        _write_jsonl(_make_telemetry_clean(), tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 0
        assert "DEMO FINALIZED" in r.stdout
        assert "scenario=A_clean" in r.stdout

    def test_zero_trade_scenario(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps(_make_zero_trade_report()),
                          encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 0
        assert "B_zero" in r.stdout
        assert "DEMO NOT YET FINALIZED" in r.stdout


class TestDemoFinalizedSemantics:
    """FASE 29 Acceptance Polish - verdict canonico sem ambiguidade."""

    def test_clean_uses_demo_full_cycle_clean_verdict(self, tmp_path):
        data = _make_clean_report()
        assert data["outcome"]["verdict"] == "demo_full_cycle_clean"
        assert data["outcome"]["demo_finalized"] is True
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 0
        assert "DEMO FINALIZED" in r.stdout

    def test_demo_finalized_false_with_clean_verdict_rejected(
        self, tmp_path,
    ):
        data = _make_clean_report()
        data["outcome"]["demo_finalized"] = False
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "demo_finalized" in r.stdout

    def test_zero_trade_must_not_be_demo_finalized(self, tmp_path):
        data = _make_zero_trade_report()
        data["outcome"]["demo_finalized"] = True  # invalid
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_wrong_finalization_scenario_rejected(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["demo_finalization_scenario"] = "B_zero"
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1


class TestRejects:

    def test_phase_must_be_29(self, tmp_path):
        data = _make_clean_report()
        data["phase"] = "28"
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "phase" in r.stdout

    def test_real_demo_full_cycle_false_rejected(self, tmp_path):
        data = _make_clean_report()
        data["real_demo_full_cycle"] = False
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_apply_demo_real_invoked_false_rejected(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["apply_demo_real_invoked"] = False
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_first_real_demo_order_false_rejected(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["first_real_demo_order"] = False
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_close_orders_above_cap_rejected(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["close_orders_submitted"] = 2
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_clean_with_exit_path_none_rejected(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["exit_management_path"] = "none"
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_secret_detected_in_report(self, tmp_path):
        data = _make_clean_report()
        data["outcome"]["outcome_reason"] = "api_key=ABC123"
        report = tmp_path / "r.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1

    def test_gate_invoked_dry_run_true_rejected_in_telemetry(
        self, tmp_path,
    ):
        report = tmp_path / "r.json"
        report.write_text(json.dumps(_make_clean_report()),
                          encoding="utf-8")
        events = _make_telemetry_clean()
        # Reverse gate_invoked dry_run to True (which is FASE 28)
        for e in events:
            if e.get("event_type") == "gate_invoked":
                e["snapshot"]["dry_run"] = True
        tel = tmp_path / "t.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "dry_run" in r.stdout


class TestPathSecurity:

    def test_report_path_dotdot_rejected(self):
        r = _run("--report", "../r.json")
        assert r.returncode == 2

    def test_report_missing_returns_2(self):
        r = _run("--report", "tests/nonexistent.json")
        assert r.returncode == 2


class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, f"non-ASCII at {i}: {ord(ch)}"

    def test_no_network_imports(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests",
                    "BybitClient", "BybitDemoExecutor",
                    "BybitDemoPreflight",
                    "execute_demo_session_gated",
                    "build_demo_api_blueprint"):
            assert tok not in src, f"forbidden in validator: {tok}"
