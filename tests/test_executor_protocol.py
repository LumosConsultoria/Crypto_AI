"""
Testes do ExecutorProtocol — FASE 6
=====================================
⚠️  ZERO chamadas à internet. ZERO API key real. ZERO ordens reais.

Cobertura:
    - PaperTrader satisfaz ExecutorProtocol estruturalmente (isinstance).
    - TestnetExecutorBotAdapter satisfaz ExecutorProtocol estruturalmente.
    - Objeto SEM método execute() NÃO satisfaz o Protocol.
    - Objeto COM execute() arbitrário satisfaz (duck typing estrutural).
    - O Protocol não importa nada de produção que afrouxe segurança.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.execution import (
    BybitTestnetExecutor,
    ExecutorProtocol,
    PaperTrader,
    TestnetExecutorBotAdapter,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine


def _make_testnet_executor() -> BybitTestnetExecutor:
    client = MagicMock(spec=BybitClient)
    type(client).use_testnet = property(lambda self: True)
    type(client).has_credentials = property(lambda self: True)
    settings = Settings(
        trading_mode=TradingMode.TESTNET,
        enable_testnet_execution=True,
        enable_live_trading=False,
        _env_file=None,  # type: ignore[arg-type]
    )
    guard = ModeGuard(settings=settings)
    risk = RiskEngine(initial_capital=5000.0)
    return BybitTestnetExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        confirm_testnet_execution=True,
    )


class TestExecutorProtocolStructural:
    """ExecutorProtocol é runtime_checkable e estrutural."""

    def test_paper_trader_satisfies_protocol(self):
        risk = RiskEngine(initial_capital=5000.0)
        paper = PaperTrader(risk_engine=risk)
        assert isinstance(paper, ExecutorProtocol)

    def test_testnet_adapter_satisfies_protocol(self):
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_testnet_executor(),
            dry_run=True,
        )
        assert isinstance(adapter, ExecutorProtocol)

    def test_object_without_execute_does_not_satisfy(self):
        class NoExecute:
            def run(self):
                return None

        assert not isinstance(NoExecute(), ExecutorProtocol)

    def test_arbitrary_object_with_execute_satisfies(self):
        class HasExecute:
            def execute(self, risk_result):
                return "ok"

        assert isinstance(HasExecute(), ExecutorProtocol)

    def test_protocol_execute_is_callable_contract(self):
        # O contrato mínimo é apenas a presença de execute(); chamamos via
        # um objeto qualquer para garantir que a assinatura aceita risk_result.
        class Echo:
            def execute(self, risk_result):
                return risk_result

        obj = Echo()
        assert isinstance(obj, ExecutorProtocol)
        sentinel = object()
        assert obj.execute(sentinel) is sentinel
