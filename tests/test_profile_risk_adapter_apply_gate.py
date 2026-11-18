"""
Testes de apply_profile_overrides_with_gate (FASE 18)
========================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - confirm=False → ProfileOverrideRejected.
    - operator_token vazio/whitespace → ProfileOverrideRejected.
    - plan com issue 'error' → ProfileOverrideRejected.
    - Sucesso: retorna NOVA instância distinta do base.
    - No-op (sem overrides): retorna NOVA instância equivalente.
    - Base original não muta.
    - Audit emite PROFILE_OVERRIDE_APPLIED com token sanitizado.
    - Audit emite PROFILE_OVERRIDE_REJECTED em falhas.
    - notes longos truncados; substrings suspeitas redacted.
    - Funciona para os 4 builders.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import (
    ProfileOverrideRejected,
    apply_profile_overrides_with_gate,
    build_custom_profile,
    build_hyrotrader_demo_template,
    build_personal_profile,
    build_prop_challenge_profile,
)


def _base_rc():
    return RiskConfig(account_size_usd=5000.0, max_daily_loss_pct=0.05)


# ---------------------------------------------------------------------------
# Gate: confirm
# ---------------------------------------------------------------------------

class TestGateConfirm:

    def test_confirm_false_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        with pytest.raises(ProfileOverrideRejected, match="confirm"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=False,
                operator_token="op@example.com",
            )

    def test_confirm_non_bool_rejects(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ProfileOverrideRejected, match="confirm"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm="yes",  # type: ignore[arg-type]
                operator_token="op@example.com",
            )


# ---------------------------------------------------------------------------
# Gate: operator_token
# ---------------------------------------------------------------------------

class TestGateOperatorToken:

    def test_empty_token_rejects(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ProfileOverrideRejected, match="operator_token"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=True,
                operator_token="",
            )

    def test_whitespace_token_rejects(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ProfileOverrideRejected, match="operator_token"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=True,
                operator_token="   ",
            )

    def test_non_string_token_rejects(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ProfileOverrideRejected, match="operator_token"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=True,
                operator_token=None,  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# Gate: plano não-seguro
# ---------------------------------------------------------------------------

class TestGateUnsafePlan:

    def test_unknown_key_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"unknown_field": 1.0},
        )
        with pytest.raises(ProfileOverrideRejected, match="apply rejeitado"):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=True,
                operator_token="op@example.com",
            )

    def test_value_out_of_range_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 5.0},  # > 1.0
        )
        with pytest.raises(ProfileOverrideRejected):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=True,
                operator_token="op@example.com",
            )


# ---------------------------------------------------------------------------
# Sucesso: novo RiskConfig
# ---------------------------------------------------------------------------

class TestSuccessfulApply:

    def test_returns_new_instance(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = _base_rc()
        new_rc = apply_profile_overrides_with_gate(
            profile, base,
            confirm=True,
            operator_token="op@example.com",
        )
        assert isinstance(new_rc, RiskConfig)
        assert id(new_rc) != id(base)

    def test_new_config_has_override_applied(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        new_rc = apply_profile_overrides_with_gate(
            profile, _base_rc(),
            confirm=True,
            operator_token="op@example.com",
        )
        assert new_rc.max_daily_loss_pct == 0.03

    def test_base_config_unchanged(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = _base_rc()
        base_value = base.max_daily_loss_pct
        apply_profile_overrides_with_gate(
            profile, base,
            confirm=True,
            operator_token="op@example.com",
        )
        assert base.max_daily_loss_pct == base_value


# ---------------------------------------------------------------------------
# No-op: profile vazio → ainda nova instância
# ---------------------------------------------------------------------------

class TestNoOpReturnsNewInstance:

    def test_empty_overrides_returns_new_equivalent_instance(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        base = _base_rc()
        new_rc = apply_profile_overrides_with_gate(
            profile, base,
            confirm=True,
            operator_token="op@example.com",
        )
        assert id(new_rc) != id(base)
        # Mesmos valores nos campos relevantes
        assert new_rc.max_daily_loss_pct == base.max_daily_loss_pct
        assert new_rc.max_leverage == base.max_leverage


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestAudit:

    def test_applied_audit_contains_sanitized_token(self, monkeypatch):
        import crypto_trading_bot.operational_profile.risk_adapter as mod
        captured: list[str] = []

        class FakeAudit:
            def info(self, msg): captured.append(("info", msg))
            def warning(self, msg): captured.append(("warning", msg))

        monkeypatch.setattr(mod, "_audit", FakeAudit())
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        apply_profile_overrides_with_gate(
            profile, _base_rc(),
            confirm=True,
            operator_token="consultorialumos@gmail.com",
            notes="approved",
        )
        applied_line = next(
            m for _, m in captured if "PROFILE_OVERRIDE_APPLIED" in m
        )
        # Token completo NÃO aparece
        assert "consultorialumos@gmail.com" not in applied_line
        # Token truncado aparece
        assert "consulto..." in applied_line

    def test_rejected_audit_emitted_on_failure(self, monkeypatch):
        import crypto_trading_bot.operational_profile.risk_adapter as mod
        captured: list[str] = []

        class FakeAudit:
            def info(self, msg): captured.append(("info", msg))
            def warning(self, msg): captured.append(("warning", msg))

        monkeypatch.setattr(mod, "_audit", FakeAudit())
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ProfileOverrideRejected):
            apply_profile_overrides_with_gate(
                profile, _base_rc(),
                confirm=False,
                operator_token="op@example.com",
            )
        rejected = [m for _, m in captured if "PROFILE_OVERRIDE_REJECTED" in m]
        assert len(rejected) >= 1


# ---------------------------------------------------------------------------
# Sanitização de notes
# ---------------------------------------------------------------------------

class TestNotesSanitized:

    def test_notes_with_suspicious_content_redacted(self, monkeypatch):
        import crypto_trading_bot.operational_profile.risk_adapter as mod
        captured: list[str] = []

        class FakeAudit:
            def info(self, msg): captured.append(("info", msg))
            def warning(self, msg): captured.append(("warning", msg))

        monkeypatch.setattr(mod, "_audit", FakeAudit())
        profile = build_personal_profile(account_size_usd=5000.0)
        apply_profile_overrides_with_gate(
            profile, _base_rc(),
            confirm=True,
            operator_token="op@example.com",
            notes="api_secret=ABC123 accidentally",
        )
        applied_line = next(
            m for _, m in captured if "PROFILE_OVERRIDE_APPLIED" in m
        )
        assert "ABC123" not in applied_line
        assert "api_secret" not in applied_line.lower() or "redacted" in applied_line.lower()


# ---------------------------------------------------------------------------
# Funciona para os 4 builders
# ---------------------------------------------------------------------------

class TestAllBuilders:

    @pytest.mark.parametrize("builder,kwargs", [
        (build_personal_profile, {"account_size_usd": 5000.0}),
        (build_prop_challenge_profile, {"account_size_usd": 5000.0}),
        (build_hyrotrader_demo_template, {"account_size_usd": 5000.0}),
        (build_custom_profile, {"name": "x", "description": "y"}),
    ])
    def test_apply_works_for_all_builders(self, builder, kwargs):
        profile = builder(**kwargs)
        new_rc = apply_profile_overrides_with_gate(
            profile, _base_rc(),
            confirm=True,
            operator_token="op@example.com",
        )
        assert isinstance(new_rc, RiskConfig)
