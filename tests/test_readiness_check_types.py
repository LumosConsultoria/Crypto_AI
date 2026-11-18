"""
Testes — Tipos do DemoSessionReadinessCheck (FASE 19)
========================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Garante:
    - ReadinessGate enum tem valores estáveis (contrato).
    - ReadinessIssue é frozen, validado e serializável.
    - DemoSessionReadinessReport é frozen, validado e serializável.
    - blocking_reasons é tupla imutável.
    - Consistência interna: is_ready=True XOR existem issues 'error'.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_session_readiness import (
    DemoSessionReadinessReport,
    ReadinessGate,
    ReadinessIssue,
)


# ---------------------------------------------------------------------------
# ReadinessGate
# ---------------------------------------------------------------------------

class TestReadinessGate:

    def test_values_are_stable_contract(self):
        # Valores são contrato — qualquer mudança quebra audit/serializ.
        assert ReadinessGate.SAFETY_STATE.value == "safety_state"
        assert ReadinessGate.PROFILE_CHECK.value == "profile_check"
        assert ReadinessGate.PROVIDER_STATUS.value == "provider_status"
        assert ReadinessGate.RISK_CONFIG_SNAPSHOT.value == "risk_config_snapshot"
        assert ReadinessGate.LAST_FLAGS_CLEAN.value == "last_flags_clean"
        assert ReadinessGate.PREFLIGHT_LOCAL.value == "preflight_local"

    def test_exactly_six_gates(self):
        assert len(list(ReadinessGate)) == 6


# ---------------------------------------------------------------------------
# ReadinessIssue
# ---------------------------------------------------------------------------

class TestReadinessIssue:

    def test_frozen(self):
        issue = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE,
            severity="error",
            message="x",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            issue.severity = "warning"  # type: ignore[misc]

    def test_invalid_severity_raises(self):
        with pytest.raises(ValueError):
            ReadinessIssue(
                gate=ReadinessGate.SAFETY_STATE,
                severity="critical",  # inválido
                message="x",
            )

    def test_empty_message_raises(self):
        with pytest.raises(ValueError):
            ReadinessIssue(
                gate=ReadinessGate.SAFETY_STATE,
                severity="error",
                message="   ",
            )

    def test_gate_must_be_enum(self):
        with pytest.raises(TypeError):
            ReadinessIssue(
                gate="safety_state",  # type: ignore[arg-type]
                severity="error",
                message="x",
            )

    def test_is_blocking_property(self):
        e = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="error", message="x",
        )
        w = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="warning", message="x",
        )
        i = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="info", message="x",
        )
        assert e.is_blocking is True
        assert w.is_blocking is False
        assert i.is_blocking is False

    def test_to_dict_json_serializable(self):
        issue = ReadinessIssue(
            gate=ReadinessGate.LAST_FLAGS_CLEAN,
            severity="warning",
            message="x",
            detail="y",
        )
        encoded = json.dumps(issue.to_dict())
        decoded = json.loads(encoded)
        assert decoded["gate"] == "last_flags_clean"
        assert decoded["severity"] == "warning"
        assert decoded["detail"] == "y"


# ---------------------------------------------------------------------------
# DemoSessionReadinessReport
# ---------------------------------------------------------------------------

def _build_report(*, issues=(), is_ready=True, blocking=()) -> DemoSessionReadinessReport:
    return DemoSessionReadinessReport(
        profile_name="test",
        symbol="BTCUSDT",
        capital=5000.0,
        provider_id="bybit_demo_linear",
        evaluated_at=datetime.now(timezone.utc),
        is_ready_for_gated_demo=is_ready,
        gates_evaluated=tuple(ReadinessGate),
        issues=tuple(issues),
        blocking_reasons=tuple(blocking),
        notes="",
    )


class TestDemoSessionReadinessReport:

    def test_frozen(self):
        r = _build_report()
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.profile_name = "other"  # type: ignore[misc]

    def test_blocking_reasons_is_tuple(self):
        r = _build_report()
        assert isinstance(r.blocking_reasons, tuple)

    def test_gates_evaluated_is_tuple(self):
        r = _build_report()
        assert isinstance(r.gates_evaluated, tuple)

    def test_issues_is_tuple(self):
        r = _build_report()
        assert isinstance(r.issues, tuple)

    def test_naive_datetime_promoted_to_utc(self):
        naive = datetime(2026, 6, 2, 12, 0, 0)
        r = DemoSessionReadinessReport(
            profile_name="x",
            symbol="BTCUSDT",
            capital=1.0,
            provider_id="bybit_demo_linear",
            evaluated_at=naive,
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        assert r.evaluated_at.tzinfo is timezone.utc

    def test_inconsistent_ready_true_with_errors_raises(self):
        err = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="error", message="x",
        )
        with pytest.raises(ValueError):
            _build_report(issues=(err,), is_ready=True, blocking=("x",))

    def test_inconsistent_blocking_reasons_count_raises(self):
        err = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="error", message="x",
        )
        with pytest.raises(ValueError):
            # 1 error mas blocking_reasons vazio
            _build_report(issues=(err,), is_ready=False, blocking=())

    def test_blocking_reasons_must_match_errors(self):
        err1 = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="error", message="a",
        )
        err2 = ReadinessIssue(
            gate=ReadinessGate.PROVIDER_STATUS, severity="error", message="b",
        )
        r = _build_report(
            issues=(err1, err2), is_ready=False, blocking=("a", "b"),
        )
        assert r.blocking_reasons == ("a", "b")

    def test_total_counts_match_issues(self):
        issues = (
            ReadinessIssue(
                gate=ReadinessGate.SAFETY_STATE, severity="error", message="a",
            ),
            ReadinessIssue(
                gate=ReadinessGate.PROVIDER_STATUS, severity="warning", message="b",
            ),
            ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL, severity="info", message="c",
            ),
        )
        r = _build_report(issues=issues, is_ready=False, blocking=("a",))
        assert r.total_issues == 3
        assert r.total_blocks == 1
        assert r.total_warnings == 1
        assert r.total_info == 1

    def test_issues_by_gate_filters(self):
        i1 = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE, severity="error", message="a",
        )
        i2 = ReadinessIssue(
            gate=ReadinessGate.LAST_FLAGS_CLEAN, severity="warning", message="b",
        )
        r = _build_report(issues=(i1, i2), is_ready=False, blocking=("a",))
        s_issues = r.issues_by_gate(ReadinessGate.SAFETY_STATE)
        assert len(s_issues) == 1
        assert s_issues[0].message == "a"

    def test_to_dict_json_serializable(self):
        r = _build_report()
        encoded = json.dumps(r.to_dict())
        decoded = json.loads(encoded)
        assert decoded["provider_id"] == "bybit_demo_linear"
        assert decoded["is_ready_for_gated_demo"] is True
        assert isinstance(decoded["gates_evaluated"], list)
        assert isinstance(decoded["issues"], list)
        assert isinstance(decoded["blocking_reasons"], list)

    def test_to_dict_includes_total_blocks(self):
        r = _build_report()
        d = r.to_dict()
        assert "total_blocks" in d
        assert "total_warnings" in d
        assert "total_info" in d
        assert "total_issues" in d
