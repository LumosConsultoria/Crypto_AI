"""
Tests - scripts/run_demo_endurance.py (FASE 30 CLI)
====================================================
100% offline. Subprocess usa SOMENTE --synthetic-feed (zero rede).
Nenhum teste usa --real-time (sleep real proibido em teste).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_endurance.py"


def _run(*args: str, timeout: int = 180):
    import os
    env = os.environ.copy()
    # Garante gates OFF e zero credenciais no subprocess.
    for k in ("DEMO_ALLOW_MULTI_ORDER_PER_SESSION",
              "ENABLE_PREDICTION_MARKET_CONTEXT",
              "DEMO_ALLOW_AI_MANUAL_REVIEW",
              "BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET"):
        env[k] = ""
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(_REPO_ROOT),
        timeout=timeout, check=False, env=env,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestSourceGuards:

    def test_no_no_max_time_flag(self):
        src = _read_src()
        assert 'add_argument("--no-max-time"' not in src
        assert "add_argument('--no-max-time'" not in src

    def test_no_dotenv_load(self):
        src = _read_src()
        assert "load_dotenv" not in src

    def test_no_real_order_calls(self):
        src = _read_src()
        # CLI FASE 30 nunca invoca envio real.
        assert "submit_order" not in src
        assert "place_order" not in src
        assert "dry_run=False" not in src

    def test_mentions_orders_submitted_zero(self):
        assert "orders_submitted=0" in _read_src()


class TestArgValidation:

    def test_requires_exactly_one_duration(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--operator-token", "T", "--demo-only",
        )
        assert r.returncode == 1
        assert "EXATAMENTE uma duracao" in r.stdout

    def test_rejects_both_durations(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--operator-token", "T", "--demo-only",
            "--duration-minutes", "30", "--duration-days", "1",
        )
        assert r.returncode == 1

    def test_requires_demo_only(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--operator-token", "T", "--duration-minutes", "30",
        )
        assert r.returncode == 1
        assert "--demo-only" in r.stdout

    def test_unknown_profile_rejected(self):
        r = _run(
            "--profile", "fake_profile", "--capital", "5000",
            "--operator-token", "T", "--demo-only",
            "--duration-minutes", "30", "--synthetic-feed",
        )
        assert r.returncode == 1
        # argparse nao restringe; resolver rejeita com lista de perfis.
        assert "profile" in r.stdout.lower()


class TestSyntheticRun:

    def test_time_compressed_synthetic_run(self, tmp_path):
        out = tmp_path / "report.json"
        tel = tmp_path / "telemetry.jsonl"
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--symbol", "BTCUSDT",
            "--strategy", "trend_pullback_bidirectional",
            "--duration-minutes", "5",
            "--cycle-interval-seconds", "60",
            "--demo-only", "--operator-token", "cli_test_op",
            "--synthetic-feed",
            "--output", str(out),
            "--telemetry-output", str(tel),
        )
        assert r.returncode == 0, r.stdout[-2000:]
        data = json.loads(out.read_text(encoding="utf-8"))
        oc = data["outcome"]
        # Campos obrigatorios + dry-run garantido.
        assert oc["real_time_mode"] is False
        assert oc["time_compressed"] is True
        assert oc["orders_submitted"] == 0
        assert oc["ended_reason"] != "order_completed"
        assert oc["expected_cycles"] == 5
        assert oc["cycles_completed"] <= 5
        assert "elapsed_wall_clock_seconds" in oc
        assert "elapsed_wall_clock_minutes" in oc
        assert data["preflight"]["approved"] is True
        # Telemetry JSONL existe e tem session_start/session_end.
        lines = tel.read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(ln)["event_type"] for ln in lines]
        assert "session_start" in events
        assert "session_end" in events
        # Sem secrets no report.
        text = out.read_text(encoding="utf-8").lower()
        for tok in ("api_key", "api_secret", "x-bapi"):
            assert tok not in text

    def test_preflight_only_exits_zero(self, tmp_path):
        out = tmp_path / "pf.json"
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--duration-minutes", "30", "--demo-only",
            "--operator-token", "T", "--synthetic-feed",
            "--preflight-only", "--output", str(out),
        )
        assert r.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["preflight"]["approved"] is True
        assert "outcome" not in data

    def test_long_demo_without_previous_report_warns(self, tmp_path):
        # Demo longa real-time de verdade levaria dias; usamos
        # preflight-only para validar o aviso sem rodar a janela.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--duration-days", "7", "--demo-only",
            "--operator-token", "T", "--synthetic-feed",
            "--preflight-only",
        )
        assert r.returncode == 0
        assert "previous-report" in r.stdout

    def test_max_would_orders_requires_continue_flag(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--duration-minutes", "30", "--demo-only",
            "--operator-token", "T", "--synthetic-feed",
            "--max-would-orders", "3",
        )
        assert r.returncode == 1
        assert "continue-after-would-order" in r.stdout

    def test_observation_mode_synthetic_run(self, tmp_path):
        out = tmp_path / "obs.json"
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback_bidirectional",
            "--duration-minutes", "5", "--demo-only",
            "--operator-token", "T", "--synthetic-feed",
            "--continue-after-would-order",
            "--max-would-orders", "2",
            "--output", str(out),
        )
        assert r.returncode == 0, r.stdout[-1500:]
        assert "OBSERVATION MODE" in r.stdout
        data = json.loads(out.read_text(encoding="utf-8"))
        oc = data["outcome"]
        assert oc["orders_submitted"] == 0
        assert oc["ended_reason"] in (
            "duration_completed", "passed_zero_trades",
            "max_would_orders_reached",
        )
        assert oc["session_summary"]["observation_mode"] is True

    def test_real_multi_requires_all_redundant_flags(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi",
        )
        assert r.returncode == 1
        assert "TODAS as flags" in r.stdout

    def test_real_multi_rejects_observation_mode(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
            "--max-real-orders", "2",
            "--continue-after-would-order",
        )
        assert r.returncode == 1
        assert "observation_mode" in r.stdout or \
            "incompativel" in r.stdout

    def test_real_multi_rejects_synthetic_feed(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
            "--max-real-orders", "2", "--synthetic-feed",
        )
        assert r.returncode == 1
        assert "synthetic" in r.stdout

    def test_real_multi_requires_real_time(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
            "--max-real-orders", "2",
        )
        assert r.returncode == 1
        assert "--real-time" in r.stdout

    def test_real_multi_requires_max_real_orders(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
        )
        assert r.returncode == 1
        assert "--max-real-orders" in r.stdout

    def test_real_multi_rejects_cap_above_3(self):
        r = _run(
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
            "--max-real-orders", "4",
        )
        assert r.returncode == 1
        assert "[1, 3]" in r.stdout

    def test_source_never_auto_executes_real_multi(self):
        src = _read_src()
        # Caminho real exige frase + prompt Y (nunca automatico).
        assert "expected_phrase_30_2" in src
        assert "prompt_yes_or_abort" in src

    def test_long_demo_with_missing_previous_report_blocks(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--duration-days", "7", "--demo-only",
            "--operator-token", "T", "--synthetic-feed",
            "--preflight-only",
            "--previous-report", "reports/_nope_does_not_exist.json",
        )
        assert r.returncode == 1
        assert "BLOCKER" in r.stdout
