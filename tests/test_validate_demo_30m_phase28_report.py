"""
Tests - scripts/validate_demo_30m_phase28_report.py (FASE 28 closeout)
========================================================================
100% offline. ZERO network. Valida JSON + JSONL produzidos pelo CLI.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "validate_demo_30m_phase28_report.py"


def _run(*args: str, timeout: int = 30):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


def _make_valid_report() -> dict:
    return {
        "wired_dry_run": True,
        "apply_demo_real_invoked": False,
        "readiness": {"status": "ready"},
        "outcome": {
            "mode": "real_endurance",
            "orders_submitted": 0,
            "orders_filled": 0,
            "open_positions_count": 0,
            "safety_state": "normal",
            "manual_review_required": False,
            "safety_halt_recommended": False,
            "verdict": "passed_zero_trades",
            "recommended_next_action": "return_to_paper",
        },
    }


def _make_valid_telemetry() -> list:
    return [
        {"event_type": "session_start",
         "cycle_idx": None,
         "timestamp": "2026-06-09T12:00:00+00:00",
         "snapshot": {"strategy_name": "trend_pullback"}},
        {"event_type": "preflight_done",
         "cycle_idx": None,
         "timestamp": "2026-06-09T12:00:01+00:00",
         "snapshot": {"blueprint_id": "BP-AAA"}},
        {"event_type": "cycle_start",
         "cycle_idx": 0,
         "timestamp": "2026-06-09T12:01:00+00:00",
         "snapshot": {}},
        {"event_type": "signal_evaluated",
         "cycle_idx": 0,
         "timestamp": "2026-06-09T12:01:01+00:00",
         "snapshot": {"signal_action": "hold", "actionable": False}},
        {"event_type": "session_end",
         "cycle_idx": None,
         "timestamp": "2026-06-09T12:30:00+00:00",
         "snapshot": {"verdict": "passed_zero_trades",
                      "orders_submitted": 0}},
    ]


def _write_jsonl(events, path: Path) -> None:
    lines = [json.dumps(e, sort_keys=True) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestHappyPath:

    def test_report_only_valid_returns_0(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 0
        assert "validation OK" in r.stdout

    def test_report_and_telemetry_valid_returns_0(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(_make_valid_telemetry(), tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 0
        assert "validation OK" in r.stdout
        assert "session_start" in r.stdout
        assert "preflight_done" in r.stdout


class TestReportFailures:

    def test_wired_dry_run_false_rejected(self, tmp_path):
        data = _make_valid_report()
        data["wired_dry_run"] = False
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "wired_dry_run" in r.stdout

    def test_apply_demo_real_invoked_true_rejected(self, tmp_path):
        data = _make_valid_report()
        data["apply_demo_real_invoked"] = True
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "apply_demo_real_invoked" in r.stdout

    def test_orders_submitted_nonzero_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["orders_submitted"] = 1
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "orders_submitted" in r.stdout

    def test_open_positions_nonzero_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["open_positions_count"] = 1
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "open_positions_count" in r.stdout

    def test_safety_state_non_normal_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["safety_state"] = "paused"
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "safety_state" in r.stdout

    def test_manual_review_true_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["manual_review_required"] = True
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "manual_review_required" in r.stdout

    def test_safety_halt_true_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["safety_halt_recommended"] = True
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "safety_halt_recommended" in r.stdout

    def test_wrong_mode_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["mode"] = "dry_run_planned"
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "real_endurance" in r.stdout

    def test_readiness_not_ready_rejected(self, tmp_path):
        data = _make_valid_report()
        data["readiness"]["status"] = "not_ready"
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "readiness.status" in r.stdout


class TestTelemetryFailures:

    def test_missing_session_start_rejected(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events = [e for e in events if e["event_type"] != "session_start"]
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "session_start" in r.stdout

    def test_missing_preflight_done_rejected(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events = [e for e in events
                  if e["event_type"] != "preflight_done"]
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "preflight_done" in r.stdout

    def test_missing_session_end_rejected(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events = [e for e in events if e["event_type"] != "session_end"]
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "session_end" in r.stdout

    def test_api_failure_event_rejects(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events.insert(3, {
            "event_type": "api_failure", "cycle_idx": 0,
            "timestamp": "2026-06-09T12:01:00+00:00",
            "snapshot": {"strike_count": 1},
        })
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "api_failure" in r.stdout

    def test_safety_event_rejects(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events.insert(3, {
            "event_type": "safety_event", "cycle_idx": 0,
            "timestamp": "2026-06-09T12:01:00+00:00",
            "snapshot": {"halt_recommended": True},
        })
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "safety_event" in r.stdout

    def test_gate_invoked_dry_run_false_rejects(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events.insert(3, {
            "event_type": "gate_invoked", "cycle_idx": 0,
            "timestamp": "2026-06-09T12:01:00+00:00",
            "snapshot": {"dry_run": False},
        })
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1
        assert "dry_run" in r.stdout

    def test_gate_invoked_dry_run_true_accepted(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events.insert(3, {
            "event_type": "gate_invoked", "cycle_idx": 0,
            "timestamp": "2026-06-09T12:01:00+00:00",
            "snapshot": {"dry_run": True},
        })
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 0


class TestSecretDetection:

    def test_report_with_api_key_rejected(self, tmp_path):
        data = _make_valid_report()
        data["outcome"]["outcome_reason"] = "api_key=ABC123"
        report = tmp_path / "report.json"
        report.write_text(json.dumps(data), encoding="utf-8")
        r = _run("--report", str(report))
        assert r.returncode == 1
        assert "api_key" in r.stdout.lower() or \
               "suspicious" in r.stdout.lower()

    def test_telemetry_with_bearer_rejected(self, tmp_path):
        report = tmp_path / "report.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        events = _make_valid_telemetry()
        events[0]["snapshot"]["leaked"] = "bearer XYZ"
        tel = tmp_path / "tel.jsonl"
        _write_jsonl(events, tel)
        r = _run("--report", str(report), "--telemetry", str(tel))
        assert r.returncode == 1


class TestPathSecurity:

    def test_report_path_with_dotdot_rejected(self):
        r = _run("--report", "../report.json")
        assert r.returncode == 2
        assert "'..'" in r.stdout

    def test_telemetry_path_with_dotdot_rejected(self, tmp_path):
        report = tmp_path / "r.json"
        report.write_text(json.dumps(_make_valid_report()),
                          encoding="utf-8")
        r = _run("--report", str(report),
                 "--telemetry", "../tel.jsonl")
        assert r.returncode == 2
        assert "'..'" in r.stdout

    def test_report_file_missing_returns_2(self):
        r = _run("--report", "tests/nonexistent_xyz.json")
        assert r.returncode == 2


class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, (
                f"non-ASCII at pos {i}: {ord(ch)}"
            )

    def test_no_network_imports(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests",
                    "BybitClient", "BybitDemoExecutor",
                    "BybitDemoPreflight",
                    "execute_demo_session_gated",
                    "build_demo_api_blueprint",
                    "load_dotenv"):
            assert tok not in src, f"forbidden in validator: {tok}"
