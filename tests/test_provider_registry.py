"""
Testes do ProviderRegistry — FASE 8
=====================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - Registry default tem os 4 providers FASE 8 com status corretos.
    - register/get/list_available/unregister.
    - assert_usable: ACTIVE passa, OPT_IN exige confirm, demais bloqueiam.
    - audit_snapshot retorna dict sem credenciais nem factories.
    - snapshot_one retorna None para provider desconhecido.
    - register duplicado falha; replace=True sobrescreve.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)
from crypto_trading_bot.execution.provider_registry import (
    ProviderBlockedError,
    ProviderEntry,
    ProviderRegistry,
    get_registry,
)


def _cap(pid: str, **overrides) -> ProviderCapability:
    return ProviderCapability(provider_id=pid, **overrides)


def _entry(pid: str, status: ProviderStatus, reason: str = "") -> ProviderEntry:
    return ProviderEntry(
        provider_id=pid, capability=_cap(pid),
        status=status, reason=reason,
    )


# ---------------------------------------------------------------------------
# Default registry — providers FASE 8
# ---------------------------------------------------------------------------

class TestDefaultRegistryHasPhase8Providers:

    def test_paper_registered_as_active(self):
        e = get_registry().get("paper")
        assert e.status is ProviderStatus.ACTIVE
        assert e.capability.supports_market_order is True
        assert e.capability.is_demo_environment is True
        assert e.capability.is_live_environment is False

    def test_bybit_testnet_linear_registered_as_restricted(self):
        e = get_registry().get("bybit_testnet_linear")
        assert e.status is ProviderStatus.RESTRICTED
        assert "FASE 7" in e.reason or "restrição" in e.reason.lower()

    def test_binance_futures_testnet_registered_as_dry_run_only(self):
        e = get_registry().get("binance_futures_testnet")
        assert e.status is ProviderStatus.DRY_RUN_ONLY
        assert e.capability.confirmed is False

    def test_hyrotrader_cleo_demo_registered_as_unconfirmed(self):
        e = get_registry().get("hyrotrader_cleo_demo")
        assert e.status is ProviderStatus.UNCONFIRMED
        assert e.capability.confirmed is False
        # Todas as capacidades False (mecanismo desconhecido)
        assert e.capability.supports_market_order is False
        assert e.capability.is_demo_environment is False
        assert e.capability.is_live_environment is False


# ---------------------------------------------------------------------------
# assert_usable: regras de bloqueio
# ---------------------------------------------------------------------------

class TestAssertUsable:

    def test_active_passes_without_confirm(self):
        r = get_registry()
        r.assert_usable("paper")   # não levanta

    def test_restricted_blocks(self):
        r = get_registry()
        with pytest.raises(ProviderBlockedError, match="restricted"):
            r.assert_usable("bybit_testnet_linear")

    def test_dry_run_only_blocks(self):
        r = get_registry()
        with pytest.raises(ProviderBlockedError, match="dry_run_only"):
            r.assert_usable("binance_futures_testnet")

    def test_unconfirmed_blocks(self):
        r = get_registry()
        with pytest.raises(ProviderBlockedError, match="unconfirmed"):
            r.assert_usable("hyrotrader_cleo_demo")

    def test_unknown_provider_raises_key_error(self):
        r = get_registry()
        with pytest.raises(KeyError):
            r.assert_usable("nonexistent_provider_xyz")

    def test_opt_in_requires_confirm_provider(self):
        # Usa um registry LOCAL para não poluir o default
        r = ProviderRegistry()
        r.register(_entry("test_optin", ProviderStatus.OPT_IN, reason="test"))
        with pytest.raises(ProviderBlockedError, match="OPT_IN"):
            r.assert_usable("test_optin")
        r.assert_usable("test_optin", confirm_provider=True)  # passa


# ---------------------------------------------------------------------------
# audit_snapshot + sanitização
# ---------------------------------------------------------------------------

class TestAuditSnapshot:

    def test_audit_snapshot_lists_all_providers(self):
        snap = get_registry().audit_snapshot()
        ids = {p["provider_id"] for p in snap["providers"]}
        assert {"paper", "bybit_testnet_linear",
                "binance_futures_testnet", "hyrotrader_cleo_demo"} <= ids
        assert snap["count"] >= 4

    def test_audit_snapshot_has_no_secrets(self):
        snap = get_registry().audit_snapshot()
        # Serializa tudo e procura por chaves sensíveis literais
        import json
        blob = json.dumps(snap).lower()
        for bad in ("api_key", "api_secret", "x-bapi-sign", "authorization",
                    "bearer ", "your_testnet_api_key"):
            assert bad not in blob, f"audit_snapshot leaked: {bad}"

    def test_snapshot_one_returns_none_for_unknown(self):
        assert get_registry().snapshot_one("doesnt_exist_xyz") is None

    def test_snapshot_one_returns_dict_for_paper(self):
        d = get_registry().snapshot_one("paper")
        assert d is not None
        assert d["provider_id"] == "paper"
        assert d["status"] == "active"
        assert d["capability"]["supports_market_order"] is True


# ---------------------------------------------------------------------------
# register / unregister / replace
# ---------------------------------------------------------------------------

class TestRegisterUnregister:

    def test_register_duplicate_raises(self):
        r = ProviderRegistry()
        r.register(_entry("p1", ProviderStatus.ACTIVE))
        with pytest.raises(ValueError, match="já registrado"):
            r.register(_entry("p1", ProviderStatus.ACTIVE))

    def test_register_replace_true_overwrites(self):
        r = ProviderRegistry()
        r.register(_entry("p1", ProviderStatus.ACTIVE))
        r.register(_entry("p1", ProviderStatus.RESTRICTED), replace=True)
        assert r.get("p1").status is ProviderStatus.RESTRICTED

    def test_unregister_removes_entry(self):
        r = ProviderRegistry()
        r.register(_entry("p1", ProviderStatus.ACTIVE))
        r.unregister("p1")
        with pytest.raises(KeyError):
            r.get("p1")

    def test_list_available_returns_tuple(self):
        r = ProviderRegistry()
        r.register(_entry("p1", ProviderStatus.ACTIVE))
        r.register(_entry("p2", ProviderStatus.FROZEN))
        items = r.list_available()
        assert isinstance(items, tuple)
        assert len(items) == 2
