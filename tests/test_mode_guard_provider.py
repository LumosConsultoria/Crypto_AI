"""
Testes de ModeGuard.assert_provider_allowed — FASE 8
======================================================
⚠️  100% offline. ZERO secrets.

Cobertura:
    - paper passa (status ACTIVE no registry default).
    - bybit_testnet_linear bloqueia (RESTRICTED).
    - binance_futures_testnet bloqueia (DRY_RUN_ONLY).
    - hyrotrader_cleo_demo bloqueia (UNCONFIRMED).
    - Provider desconhecido levanta TradingModeError.
    - assert_provider_allowed NÃO afeta assert_live_allowed (intocado).
    - assert_provider_allowed NÃO afeta assert_testnet_execution_allowed.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError


def _paper_settings() -> Settings:
    return Settings(
        trading_mode=TradingMode.PAPER,
        enable_live_trading=False,
        enable_testnet_execution=False,
        _env_file=None,  # type: ignore[arg-type]
    )


class TestAssertProviderAllowedDelegatesToRegistry:

    def test_paper_passes(self):
        g = ModeGuard(settings=_paper_settings())
        g.assert_provider_allowed("paper")  # não levanta

    def test_bybit_testnet_linear_blocks(self):
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError, match="restricted"):
            g.assert_provider_allowed("bybit_testnet_linear")

    def test_binance_futures_testnet_blocks(self):
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError, match="dry_run_only"):
            g.assert_provider_allowed("binance_futures_testnet")

    def test_hyrotrader_cleo_demo_blocks(self):
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError, match="unconfirmed"):
            g.assert_provider_allowed("hyrotrader_cleo_demo")

    def test_unknown_provider_raises_trading_mode_error(self):
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError, match="desconhecido"):
            g.assert_provider_allowed("provider_inexistente_xyz")


class TestAssertProviderAllowedDoesNotAffectOtherGuards:

    def test_assert_live_allowed_still_blocks_paper_mode(self):
        """FASE 8 não afrouxou o triple-lock de live."""
        g = ModeGuard(settings=_paper_settings())
        with pytest.raises(TradingModeError):
            g.assert_live_allowed(confirm_live_trading=True)

    def test_assert_testnet_execution_allowed_still_requires_triple_lock(self):
        """FASE 8 não afrouxou o triple-lock de testnet."""
        g = ModeGuard(settings=_paper_settings())   # paper, testnet_exec=False
        with pytest.raises(TradingModeError):
            g.assert_testnet_execution_allowed(confirm_testnet_execution=True)

    def test_is_safe_unchanged_after_provider_check(self):
        g = ModeGuard(settings=_paper_settings())
        before = g.is_safe
        g.assert_provider_allowed("paper")
        assert g.is_safe is before is True
