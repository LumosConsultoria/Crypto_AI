"""
Testes de factories de OperationalProfile (FASE 16)
=====================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - build_personal_profile com capital customizado.
    - build_prop_challenge_profile marca flags corretamente.
    - build_hyrotrader_demo_template é editável (overrides aplicáveis).
    - build_custom_profile aceita campos arbitrários.
    - Builders rejeitam capital <= 0.
    - Nenhum builder depende de provider_name == "HyroTrader".
    - Nenhum builder define max_profit_usd obrigatório.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.operational_profile import (
    OperationalProfile,
    build_custom_profile,
    build_hyrotrader_demo_template,
    build_personal_profile,
    build_prop_challenge_profile,
)


# ---------------------------------------------------------------------------
# Personal
# ---------------------------------------------------------------------------

class TestBuildPersonal:

    def test_basic_build(self):
        p = build_personal_profile(account_size_usd=5000.0)
        assert p.provider_type == "personal"
        assert p.is_prop_firm is False
        assert p.is_challenge_account is False
        assert p.is_funded_account is False
        assert p.account_size_usd == 5000.0
        assert p.kill_switch_enabled is False
        assert p.conservative_mode is False

    def test_accepts_custom_capital(self):
        p = build_personal_profile(account_size_usd=1234.56)
        assert p.account_size_usd == 1234.56

    def test_rejects_zero_capital(self):
        with pytest.raises(ValueError, match="account_size_usd"):
            build_personal_profile(account_size_usd=0)

    def test_rejects_negative_capital(self):
        with pytest.raises(ValueError, match="account_size_usd"):
            build_personal_profile(account_size_usd=-100)

    def test_overrides_applied(self):
        p = build_personal_profile(
            account_size_usd=5000.0,
            max_concurrent_positions=3,
            kill_switch_enabled=True,
            allowed_symbols=("BTCUSDT", "ETHUSDT"),
        )
        assert p.max_concurrent_positions == 3
        assert p.kill_switch_enabled is True
        assert p.allowed_symbols == ("BTCUSDT", "ETHUSDT")


# ---------------------------------------------------------------------------
# Prop challenge
# ---------------------------------------------------------------------------

class TestBuildPropChallenge:

    def test_marks_flags_correctly(self):
        p = build_prop_challenge_profile(account_size_usd=5000.0)
        assert p.provider_type == "prop_challenge"
        assert p.is_prop_firm is True
        assert p.is_challenge_account is True
        assert p.is_funded_account is False
        assert p.kill_switch_enabled is True
        assert p.conservative_mode is True

    def test_overrides_can_disable_kill_switch(self):
        p = build_prop_challenge_profile(
            account_size_usd=5000.0,
            kill_switch_enabled=False,
        )
        assert p.kill_switch_enabled is False


# ---------------------------------------------------------------------------
# HyroTrader template (editável)
# ---------------------------------------------------------------------------

class TestBuildHyroTraderTemplate:

    def test_marked_as_template_editable(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        desc_lower = p.description.lower()
        assert "template" in desc_lower
        assert "edit" in desc_lower  # "editável" / "editar" / "editado"

    def test_defaults_conservative(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert p.is_prop_firm is True
        assert p.is_challenge_account is True
        assert p.is_funded_account is False
        assert p.kill_switch_enabled is True
        assert p.conservative_mode is True
        assert p.require_manual_ack_on_triangulation is True

    def test_overrides_apply(self):
        p = build_hyrotrader_demo_template(
            account_size_usd=10000.0,
            max_concurrent_positions=2,
            allowed_symbols=("BTCUSDT",),
        )
        assert p.account_size_usd == 10000.0
        assert p.max_concurrent_positions == 2
        assert p.allowed_symbols == ("BTCUSDT",)

    def test_no_max_profit_field_exists(self):
        """Nenhum max_profit_usd obrigatório — challenge target é apenas KPI."""
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        # Garantia estrutural: campo não existe no dataclass
        assert not hasattr(p, "max_profit_usd")

    def test_does_not_depend_on_provider_name_hyrotrader(self):
        """Diferenciação via flags estruturados, não por provider_name."""
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        # OperationalProfile não tem provider_name; usa provider_type+flags
        assert not hasattr(p, "provider_name")

    def test_overrides_can_change_description(self):
        p = build_hyrotrader_demo_template(
            account_size_usd=5000.0,
            description="Edited by operator with real HyroTrader rules.",
        )
        assert "Edited by operator" in p.description


# ---------------------------------------------------------------------------
# Custom
# ---------------------------------------------------------------------------

class TestBuildCustom:

    def test_basic(self):
        p = build_custom_profile(
            name="my_custom",
            description="My custom profile",
        )
        assert p.name == "my_custom"
        assert p.provider_type == "custom"
        assert p.account_size_usd is None

    def test_allows_account_size_none(self):
        p = build_custom_profile(name="x", description="y")
        assert p.account_size_usd is None

    def test_with_capital(self):
        p = build_custom_profile(
            name="x", description="y", account_size_usd=8000.0,
        )
        assert p.account_size_usd == 8000.0

    def test_rejects_negative_capital(self):
        with pytest.raises(ValueError, match="account_size_usd"):
            build_custom_profile(
                name="x", description="y", account_size_usd=-1,
            )

    def test_accepts_arbitrary_overrides(self):
        p = build_custom_profile(
            name="x", description="y",
            provider_type="exchange",
            allowed_symbols=("BTCUSDT", "SOLUSDT"),
            max_concurrent_positions=5,
            kill_switch_enabled=True,
            risk_config_overrides={"max_daily_loss_pct": 0.02},
        )
        assert p.provider_type == "exchange"
        assert p.allowed_symbols == ("BTCUSDT", "SOLUSDT")
        assert p.max_concurrent_positions == 5
        assert p.kill_switch_enabled is True
        assert dict(p.risk_config_overrides) == {"max_daily_loss_pct": 0.02}


# ---------------------------------------------------------------------------
# Garantias gerais
# ---------------------------------------------------------------------------

class TestAllBuildersReturnOperationalProfile:

    @pytest.mark.parametrize("builder,kwargs", [
        (build_personal_profile, {"account_size_usd": 5000.0}),
        (build_prop_challenge_profile, {"account_size_usd": 5000.0}),
        (build_hyrotrader_demo_template, {"account_size_usd": 5000.0}),
        (build_custom_profile, {"name": "x", "description": "y"}),
    ])
    def test_returns_operational_profile(self, builder, kwargs):
        p = builder(**kwargs)
        assert isinstance(p, OperationalProfile)
