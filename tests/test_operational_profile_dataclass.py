"""
Testes de OperationalProfile dataclass (FASE 16)
==================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - Frozen.
    - risk_config_overrides é MappingProxyType.
    - allowed_symbols / allowed_hours_utc são tuplas.
    - to_dict é JSON-serializável.
    - provider_type inválido é rejeitado.
"""

from __future__ import annotations

import json
from types import MappingProxyType

import pytest

from crypto_trading_bot.operational_profile import OperationalProfile


class TestImmutability:

    def test_is_frozen(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
        )
        with pytest.raises(Exception):
            p.name = "z"  # type: ignore[misc]

    def test_risk_overrides_is_mappingproxy(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            risk_config_overrides={"foo": 1},
        )
        assert isinstance(p.risk_config_overrides, MappingProxyType)
        with pytest.raises(TypeError):
            p.risk_config_overrides["foo"] = 2  # type: ignore[index]

    def test_allowed_symbols_becomes_tuple(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_symbols=["BTCUSDT", "ETHUSDT"],
        )
        assert isinstance(p.allowed_symbols, tuple)
        assert p.allowed_symbols == ("BTCUSDT", "ETHUSDT")

    def test_allowed_hours_becomes_tuple_of_tuples(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_hours_utc=[(13, 18), (20, 22)],
        )
        assert isinstance(p.allowed_hours_utc, tuple)
        for entry in p.allowed_hours_utc:
            assert isinstance(entry, tuple)


class TestDefaults:

    def test_defaults_conservative(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
        )
        assert p.max_concurrent_positions == 1
        assert p.kill_switch_enabled is False
        assert p.conservative_mode is False
        assert p.require_manual_ack_on_triangulation is True
        assert p.allowed_symbols == ()
        assert p.allowed_hours_utc == ()
        assert p.account_size_usd is None


class TestValidation:

    def test_empty_name_rejected(self):
        with pytest.raises(ValueError, match="name"):
            OperationalProfile(
                name="", description="y", provider_type="personal",
            )

    def test_invalid_provider_type_rejected(self):
        with pytest.raises(ValueError, match="provider_type"):
            OperationalProfile(
                name="x", description="y", provider_type="invalid",
            )


class TestProperties:

    def test_is_personal(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
        )
        assert p.is_personal is True

    def test_has_restricted_symbols(self):
        p1 = OperationalProfile(
            name="x", description="y", provider_type="personal",
        )
        p2 = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_symbols=("BTCUSDT",),
        )
        assert p1.has_restricted_symbols is False
        assert p2.has_restricted_symbols is True

    def test_has_restricted_hours(self):
        p1 = OperationalProfile(
            name="x", description="y", provider_type="personal",
        )
        p2 = OperationalProfile(
            name="x", description="y", provider_type="personal",
            allowed_hours_utc=((13, 18),),
        )
        assert p1.has_restricted_hours is False
        assert p2.has_restricted_hours is True


class TestToDict:

    def test_to_dict_is_json_serializable(self):
        p = OperationalProfile(
            name="x", description="y", provider_type="personal",
            account_size_usd=5000.0,
            allowed_symbols=("BTCUSDT",),
            allowed_hours_utc=((13, 18),),
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        d = p.to_dict()
        # estrutura
        assert d["name"] == "x"
        assert d["provider_type"] == "personal"
        assert d["account_size_usd"] == 5000.0
        assert d["allowed_symbols"] == ["BTCUSDT"]
        assert d["allowed_hours_utc"] == [[13, 18]]
        # serializável
        json.dumps(d)
