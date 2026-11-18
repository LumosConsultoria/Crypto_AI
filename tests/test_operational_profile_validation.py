"""
Testes de validation puras de OperationalProfile (FASE 16)
============================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordens.

Cobertura:
    - validate_profile_self retorna lista (vazia/com problemas).
    - Detecta campos inválidos.
    - validate_profile_against_risk_config detecta inconsistências.
    - NÃO lança em entradas válidas inesperadas.
    - É pura: não tem I/O.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.operational_profile import (
    OperationalProfile,
    build_personal_profile,
    build_prop_challenge_profile,
    validate_profile_against_risk_config,
    validate_profile_self,
)


# ---------------------------------------------------------------------------
# Self validation
# ---------------------------------------------------------------------------

class TestValidateProfileSelf:

    def test_valid_personal_returns_empty(self):
        p = build_personal_profile(account_size_usd=5000.0)
        assert validate_profile_self(p) == []

    def test_valid_prop_challenge_returns_empty(self):
        p = build_prop_challenge_profile(account_size_usd=5000.0)
        assert validate_profile_self(p) == []

    def test_rejects_non_profile_argument(self):
        issues = validate_profile_self("not a profile")  # type: ignore[arg-type]
        assert len(issues) == 1
        assert "OperationalProfile" in issues[0]

    def test_max_concurrent_positions_zero(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            max_concurrent_positions=0,
        )
        issues = validate_profile_self(p)
        assert any("max_concurrent_positions" in i for i in issues)

    def test_max_session_minutes_negative(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            max_session_minutes=-10,
        )
        issues = validate_profile_self(p)
        assert any("max_session_minutes" in i for i in issues)

    def test_allowed_hours_out_of_range(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_hours_utc=((25, 26),),
        )
        issues = validate_profile_self(p)
        assert any("allowed_hours_utc" in i for i in issues)

    def test_allowed_hours_start_ge_end(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_hours_utc=((18, 13),),
        )
        issues = validate_profile_self(p)
        assert any("start >= end" in i for i in issues)

    def test_allowed_symbols_empty_string(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_symbols=("",),
        )
        issues = validate_profile_self(p)
        assert any("allowed_symbols" in i for i in issues)

    def test_funded_and_challenge_mutually_exclusive(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="prop_funded",
            is_funded_account=True,
            is_challenge_account=True,
        )
        issues = validate_profile_self(p)
        assert any("mutuamente exclusivos" in i for i in issues)

    def test_prop_challenge_requires_appropriate_flags(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="prop_challenge",
            is_prop_firm=False,
            is_challenge_account=False,
        )
        issues = validate_profile_self(p)
        assert any("prop_challenge" in i for i in issues)


# ---------------------------------------------------------------------------
# Cross-config validation (com fake RiskConfig duck-typed)
# ---------------------------------------------------------------------------

class _FakeRiskConfig:
    """Fake duck-typed para validation cross-config sem importar RiskConfig."""
    def __init__(
        self,
        *,
        account_size_usd=5000.0,
        max_daily_loss_pct=0.05,
        max_total_loss_pct=0.10,
        default_symbol="BTCUSDT",
    ):
        self.account_size_usd = account_size_usd
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_total_loss_pct = max_total_loss_pct
        self.default_symbol = default_symbol


class TestValidateProfileAgainstRiskConfig:

    def test_valid_combination_returns_empty(self):
        p = build_personal_profile(account_size_usd=5000.0)
        rc = _FakeRiskConfig()
        assert validate_profile_against_risk_config(p, rc) == []

    def test_account_size_mismatch_detected(self):
        p = build_personal_profile(account_size_usd=5000.0)
        rc = _FakeRiskConfig(account_size_usd=8000.0)
        issues = validate_profile_against_risk_config(p, rc)
        assert any("account_size_usd" in i for i in issues)

    def test_prop_challenge_with_loose_daily_loss_detected(self):
        p = build_prop_challenge_profile(account_size_usd=5000.0)
        rc = _FakeRiskConfig(max_daily_loss_pct=0.10)  # > 5%
        issues = validate_profile_against_risk_config(p, rc)
        assert any("max_daily_loss_pct" in i for i in issues)

    def test_default_symbol_not_in_allowed(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_symbols=("ETHUSDT",),
        )
        rc = _FakeRiskConfig(default_symbol="BTCUSDT")
        issues = validate_profile_against_risk_config(p, rc)
        assert any("default_symbol" in i for i in issues)

    def test_unknown_risk_override_key_detected(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            risk_config_overrides={"non_existent_field": 0.5},
        )
        rc = _FakeRiskConfig()
        issues = validate_profile_against_risk_config(p, rc)
        assert any("non_existent_field" in i for i in issues)

    def test_does_not_raise_on_none_risk_config(self):
        p = build_personal_profile(account_size_usd=5000.0)
        issues = validate_profile_against_risk_config(p, None)
        # Não lança — retorna issue claro
        assert len(issues) == 1

    def test_does_not_raise_on_non_profile_arg(self):
        rc = _FakeRiskConfig()
        issues = validate_profile_against_risk_config(
            "not a profile", rc,  # type: ignore[arg-type]
        )
        assert len(issues) == 1


# ---------------------------------------------------------------------------
# Pureza: nenhum I/O nas funções de validation
# ---------------------------------------------------------------------------

class TestPurity:

    def _src(self) -> str:
        import crypto_trading_bot.operational_profile.validation as mod
        return open(mod.__file__, "r", encoding="utf-8").read()

    def test_no_network_or_io_imports(self):
        src = self._src()
        forbidden = [
            "import httpx", "from httpx",
            "import requests", "from requests",
            "open(", "Path(",
        ]
        for tok in forbidden:
            assert tok not in src

    def test_no_executor_imports(self):
        src = self._src()
        forbidden = [
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.risk.risk_engine",
        ]
        for tok in forbidden:
            assert tok not in src
