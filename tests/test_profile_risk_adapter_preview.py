"""
Testes de preview_profile_risk_config (FASE 18)
=================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - Preview retorna AppliedRiskConfigSnapshot com was_applied=False.
    - Preview com profile vazio retorna snapshot equivalente ao base.
    - Preview NÃO emite PROFILE_OVERRIDE_APPLIED (apenas PROFILE_OVERRIDE_PLAN).
    - Múltiplas chamadas idempotentes.
    - Preview em profile com issues 'error' retorna snapshot (marca issues).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import (
    AppliedRiskConfigSnapshot,
    build_personal_profile,
    preview_profile_risk_config,
)


def _base_rc():
    return RiskConfig(account_size_usd=5000.0)


# ---------------------------------------------------------------------------
# Resultados básicos
# ---------------------------------------------------------------------------

class TestPreviewBasic:

    def test_returns_applied_snapshot(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        snap = preview_profile_risk_config(profile, _base_rc())
        assert isinstance(snap, AppliedRiskConfigSnapshot)

    def test_was_applied_false(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        snap = preview_profile_risk_config(profile, _base_rc())
        assert snap.was_applied is False

    def test_token_sanitized_for_preview(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        snap = preview_profile_risk_config(profile, _base_rc())
        # Preview usa placeholder "<preview>" no token
        assert snap.operator_token_sanitized == "<preview>"


# ---------------------------------------------------------------------------
# Empty overrides → snapshot equivalente ao base
# ---------------------------------------------------------------------------

class TestEmptyOverrides:

    def test_empty_overrides_snapshot_matches_base(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        base = _base_rc()
        snap = preview_profile_risk_config(profile, base)
        # Não há diffs reais
        assert not any(d.changed for d in snap.diff_summary)


# ---------------------------------------------------------------------------
# Preview NÃO modifica base
# ---------------------------------------------------------------------------

class TestPreviewDoesNotMutateBase:

    def test_base_risk_config_unchanged_after_preview(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = _base_rc()
        base_value_before = base.max_daily_loss_pct
        preview_profile_risk_config(profile, base)
        assert base.max_daily_loss_pct == base_value_before


# ---------------------------------------------------------------------------
# Preview NÃO emite PROFILE_OVERRIDE_APPLIED
# ---------------------------------------------------------------------------

class TestPreviewNoAppliedAuditLine:

    def test_no_applied_audit_emitted(self, monkeypatch):
        import crypto_trading_bot.operational_profile.risk_adapter as mod
        captured: list[str] = []

        class FakeAudit:
            def info(self, msg):
                captured.append(("info", msg))

            def warning(self, msg):
                captured.append(("warning", msg))

        monkeypatch.setattr(mod, "_audit", FakeAudit())
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        preview_profile_risk_config(profile, _base_rc())
        # PROFILE_OVERRIDE_PLAN é emitido (do build_risk_override_plan interno),
        # mas APPLIED não.
        applied = [
            m for _, m in captured if "PROFILE_OVERRIDE_APPLIED" in m
        ]
        assert applied == []


# ---------------------------------------------------------------------------
# Múltiplas chamadas idempotentes
# ---------------------------------------------------------------------------

class TestIdempotent:

    def test_multiple_calls_same_result(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = _base_rc()
        s1 = preview_profile_risk_config(profile, base)
        s2 = preview_profile_risk_config(profile, base)
        # Igualdade de diff_summary (ignorando applied_at)
        assert s1.diff_summary == s2.diff_summary
        assert s1.profile_name == s2.profile_name
        assert dict(s1.final_config) == dict(s2.final_config)


# ---------------------------------------------------------------------------
# Preview com error ainda retorna snapshot
# ---------------------------------------------------------------------------

class TestPreviewWithErrors:

    def test_preview_with_error_returns_snapshot(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"unknown_key": 1.0},
        )
        snap = preview_profile_risk_config(profile, _base_rc())
        # Retorna snapshot com issues marcadas
        assert any(
            i.severity == "error" for i in snap.issues_at_apply
        )
        # was_applied permanece False
        assert snap.was_applied is False
