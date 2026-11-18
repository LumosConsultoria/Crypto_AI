"""
Testes de ModeGuard.assert_demo_execution_allowed — FASE 9 Fatia 2
====================================================================
⚠️  100% offline. ZERO secrets.

Cobertura:
    - is_demo property reflete trading_mode=demo.
    - is_demo_execution_allowed exige modo + flag.
    - assert_demo_execution_allowed: triple-lock completo.
    - Bloqueia sem TRADING_MODE=demo.
    - Bloqueia sem ENABLE_DEMO_EXECUTION=true.
    - Bloqueia sem confirm_demo_execution=True.
    - Passa apenas com triple-lock completo.
    - NÃO afeta assert_live_allowed (intocado).
    - NÃO afeta assert_testnet_execution_allowed (intocado).
    - get_status_summary inclui campos demo sem expor secrets.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError


def _settings(
    trading_mode: str = "paper",
    enable_live_trading: bool = False,
    enable_testnet_execution: bool = False,
    enable_demo_execution: bool = False,
) -> Settings:
    return Settings(
        trading_mode=trading_mode,
        enable_live_trading=enable_live_trading,
        enable_testnet_execution=enable_testnet_execution,
        enable_demo_execution=enable_demo_execution,
        _env_file=None,  # type: ignore[arg-type]
    )


def _demo_ready_settings() -> Settings:
    """Settings com triple-lock demo satisfeito (mas confirm_demo_execution
    ainda precisa vir da chamada)."""
    return _settings(trading_mode="demo", enable_demo_execution=True)


# ---------------------------------------------------------------------------
# is_demo / is_demo_execution_allowed
# ---------------------------------------------------------------------------

class TestModeGuardDemoState:

    def test_is_demo_true_when_mode_is_demo(self):
        g = ModeGuard(_settings(trading_mode="demo"))
        assert g.is_demo is True

    def test_is_demo_false_when_mode_is_paper(self):
        g = ModeGuard(_settings(trading_mode="paper"))
        assert g.is_demo is False

    def test_is_demo_false_when_mode_is_testnet(self):
        g = ModeGuard(_settings(trading_mode="testnet"))
        assert g.is_demo is False

    def test_is_demo_execution_allowed_requires_mode_and_flag(self):
        # apenas modo demo, sem flag
        g_partial = ModeGuard(_settings(trading_mode="demo"))
        assert g_partial.is_demo_execution_allowed is False

        # apenas flag, sem modo demo
        g_flag_only = ModeGuard(_settings(enable_demo_execution=True))
        assert g_flag_only.is_demo_execution_allowed is False

        # ambos
        g_full = ModeGuard(_demo_ready_settings())
        assert g_full.is_demo_execution_allowed is True


# ---------------------------------------------------------------------------
# assert_demo_execution_allowed — triple-lock
# ---------------------------------------------------------------------------

class TestAssertDemoExecutionAllowed:

    def test_blocks_without_demo_mode(self):
        g = ModeGuard(_settings(trading_mode="paper", enable_demo_execution=True))
        with pytest.raises(TradingModeError, match="TRADING_MODE=paper"):
            g.assert_demo_execution_allowed(confirm_demo_execution=True)

    def test_blocks_without_enable_demo_execution(self):
        g = ModeGuard(_settings(trading_mode="demo", enable_demo_execution=False))
        with pytest.raises(TradingModeError, match="ENABLE_DEMO_EXECUTION=false"):
            g.assert_demo_execution_allowed(confirm_demo_execution=True)

    def test_blocks_without_explicit_confirm(self):
        g = ModeGuard(_demo_ready_settings())
        with pytest.raises(TradingModeError, match="confirm_demo_execution=False"):
            g.assert_demo_execution_allowed(confirm_demo_execution=False)

    def test_passes_with_full_triple_lock(self):
        g = ModeGuard(_demo_ready_settings())
        g.assert_demo_execution_allowed(confirm_demo_execution=True)  # não levanta

    def test_blocks_in_testnet_mode_even_with_confirm(self):
        # Demo e testnet são modos distintos; demo gate exige modo demo
        g = ModeGuard(_settings(
            trading_mode="testnet",
            enable_testnet_execution=True,
            enable_demo_execution=True,  # flag ON mas modo errado
        ))
        with pytest.raises(TradingModeError, match="TRADING_MODE=testnet"):
            g.assert_demo_execution_allowed(confirm_demo_execution=True)


# ---------------------------------------------------------------------------
# Demo gate não afeta outros gates (assert_live_allowed, testnet)
# ---------------------------------------------------------------------------

class TestDemoGateIsolation:

    def test_assert_live_allowed_still_blocks_in_demo_mode(self):
        g = ModeGuard(_demo_ready_settings())
        with pytest.raises(TradingModeError):
            g.assert_live_allowed(confirm_live_trading=True)

    def test_assert_testnet_execution_allowed_still_blocks_in_demo_mode(self):
        g = ModeGuard(_demo_ready_settings())
        with pytest.raises(TradingModeError):
            g.assert_testnet_execution_allowed(confirm_testnet_execution=True)

    def test_assert_demo_blocks_in_pure_testnet_setup(self):
        # Cenário testnet pronto — demo gate deve bloquear
        g = ModeGuard(_settings(
            trading_mode="testnet", enable_testnet_execution=True
        ))
        with pytest.raises(TradingModeError):
            g.assert_demo_execution_allowed(confirm_demo_execution=True)
        # E o testnet gate continua passando
        g.assert_testnet_execution_allowed(confirm_testnet_execution=True)


# ---------------------------------------------------------------------------
# get_status_summary inclui campos demo
# ---------------------------------------------------------------------------

class TestStatusSummaryIncludesDemo:

    def test_summary_has_demo_keys(self):
        g = ModeGuard(_demo_ready_settings())
        summary = g.get_status_summary()
        assert "is_demo" in summary
        assert "demo_execution_env_enabled" in summary
        assert "is_demo_execution_allowed" in summary
        assert summary["is_demo"] is True
        assert summary["demo_execution_env_enabled"] is True
        assert summary["is_demo_execution_allowed"] is True

    def test_summary_demo_does_not_leak_secrets(self):
        import json
        g = ModeGuard(_demo_ready_settings())
        blob = json.dumps(g.get_status_summary(), default=str).lower()
        for bad in ("api_key", "api_secret", "x-bapi-sign", "authorization"):
            assert bad not in blob
