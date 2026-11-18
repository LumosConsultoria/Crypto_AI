"""
Testes de Settings — FASE 9 Fatia 2 (Bybit Demo Trading)
==========================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede.

Cobertura:
    - TradingMode tem o valor 'demo' adicionado.
    - enable_demo_execution default False.
    - Settings aceita ENABLE_DEMO_EXECUTION=true.
    - is_demo_mode/is_demo_execution_enabled refletem combinação correta.
    - is_safe_mode permanece True para demo (não é live).
    - provider_id aceita 'bybit_demo_linear'.
    - provider_id continua rejeitando live/mainnet.
    - is_testnet_execution_enabled NÃO é alterado por flags demo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from crypto_trading_bot.config.settings import Settings, TradingMode


def _s(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


class TestTradingModeDemo:

    def test_trading_mode_enum_has_demo(self):
        assert TradingMode.DEMO.value == "demo"

    def test_trading_mode_enum_still_has_paper_testnet_live(self):
        assert TradingMode.PAPER.value == "paper"
        assert TradingMode.TESTNET.value == "testnet"
        assert TradingMode.LIVE.value == "live"

    def test_settings_accepts_trading_mode_demo(self):
        s = _s(trading_mode="demo")
        assert s.trading_mode == TradingMode.DEMO
        assert s.is_demo_mode is True
        assert s.is_paper_mode is False
        assert s.is_testnet_mode is False
        assert s.is_live_mode is False


class TestEnableDemoExecutionFlag:

    def test_default_false(self):
        s = _s()
        assert s.enable_demo_execution is False

    def test_accepts_true(self):
        s = _s(enable_demo_execution=True)
        assert s.enable_demo_execution is True

    def test_is_demo_execution_enabled_requires_both_mode_and_flag(self):
        # apenas modo demo, sem flag
        assert _s(trading_mode="demo").is_demo_execution_enabled is False
        # apenas flag, sem modo demo
        assert _s(enable_demo_execution=True).is_demo_execution_enabled is False
        # ambos
        s = _s(trading_mode="demo", enable_demo_execution=True)
        assert s.is_demo_execution_enabled is True

    def test_is_safe_mode_true_in_demo(self):
        # Demo NÃO é live → sistema é seguro
        s = _s(trading_mode="demo", enable_demo_execution=True)
        assert s.is_safe_mode is True
        assert s.is_live_mode is False


class TestProviderIdAcceptsBybitDemoLinear:

    def test_accepts_bybit_demo_linear(self):
        s = _s(provider_id="bybit_demo_linear")
        assert s.provider_id == "bybit_demo_linear"

    @pytest.mark.parametrize("forbidden", [
        "live", "mainnet", "real", "production", "prod",
        "bybit_mainnet", "binance_mainnet", "hyrotrader_real",
        "bybit_live", "binance_live",
    ])
    def test_still_rejects_live_mainnet(self, forbidden):
        with pytest.raises(ValidationError):
            _s(provider_id=forbidden)


class TestNoCrossContaminationBetweenFlags:

    def test_demo_flag_does_not_enable_testnet(self):
        s = _s(trading_mode="demo", enable_demo_execution=True)
        # demo execução habilitada — testnet NÃO
        assert s.is_demo_execution_enabled is True
        assert s.is_testnet_execution_enabled is False

    def test_testnet_flag_does_not_enable_demo(self):
        s = _s(trading_mode="testnet", enable_testnet_execution=True)
        assert s.is_testnet_execution_enabled is True
        assert s.is_demo_execution_enabled is False

    def test_both_modes_mutually_exclusive(self):
        # trading_mode é singular — não dá pra ser demo e testnet ao mesmo tempo
        s_demo = _s(trading_mode="demo")
        s_testnet = _s(trading_mode="testnet")
        assert s_demo.is_demo_mode is True and s_demo.is_testnet_mode is False
        assert s_testnet.is_testnet_mode is True and s_testnet.is_demo_mode is False
