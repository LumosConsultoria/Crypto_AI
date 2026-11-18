"""
Isolamento estrutural do BacktestEngine vs. provider real (FASE 12)
====================================================================
⚠️  100% offline. ZERO rede.

Cobertura estrutural:
    - BacktestEngine não importa BybitClient.
    - BacktestEngine não importa executores (BybitDemoExecutor,
      BybitTestnetExecutor, PaperTrader).
    - BacktestEngine não importa httpx.
    - exit_policy_adapter não importa providers reais.
    - Nenhum caminho usa API key ou URL real.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _read(module_path: str) -> str:
    return Path(module_path).read_text(encoding="utf-8")


def _src_of(module) -> str:
    return _read(module.__file__)


class TestBacktestEngineProviderAgnostic:

    def test_no_bybit_client_import(self):
        import crypto_trading_bot.backtesting.backtest_engine as m
        src = _src_of(m)
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "import crypto_trading_bot.exchange.bybit_client" not in src

    def test_no_executor_imports(self):
        import crypto_trading_bot.backtesting.backtest_engine as m
        src = _src_of(m)
        forbidden = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.execution.paper_trader",
        ]
        for line in forbidden:
            assert line not in src, f"BacktestEngine não deve importar: {line}"

    def test_no_httpx(self):
        import crypto_trading_bot.backtesting.backtest_engine as m
        src = _src_of(m)
        assert "import httpx" not in src
        assert "from httpx" not in src

    def test_no_api_key_in_engine_module(self):
        import crypto_trading_bot.backtesting.backtest_engine as m
        src = _src_of(m).lower()
        # Tokens proibidos em código de backtest puro
        for tok in ("api_key", "api_secret", "x-bapi-api-key", "bearer "):
            assert tok not in src, (
                f"BacktestEngine não deve mencionar {tok!r}"
            )


class TestExitPolicyAdapterProviderAgnostic:

    def test_adapter_imports_only_exit_policy_and_backtest_trade(self):
        import crypto_trading_bot.backtesting.exit_policy_adapter as m
        src = _src_of(m)
        # Permitidos
        assert "from crypto_trading_bot.exit_policy" in src
        assert "from crypto_trading_bot.backtesting.backtest_trade" in src
        # Proibidos
        forbidden = [
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.execution.paper_trader",
            "from crypto_trading_bot.execution.provider_registry",
            "import httpx",
        ]
        for line in forbidden:
            assert line not in src, (
                f"exit_policy_adapter não deve importar: {line}"
            )


class TestExitPolicyAdapterIsPure:

    def test_no_io_or_logging_side_effects(self):
        import crypto_trading_bot.backtesting.exit_policy_adapter as m
        src = _src_of(m)
        # Sem prints, sem open(), sem requests
        assert "print(" not in src
        assert "open(" not in src
        assert "requests." not in src
        assert "httpx." not in src
