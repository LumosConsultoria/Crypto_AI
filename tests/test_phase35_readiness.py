"""
Tests - FASE 35: readiness supervisionado
==========================================
100% offline. Le apenas JSON locais (tmp_path). ZERO rede/ordem.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from crypto_trading_bot.operational_profile import resolve_profile
from crypto_trading_bot.readiness import (
    ReadinessEvidence,
    ReadinessVerdict,
    collect_evidence_from_reports_dir,
    evaluate_supervised_readiness,
    run_supervised_readiness_from_dir,
)

_REPO_ROOT = Path(__file__).parent.parent


def _good_evidence(**kw) -> ReadinessEvidence:
    base = dict(
        total_sessions=3,
        short_demo_clean_count=1,
        short_demo_completed_count=2,
        long_demo_completed_count=1,
        profile_compliance_ok=True,
    )
    base.update(kw)
    return ReadinessEvidence(**base)


class TestVerdicts:

    def test_ready_when_minimum_criteria_met(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(), profile_name="personal",
        )
        assert report.verdict is ReadinessVerdict.READY
        assert report.is_ready
        assert report.blockers == ()

    def test_not_ready_without_short_demo(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(short_demo_clean_count=0),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY
        assert any("demo curta" in b for b in report.blockers)

    def test_not_ready_without_long_demo(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(long_demo_completed_count=0),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY
        assert any("demo longa" in b for b in report.blockers)

    def test_justification_can_substitute_demo(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(
                long_demo_completed_count=0,
                justifications=(
                    "long_demo adiada: janela macro instavel",
                ),
            ),
        )
        assert report.verdict is ReadinessVerdict.READY

    def test_insufficient_history(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(total_sessions=1),
        )
        assert report.verdict is ReadinessVerdict.INSUFFICIENT_HISTORY

    def test_manual_review_with_safety_event(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(safety_events_total=1),
        )
        assert report.verdict is \
            ReadinessVerdict.MANUAL_REVIEW_REQUIRED

    def test_manual_review_with_ai_critical_veto(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(ai_critical_vetoes=1),
        )
        assert report.verdict is \
            ReadinessVerdict.MANUAL_REVIEW_REQUIRED

    def test_manual_review_with_prediction_critical(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(prediction_critical_unhandled=1),
        )
        assert report.verdict is \
            ReadinessVerdict.MANUAL_REVIEW_REQUIRED

    def test_not_ready_with_residual_position(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(residual_positions=1),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY

    def test_not_ready_with_missing_sl_tp(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(orders_missing_sl_tp=1),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY

    def test_not_ready_with_risk_violations(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(risk_violations_total=2),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY

    def test_not_ready_with_overfitting_critical(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(advisor_overfitting_critical=1),
        )
        assert report.verdict is ReadinessVerdict.NOT_READY


class TestGatesInReadiness:

    def test_blocks_short_without_validation(self):
        profile = resolve_profile(
            "personal", capital=5000.0, allow_short_demo=True,
        )
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(short_validated=False),
            profile=profile,
        )
        assert report.verdict is ReadinessVerdict.NOT_READY
        assert any("short" in b for b in report.blockers)

    def test_blocks_multi_order_without_gate(self):
        profile = resolve_profile(
            "personal", capital=5000.0, allow_multi_order_demo=True,
        )
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(multi_order_gate_validated=False),
            profile=profile,
        )
        assert report.verdict is ReadinessVerdict.NOT_READY
        assert any("multi-order" in b for b in report.blockers)

    def test_short_ok_when_validated(self):
        profile = resolve_profile(
            "personal", capital=5000.0, allow_short_demo=True,
        )
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(short_validated=True),
            profile=profile,
        )
        assert report.verdict is ReadinessVerdict.READY


class TestWarningsConsidered:

    def test_ai_and_prediction_warnings_in_report(self):
        report = evaluate_supervised_readiness(
            evidence=_good_evidence(
                ai_warnings_total=3, prediction_warnings_total=2,
            ),
        )
        # Warnings consultivos nao bloqueiam sozinhos...
        assert report.verdict is ReadinessVerdict.READY
        # ...mas SAO considerados/registrados.
        text = " ".join(report.warnings)
        assert "ai_warnings_total=3" in text
        assert "prediction_warnings_total=2" in text


class TestEvidenceCollection:

    def _write(self, path: Path, payload: dict) -> None:
        path.write_text(
            json.dumps(payload, default=str), encoding="utf-8",
        )

    def test_collects_from_phase30_and_phase29_reports(self, tmp_path):
        # FASE 30 endurance longa concluida.
        self._write(tmp_path / "endur_7d.json", {
            "phase": "30",
            "outcome": {
                "ended_reason": "duration_completed",
                "configured_duration_days": 7,
                "configured_duration_minutes": None,
                "api_failures": 1, "safety_events": 0,
                "session_summary": {"ai_warnings": ["w1"]},
            },
        })
        # FASE 29 A_clean.
        self._write(tmp_path / "demo29.json", {
            "outcome": {
                "demo_finalization_scenario": "A_clean",
                "open_positions_count": 0,
                "open_orders_count": 0,
                "risk_violations_count": 0,
                "orders_submitted": 1,
                "pnl_realized_usd": 1.25,
                "sl_attached": True, "tp_attached": True,
            },
        })
        # Advisor com overfitting.
        self._write(tmp_path / "advisor.json", {
            "candidate_strategy": "trend_pullback_bidirectional",
            "ranking": [{"overfitting_warning": True}],
        })
        # Arquivo invalido eh ignorado.
        (tmp_path / "broken.json").write_text(
            "{not json", encoding="utf-8",
        )

        evidence, scanned = collect_evidence_from_reports_dir(
            str(tmp_path),
        )
        assert scanned == 3
        assert evidence.total_sessions == 2
        assert evidence.long_demo_completed_count == 1
        assert evidence.short_demo_clean_count == 1
        assert evidence.advisor_overfitting_critical == 1
        assert evidence.ai_warnings_total == 1
        assert evidence.api_failures_total == 1

    def test_end_to_end_from_dir(self, tmp_path):
        self._write(tmp_path / "a.json", {
            "outcome": {"demo_finalization_scenario": "A_clean",
                        "open_positions_count": 0,
                        "open_orders_count": 0,
                        "risk_violations_count": 0,
                        "orders_submitted": 1,
                        "pnl_realized_usd": 0.5,
                        "sl_attached": True, "tp_attached": True},
        })
        self._write(tmp_path / "b.json", {
            "outcome": {"ended_reason": "duration_completed",
                        "configured_duration_days": 1,
                        "configured_duration_minutes": None},
        })
        report = run_supervised_readiness_from_dir(
            reports_dir=str(tmp_path), profile_name="personal",
        )
        assert report.verdict is ReadinessVerdict.READY
        d = report.to_dict()
        assert "live" in d["note"]  # aviso consultivo presente
        assert d["reports_scanned"] == 2


class TestReadinessCLI:

    def test_cli_runs_offline(self, tmp_path):
        (tmp_path / "a.json").write_text(json.dumps({
            "outcome": {"demo_finalization_scenario": "A_clean",
                        "open_positions_count": 0,
                        "open_orders_count": 0,
                        "risk_violations_count": 0,
                        "orders_submitted": 1,
                        "pnl_realized_usd": 0.5,
                        "sl_attached": True, "tp_attached": True},
        }), encoding="utf-8")
        (tmp_path / "b.json").write_text(json.dumps({
            "outcome": {"ended_reason": "duration_completed",
                        "configured_duration_days": 1,
                        "configured_duration_minutes": None},
        }), encoding="utf-8")
        out = tmp_path / "readiness.json"
        script = _REPO_ROOT / "scripts" / "run_supervised_readiness.py"
        r = subprocess.run(
            [sys.executable, str(script),
             "--profile", "personal",
             "--reports-dir", str(tmp_path),
             "--output", str(out)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=120, check=False,
        )
        assert r.returncode == 0, r.stdout[-1500:]
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "ready"
        assert "NAO habilita" in data["note"]

    def test_cli_source_has_no_dotenv_or_network(self):
        src = (
            _REPO_ROOT / "scripts" / "run_supervised_readiness.py"
        ).read_text(encoding="utf-8")
        assert "load_dotenv" not in src
        assert "httpx" not in src
        assert "requests" not in src
