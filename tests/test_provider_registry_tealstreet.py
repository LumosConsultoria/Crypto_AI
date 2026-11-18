"""
Testes da integração Tealstreet ↔ ProviderRegistry — FASE 9B
==============================================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - tealstreet_cli_gateway registrado como DRY_RUN_ONLY no registry default.
    - capability declara supports_webhook=True, supports_cli=True, confirmed=False.
    - assert_usable bloqueia (status DRY_RUN_ONLY).
    - ModeGuard.assert_provider_allowed bloqueia com TradingModeError.
    - Tealstreet NÃO é default — Settings.provider_id default segue "paper".
    - Os demais providers (paper/bybit/binance/cleo) ficam INALTERADOS.
    - audit_snapshot inclui tealstreet sem expor secrets.
"""

from __future__ import annotations

import json

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.execution.provider_capability import ProviderStatus
from crypto_trading_bot.execution.provider_registry import (
    ProviderBlockedError,
    get_registry,
)


def _paper_settings() -> Settings:
    return Settings(
        trading_mode=TradingMode.PAPER,
        enable_live_trading=False,
        enable_testnet_execution=False,
        _env_file=None,  # type: ignore[arg-type]
    )


class TestTealstreetRegisteredAsDryRunOnly:

    def test_status_dry_run_only(self):
        e = get_registry().get("tealstreet_cli_gateway")
        assert e.status is ProviderStatus.DRY_RUN_ONLY

    def test_capability_webhook_and_cli(self):
        cap = get_registry().get("tealstreet_cli_gateway").capability
        assert cap.supports_webhook is True
        assert cap.supports_cli is True
        assert cap.confirmed is False
        assert cap.is_live_environment is False


class TestTealstreetBlockedForExecution:

    def test_registry_assert_usable_blocks(self):
        with pytest.raises(ProviderBlockedError, match="dry_run_only"):
            get_registry().assert_usable("tealstreet_cli_gateway")

    def test_mode_guard_blocks(self):
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError, match="dry_run_only"):
            g.assert_provider_allowed("tealstreet_cli_gateway")


class TestTealstreetIsNotDefault:

    def test_settings_default_provider_is_paper(self):
        s = Settings(_env_file=None)
        assert s.provider_id == "paper"

    def test_settings_accepts_tealstreet_as_explicit_value(self):
        s = Settings(_env_file=None, provider_id="tealstreet_cli_gateway")
        assert s.provider_id == "tealstreet_cli_gateway"


class TestOtherProvidersUnchanged:

    def test_paper_still_active(self):
        assert get_registry().get("paper").status is ProviderStatus.ACTIVE

    def test_bybit_still_restricted(self):
        assert get_registry().get("bybit_testnet_linear").status is ProviderStatus.RESTRICTED

    def test_binance_still_dry_run_only(self):
        assert get_registry().get("binance_futures_testnet").status is ProviderStatus.DRY_RUN_ONLY

    def test_cleo_still_unconfirmed(self):
        assert get_registry().get("hyrotrader_cleo_demo").status is ProviderStatus.UNCONFIRMED


class TestAuditSnapshot:

    def test_audit_includes_tealstreet_without_secret(self):
        snap = get_registry().audit_snapshot()
        ids = {p["provider_id"] for p in snap["providers"]}
        assert "tealstreet_cli_gateway" in ids
        blob = json.dumps(snap).lower()
        for bad in ("api_key", "api_secret", "x-bapi-sign",
                    "authorization", "bearer "):
            assert bad not in blob
