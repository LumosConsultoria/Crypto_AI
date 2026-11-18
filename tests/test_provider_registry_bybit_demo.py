"""
Testes da integração bybit_demo_linear ↔ ProviderRegistry — FASE 9 Fatia 2
============================================================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - bybit_demo_linear registrado com status CANDIDATE_REVALIDATION.
    - capability declara is_demo_environment=True, is_live_environment=False,
      confirmed=False.
    - assert_usable bloqueia CANDIDATE_REVALIDATION (status novo).
    - ModeGuard.assert_provider_allowed bloqueia com TradingModeError.
    - Não é default — paper segue ACTIVE.
    - audit_snapshot inclui bybit_demo_linear sem secrets.
    - Outros providers permanecem com seus status anteriores.
"""

from __future__ import annotations

import json

import pytest

from crypto_trading_bot.config.settings import Settings
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.execution.provider_capability import ProviderStatus
from crypto_trading_bot.execution.provider_registry import (
    ProviderBlockedError,
    get_registry,
)


def _paper_settings() -> Settings:
    return Settings(
        trading_mode="paper",
        enable_live_trading=False,
        enable_testnet_execution=False,
        enable_demo_execution=False,
        _env_file=None,  # type: ignore[arg-type]
    )


class TestBybitDemoLinearRegistered:

    def test_status_is_opt_in_after_fatia_4b(self):
        """FASE 9 Fatia 4B: migrou de CANDIDATE_REVALIDATION → OPT_IN."""
        e = get_registry().get("bybit_demo_linear")
        assert e.status is ProviderStatus.OPT_IN

    def test_status_never_becomes_active_in_fatia_4b(self):
        """Promoção para ACTIVE exige fatia futura — não nesta."""
        e = get_registry().get("bybit_demo_linear")
        assert e.status is not ProviderStatus.ACTIVE

    def test_capability_is_demo_not_live(self):
        cap = get_registry().get("bybit_demo_linear").capability
        assert cap.is_demo_environment is True
        assert cap.is_live_environment is False
        assert cap.confirmed is False

    def test_capability_declares_market_orders(self):
        cap = get_registry().get("bybit_demo_linear").capability
        assert cap.supports_market_order is True
        # análogo ao testnet: limit NÃO no client atual
        assert cap.supports_limit_order is False


class TestBybitDemoLinearBlockedWithoutConfirm:
    """OPT_IN bloqueia sem confirm_provider; passa com confirm_provider=True."""

    def test_registry_assert_usable_blocks_without_confirm_provider(self):
        with pytest.raises(ProviderBlockedError, match="OPT_IN"):
            get_registry().assert_usable("bybit_demo_linear")

    def test_registry_assert_usable_passes_with_confirm_provider_true(self):
        # NÃO levanta
        get_registry().assert_usable(
            "bybit_demo_linear", confirm_provider=True
        )

    def test_mode_guard_blocks_without_confirm_provider(self):
        g = ModeGuard(_paper_settings())
        with pytest.raises(TradingModeError, match="OPT_IN"):
            g.assert_provider_allowed("bybit_demo_linear")

    def test_mode_guard_passes_with_confirm_provider_true(self):
        g = ModeGuard(_paper_settings())
        # NÃO levanta
        g.assert_provider_allowed("bybit_demo_linear", confirm_provider=True)


class TestBybitDemoIsNotDefault:

    def test_settings_default_provider_is_paper(self):
        s = Settings(_env_file=None)
        assert s.provider_id == "paper"

    def test_paper_still_active(self):
        assert get_registry().get("paper").status is ProviderStatus.ACTIVE


class TestOtherProvidersStillUnchanged:

    def test_bybit_testnet_still_restricted(self):
        assert get_registry().get("bybit_testnet_linear").status is ProviderStatus.RESTRICTED

    def test_binance_still_dry_run_only(self):
        assert get_registry().get("binance_futures_testnet").status is ProviderStatus.DRY_RUN_ONLY

    def test_cleo_still_unconfirmed(self):
        assert get_registry().get("hyrotrader_cleo_demo").status is ProviderStatus.UNCONFIRMED

    def test_tealstreet_still_dry_run_only(self):
        assert get_registry().get("tealstreet_cli_gateway").status is ProviderStatus.DRY_RUN_ONLY


class TestAuditSnapshotIncludesDemo:

    def test_snapshot_includes_bybit_demo_linear_without_secrets(self):
        snap = get_registry().audit_snapshot()
        ids = {p["provider_id"] for p in snap["providers"]}
        assert "bybit_demo_linear" in ids

        blob = json.dumps(snap).lower()
        for bad in ("api_key", "api_secret", "x-bapi-sign", "authorization",
                    "bearer ", "your_testnet_api_key"):
            assert bad not in blob


class TestProviderStatusEnumExtended:

    def test_candidate_revalidation_in_enum(self):
        # Garantia de que o enum foi estendido (status novo existe e é distinto)
        assert ProviderStatus.CANDIDATE_REVALIDATION.value == "candidate_revalidation"
        assert ProviderStatus.CANDIDATE_REVALIDATION is not ProviderStatus.UNCONFIRMED
        assert ProviderStatus.CANDIDATE_REVALIDATION is not ProviderStatus.OPT_IN
