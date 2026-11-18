"""
Testes dos tipos imutáveis do risk_adapter (FASE 18)
======================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - ProfileRiskOverrideIssue frozen + severity válida.
    - FieldDiff frozen.
    - ProfileRiskOverridePlan: MappingProxyType + tuple.
    - AppliedRiskConfigSnapshot: timestamp UTC, token sanitizado.
    - to_dict JSON-serializável em todos os tipos.
    - ProfileOverrideRejected é RuntimeError.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.operational_profile import (
    AppliedRiskConfigSnapshot,
    FieldDiff,
    ProfileOverrideRejected,
    ProfileRiskOverrideIssue,
    ProfileRiskOverridePlan,
)


# ---------------------------------------------------------------------------
# ProfileRiskOverrideIssue
# ---------------------------------------------------------------------------

class TestIssue:

    def test_frozen(self):
        i = ProfileRiskOverrideIssue(
            severity="warning", key="max_daily_loss_pct", message="x",
        )
        with pytest.raises(Exception):
            i.severity = "error"  # type: ignore[misc]

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValueError, match="severity"):
            ProfileRiskOverrideIssue(severity="critical", key=None, message="x")

    def test_empty_message_rejected(self):
        with pytest.raises(ValueError, match="message"):
            ProfileRiskOverrideIssue(severity="info", key=None, message="")

    def test_key_can_be_none(self):
        i = ProfileRiskOverrideIssue(
            severity="warning", key=None, message="general issue",
        )
        assert i.key is None

    def test_to_dict_json_serializable(self):
        i = ProfileRiskOverrideIssue(
            severity="error", key="max_leverage", message="out of range",
        )
        d = i.to_dict()
        json.dumps(d)
        assert d["severity"] == "error"
        assert d["key"] == "max_leverage"


# ---------------------------------------------------------------------------
# FieldDiff
# ---------------------------------------------------------------------------

class TestFieldDiff:

    def test_frozen(self):
        d = FieldDiff(
            field="x", base_value=1, proposed_value=2, changed=True,
        )
        with pytest.raises(Exception):
            d.field = "y"  # type: ignore[misc]

    def test_equality_by_value(self):
        d1 = FieldDiff(field="a", base_value=1, proposed_value=2, changed=True)
        d2 = FieldDiff(field="a", base_value=1, proposed_value=2, changed=True)
        assert d1 == d2

    def test_to_dict_json_serializable(self):
        d = FieldDiff(
            field="account_size_usd", base_value=5000.0,
            proposed_value=10000.0, changed=True,
        )
        json.dumps(d.to_dict())


# ---------------------------------------------------------------------------
# ProfileRiskOverridePlan
# ---------------------------------------------------------------------------

class TestPlan:

    def _make(self, **kw):
        defaults = dict(
            profile_name="x",
            base_config={"a": 1},
            proposed_config={"a": 1},
            diffs=(),
            issues=(),
            is_apply_safe=True,
            requires_confirmation=False,
        )
        defaults.update(kw)
        return ProfileRiskOverridePlan(**defaults)

    def test_frozen(self):
        p = self._make()
        with pytest.raises(Exception):
            p.profile_name = "y"  # type: ignore[misc]

    def test_snapshots_become_mappingproxy(self):
        p = self._make(
            base_config={"a": 1, "b": 2},
            proposed_config={"a": 1, "b": 3},
        )
        assert isinstance(p.base_config, MappingProxyType)
        assert isinstance(p.proposed_config, MappingProxyType)
        with pytest.raises(TypeError):
            p.base_config["a"] = 99  # type: ignore[index]

    def test_diffs_and_issues_are_tuples(self):
        diff = FieldDiff(field="a", base_value=1, proposed_value=2, changed=True)
        issue = ProfileRiskOverrideIssue(
            severity="info", key="a", message="redundant",
        )
        p = self._make(diffs=[diff], issues=[issue])
        assert isinstance(p.diffs, tuple)
        assert isinstance(p.issues, tuple)

    def test_has_errors_and_warnings_properties(self):
        err = ProfileRiskOverrideIssue(severity="error", key=None, message="e")
        warn = ProfileRiskOverrideIssue(severity="warning", key=None, message="w")
        p = self._make(issues=(err, warn))
        assert p.has_errors is True
        assert p.has_warnings is True

    def test_to_dict_json_serializable(self):
        p = self._make(
            diffs=(FieldDiff("a", 1, 2, True),),
            issues=(ProfileRiskOverrideIssue("info", "a", "redundant"),),
        )
        json.dumps(p.to_dict())


# ---------------------------------------------------------------------------
# AppliedRiskConfigSnapshot
# ---------------------------------------------------------------------------

class TestAppliedSnapshot:

    def test_frozen(self):
        s = AppliedRiskConfigSnapshot(
            profile_name="x",
            applied_at=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            operator_token_sanitized="abc...",
            final_config={"a": 1},
            diff_summary=(),
            issues_at_apply=(),
            was_applied=False,
        )
        with pytest.raises(Exception):
            s.was_applied = True  # type: ignore[misc]

    def test_naive_timestamp_promoted_to_utc(self):
        s = AppliedRiskConfigSnapshot(
            profile_name="x",
            applied_at=datetime(2026, 6, 1, 12, 0, 0),  # naive
            operator_token_sanitized="x",
            final_config={},
            diff_summary=(),
            issues_at_apply=(),
            was_applied=False,
        )
        assert s.applied_at.tzinfo == timezone.utc

    def test_final_config_becomes_mappingproxy(self):
        s = AppliedRiskConfigSnapshot(
            profile_name="x",
            applied_at=datetime.now(timezone.utc),
            operator_token_sanitized="x",
            final_config={"a": 1},
            diff_summary=(),
            issues_at_apply=(),
            was_applied=False,
        )
        assert isinstance(s.final_config, MappingProxyType)

    def test_to_dict_json_serializable(self):
        s = AppliedRiskConfigSnapshot(
            profile_name="x",
            applied_at=datetime.now(timezone.utc),
            operator_token_sanitized="abc...",
            final_config={"a": 1},
            diff_summary=(FieldDiff("a", 0, 1, True),),
            issues_at_apply=(ProfileRiskOverrideIssue("info", "a", "x"),),
            was_applied=True,
        )
        json.dumps(s.to_dict())


# ---------------------------------------------------------------------------
# ProfileOverrideRejected
# ---------------------------------------------------------------------------

class TestExceptionType:

    def test_is_runtime_error(self):
        assert issubclass(ProfileOverrideRejected, RuntimeError)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(ProfileOverrideRejected, match="x"):
            raise ProfileOverrideRejected("x")
