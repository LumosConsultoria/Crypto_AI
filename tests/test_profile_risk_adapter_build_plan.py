"""
Testes de build_risk_override_plan (FASE 18)
==============================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - Profile sem overrides → plan sem diffs, sem issues.
    - Override em chave existente → diff registrado.
    - Override em chave inexistente → issue 'error', is_apply_safe=False.
    - Override fora do range pydantic → issue 'error'.
    - Override redundante → issue 'info'.
    - account_size_usd divergente → issue 'warning'.
    - prop_challenge com max_daily_loss_pct alto → issue 'warning' (cross-config).
    - Diffs ordenados deterministicamente.
    - Função é pura (sem I/O).
    - Não levanta — sempre retorna plano.
    - Aceita os 4 builders de profile.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import (
    OperationalProfile,
    build_custom_profile,
    build_hyrotrader_demo_template,
    build_personal_profile,
    build_prop_challenge_profile,
    build_risk_override_plan,
)


def _base_rc(**kw):
    """RiskConfig com defaults; aceita overrides explícitos."""
    defaults = dict(
        account_size_usd=5000.0,
        max_daily_loss_pct=0.05,
        max_total_loss_pct=0.10,
        max_trades_per_day=10,
        max_open_positions=3,
        max_risk_per_trade_pct=0.01,
        max_leverage=3.0,
    )
    defaults.update(kw)
    return RiskConfig(**defaults)


# ---------------------------------------------------------------------------
# Profile sem overrides
# ---------------------------------------------------------------------------

class TestNoOverrides:

    def test_personal_no_overrides_yields_empty_plan(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = build_risk_override_plan(profile, _base_rc())
        # Todas as diffs com changed=False (sem mudança proposta)
        assert all(d.changed is False for d in plan.diffs)
        # Sem issues (sem overrides, sem divergência)
        assert plan.issues == ()
        assert plan.requires_confirmation is False
        assert plan.is_apply_safe is True


# ---------------------------------------------------------------------------
# Override em chave existente → diff real
# ---------------------------------------------------------------------------

class TestRealDiff:

    def test_override_max_daily_loss_creates_diff(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        plan = build_risk_override_plan(profile, _base_rc())
        diff = next(
            d for d in plan.diffs if d.field == "max_daily_loss_pct"
        )
        assert diff.base_value == 0.05
        assert diff.proposed_value == 0.03
        assert diff.changed is True
        assert plan.requires_confirmation is True
        assert plan.is_apply_safe is True


# ---------------------------------------------------------------------------
# Chave desconhecida → error
# ---------------------------------------------------------------------------

class TestUnknownKeyError:

    def test_unknown_key_is_error(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"this_key_does_not_exist": 1.0},
        )
        plan = build_risk_override_plan(profile, _base_rc())
        errors = [i for i in plan.issues if i.severity == "error"]
        assert any("this_key_does_not_exist" in i.message for i in errors)
        assert plan.is_apply_safe is False


# ---------------------------------------------------------------------------
# Valor fora do range pydantic → error
# ---------------------------------------------------------------------------

class TestInvalidValueError:

    def test_value_above_range_is_error(self):
        # max_daily_loss_pct tem le=1.0
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 2.0},
        )
        plan = build_risk_override_plan(profile, _base_rc())
        assert plan.is_apply_safe is False
        assert any(
            i.severity == "error" and i.key
            and "max_daily_loss_pct" in (i.key or "")
            for i in plan.issues
        )

    def test_value_below_range_is_error(self):
        # max_leverage ge=1.0
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_leverage": 0.5},
        )
        plan = build_risk_override_plan(profile, _base_rc())
        assert plan.is_apply_safe is False


# ---------------------------------------------------------------------------
# Redundante → info
# ---------------------------------------------------------------------------

class TestRedundantInfo:

    def test_redundant_override_is_info(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.05},  # igual ao base
        )
        plan = build_risk_override_plan(profile, _base_rc())
        info_issues = [i for i in plan.issues if i.severity == "info"]
        assert any("redundante" in i.message for i in info_issues)
        # is_apply_safe permanece True
        assert plan.is_apply_safe is True


# ---------------------------------------------------------------------------
# account_size_usd divergente → warning
# ---------------------------------------------------------------------------

class TestAccountSizeDivergence:

    def test_capital_divergence_is_warning(self):
        # Profile diz 10000; RiskConfig base diz 5000
        profile = build_personal_profile(account_size_usd=10000.0)
        plan = build_risk_override_plan(
            profile, _base_rc(account_size_usd=5000.0),
        )
        warnings = [i for i in plan.issues if i.severity == "warning"]
        assert any(
            "account_size_usd" in (i.key or "") for i in warnings
        )
        # Warning não bloqueia apply
        assert plan.is_apply_safe is True


# ---------------------------------------------------------------------------
# prop_challenge + max_daily_loss alto → warning (cross-config FASE 16)
# ---------------------------------------------------------------------------

class TestPropChallengeCrossConfigWarning:

    def test_prop_challenge_with_loose_daily_loss_warns(self):
        profile = build_prop_challenge_profile(account_size_usd=5000.0)
        # RiskConfig base com max_daily_loss_pct alto (não compatível
        # com prop challenge típico)
        plan = build_risk_override_plan(
            profile, _base_rc(max_daily_loss_pct=0.10),
        )
        warnings = [i for i in plan.issues if i.severity == "warning"]
        assert any(
            "max_daily_loss_pct" in i.message for i in warnings
        )


# ---------------------------------------------------------------------------
# Determinismo + pureza
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_diffs_ordered_alphabetically_by_field(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={
                "max_leverage": 2.0,
                "max_daily_loss_pct": 0.03,
                "max_open_positions": 2,
            },
        )
        plan = build_risk_override_plan(profile, _base_rc())
        fields = [d.field for d in plan.diffs]
        assert fields == sorted(fields)

    def test_pure_function_idempotent(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = _base_rc()
        p1 = build_risk_override_plan(profile, base)
        p2 = build_risk_override_plan(profile, base)
        assert p1.to_dict() == p2.to_dict()


# ---------------------------------------------------------------------------
# Não levanta em entradas razoáveis
# ---------------------------------------------------------------------------

class TestNeverRaises:

    @pytest.mark.parametrize("builder,kwargs", [
        (build_personal_profile, {"account_size_usd": 5000.0}),
        (build_prop_challenge_profile, {"account_size_usd": 5000.0}),
        (build_hyrotrader_demo_template, {"account_size_usd": 5000.0}),
        (build_custom_profile, {"name": "x", "description": "y"}),
    ])
    def test_all_builders_produce_valid_plan(self, builder, kwargs):
        profile = builder(**kwargs)
        plan = build_risk_override_plan(profile, _base_rc())
        # Sempre retorna plano (mesmo que com issues)
        assert plan.profile_name == profile.name


# ---------------------------------------------------------------------------
# Validação de argumentos
# ---------------------------------------------------------------------------

class TestArgValidation:

    def test_rejects_non_profile(self):
        with pytest.raises(TypeError, match="profile"):
            build_risk_override_plan(
                "not_a_profile",  # type: ignore[arg-type]
                _base_rc(),
            )

    def test_rejects_non_risk_config(self):
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(TypeError, match="RiskConfig"):
            build_risk_override_plan(
                profile,
                "not_a_risk_config",  # type: ignore[arg-type]
            )
