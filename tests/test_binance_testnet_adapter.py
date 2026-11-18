"""
Testes do BinanceFuturesTestnetAdapter — FASE 8 (esqueleto dry-run)
=====================================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO httpx.

Cobertura:
    - dry_run obrigatório no construtor (sem default).
    - dry_run=False levanta NotImplementedError no construtor.
    - dry_run=True + execute() retorna BinanceDryRunResult(success=True, dry_run=True).
    - execute() rejeita risk_result.approved=False.
    - capability descreve is_demo_environment=True, is_live_environment=False,
      confirmed=False.
    - Satisfaz ExecutorProtocol estruturalmente.
    - Adapter NÃO importa httpx em runtime.
"""

from __future__ import annotations

import sys

import pytest

from crypto_trading_bot.execution import ExecutorProtocol
from crypto_trading_bot.execution.providers import (
    BinanceDryRunResult,
    BinanceFuturesTestnetAdapter,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskResult,
    TradingSignal,
)


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=100.0,
        leverage=1.0,
        strategy_name="test",
    )


def _approved() -> RiskResult:
    return RiskResult(approved=True, reason="ok", signal=_signal())


def _blocked() -> RiskResult:
    return RiskResult(approved=False, reason="blocked", signal=_signal())


class TestConstructor:

    def test_dry_run_required_no_default(self):
        with pytest.raises(TypeError):
            BinanceFuturesTestnetAdapter()  # type: ignore[call-arg]

    def test_dry_run_must_be_bool(self):
        with pytest.raises(ValueError):
            BinanceFuturesTestnetAdapter(dry_run=None)  # type: ignore[arg-type]

    def test_dry_run_false_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="NÃO está implementada"):
            BinanceFuturesTestnetAdapter(dry_run=False)

    def test_dry_run_true_constructs(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        assert a.is_dry_run is True
        assert a.provider_id == "binance_futures_testnet"


class TestCapability:

    def test_capability_declares_demo_not_live(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        cap = a.capability
        assert cap.is_demo_environment is True
        assert cap.is_live_environment is False

    def test_capability_confirmed_false(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        assert a.capability.confirmed is False
        assert a.capability.confirmation_source == ""


class TestExecute:

    def test_satisfies_executor_protocol(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        assert isinstance(a, ExecutorProtocol)

    def test_execute_rejects_unapproved(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        with pytest.raises(ValueError, match="REJEITA risk_result não aprovado"):
            a.execute(_blocked())

    def test_execute_returns_dry_run_result(self):
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        r = a.execute(_approved())
        assert isinstance(r, BinanceDryRunResult)
        assert r.success is True
        assert r.dry_run is True
        assert r.provider_id == "binance_futures_testnet"

    def test_summary_has_no_secrets(self):
        import json
        a = BinanceFuturesTestnetAdapter(dry_run=True)
        blob = json.dumps(a.get_summary()).lower()
        for bad in ("api_key", "api_secret", "secret", "url", "endpoint",
                    "authorization", "x-mbx-apikey"):
            assert bad not in blob


class TestNoNetworkImport:

    def test_httpx_not_required_at_import(self):
        # O adapter NÃO deve depender de httpx no escopo do módulo.
        # Verifica que o módulo do adapter foi importável; se httpx estivesse
        # como `import httpx` no topo e ausente, ImportError teria ocorrido.
        # Adicionalmente, asserta que nenhum atributo public do módulo é httpx.
        mod = sys.modules[BinanceFuturesTestnetAdapter.__module__]
        assert not hasattr(mod, "httpx")
        assert not hasattr(mod, "requests")
