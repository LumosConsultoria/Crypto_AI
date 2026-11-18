"""
Testes do ProviderCapability — FASE 8
========================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - frozen (não pode ser mutado após construção).
    - defaults SEGUROS: tudo False, confirmed=False, is_live_environment=False.
    - documented_assets é tupla imutável.
    - to_dict() sanitizado, sem credentials.
    - ProviderStatus enum tem os 6 estados esperados.
    - equality baseada em todos os campos (frozen dataclass).
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)


class TestProviderCapabilityDefaults:

    def test_all_support_flags_default_false(self):
        cap = ProviderCapability(provider_id="x")
        # Todos os support_* default False
        for attr in [
            "supports_market_order", "supports_limit_order",
            "supports_stop_loss", "supports_take_profit",
            "supports_reduce_only", "supports_leverage_api",
            "supports_positions_query", "supports_balance_query",
            "supports_cancel_order",
            "supports_webhook", "supports_cli",   # FASE 9B
        ]:
            assert getattr(cap, attr) is False, f"{attr} should default to False"

    def test_environment_flags_default_false(self):
        cap = ProviderCapability(provider_id="x")
        assert cap.is_demo_environment is False
        assert cap.is_live_environment is False

    def test_confirmed_default_false(self):
        cap = ProviderCapability(provider_id="x")
        assert cap.confirmed is False
        assert cap.confirmation_source == ""
        assert cap.notes == ""

    def test_documented_assets_default_empty_tuple(self):
        cap = ProviderCapability(provider_id="x")
        assert cap.documented_assets == ()
        assert isinstance(cap.documented_assets, tuple)


class TestProviderCapabilityFrozen:

    def test_frozen_blocks_mutation(self):
        cap = ProviderCapability(provider_id="x")
        with pytest.raises(Exception):  # FrozenInstanceError
            cap.supports_market_order = True

    def test_frozen_blocks_provider_id_mutation(self):
        cap = ProviderCapability(provider_id="x")
        with pytest.raises(Exception):
            cap.provider_id = "y"


class TestProviderCapabilityToDict:

    def test_to_dict_has_all_fields(self):
        cap = ProviderCapability(
            provider_id="demo",
            supports_market_order=True,
            is_demo_environment=True,
            documented_assets=("BTCUSDT", "ETHUSDT"),
            confirmed=True,
            confirmation_source="src",
            notes="n",
        )
        d = cap.to_dict()
        assert d["provider_id"] == "demo"
        assert d["supports_market_order"] is True
        assert d["is_demo_environment"] is True
        assert d["documented_assets"] == ["BTCUSDT", "ETHUSDT"]
        assert d["confirmed"] is True

    def test_to_dict_contains_no_secret_keys(self):
        cap = ProviderCapability(provider_id="x")
        d = cap.to_dict()
        bad_keys = {"api_key", "api_secret", "secret", "token",
                    "credentials", "authorization", "url", "endpoint"}
        assert not (set(d.keys()) & bad_keys)


class TestProviderStatusEnum:

    def test_has_all_expected_states(self):
        names = {s.name for s in ProviderStatus}
        # FASE 8: ACTIVE, OPT_IN, DRY_RUN_ONLY, FROZEN, RESTRICTED, UNCONFIRMED
        # FASE 9 Fatia 2: + CANDIDATE_REVALIDATION
        assert names == {
            "ACTIVE", "OPT_IN", "DRY_RUN_ONLY",
            "FROZEN", "RESTRICTED", "UNCONFIRMED",
            "CANDIDATE_REVALIDATION",
        }

    def test_status_is_str_enum(self):
        assert ProviderStatus.ACTIVE.value == "active"
        assert ProviderStatus.RESTRICTED.value == "restricted"
        assert ProviderStatus.UNCONFIRMED.value == "unconfirmed"
