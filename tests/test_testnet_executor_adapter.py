"""
Testes do TestnetExecutorBotAdapter — FASE 6
==============================================
⚠️  ZERO chamadas à internet (BybitClient mockado). ZERO API key real.
⚠️  ZERO ordens reais. dry_run controla simulação vs. envio.

Cobertura:
    - dry_run é OBRIGATÓRIO (sem default) — TypeError ao omitir.
    - dry_run deve ser bool — ValueError para None/valor inválido.
    - construtor rejeita executor que não é BybitTestnetExecutor.
    - execute() delega ao BybitTestnetExecutor com o dry_run fixado.
    - dry_run=True NUNCA chama BybitClient privado (place_market_order).
    - execute() repassa risk_result não-aprovado → BybitTestnetExecutor levanta
      ValueError (invariante preservada).
    - is_dry_run reflete o construtor.
    - get_summary delega e adiciona dry_run.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.execution.bybit_testnet_executor import (
    BybitTestnetExecutor,
    TestnetExecutionResult,
)
from crypto_trading_bot.execution.testnet_executor_adapter import (
    TestnetExecutorBotAdapter,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings_testnet_ready() -> Settings:
    return Settings(
        trading_mode=TradingMode.TESTNET,
        enable_testnet_execution=True,
        enable_live_trading=False,
        _env_file=None,  # type: ignore[arg-type]
    )


def _make_mock_client(use_testnet: bool = True) -> MagicMock:
    client = MagicMock(spec=BybitClient)
    type(client).use_testnet = property(lambda self: use_testnet)
    type(client).has_credentials = property(lambda self: True)
    return client


def _make_executor(client: MagicMock | None = None) -> BybitTestnetExecutor:
    client = client or _make_mock_client()
    guard = ModeGuard(settings=_settings_testnet_ready())
    risk = RiskEngine(initial_capital=5000.0)
    return BybitTestnetExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        confirm_testnet_execution=True,
    )


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=200.0,
        leverage=1.0,
        strategy_name="test",
    )


def _approved() -> RiskResult:
    return RiskResult(approved=True, reason="ok", signal=_signal())


def _blocked() -> RiskResult:
    return RiskResult(approved=False, reason="blocked", signal=_signal())


# ---------------------------------------------------------------------------
# Construtor
# ---------------------------------------------------------------------------

class TestAdapterConstructor:

    def test_dry_run_is_required_no_default(self):
        """dry_run não tem default — omiti-lo levanta TypeError."""
        with pytest.raises(TypeError):
            TestnetExecutorBotAdapter(testnet_executor=_make_executor())  # type: ignore[call-arg]

    def test_dry_run_must_be_bool(self):
        with pytest.raises(ValueError):
            TestnetExecutorBotAdapter(
                testnet_executor=_make_executor(),
                dry_run=None,  # type: ignore[arg-type]
            )

    def test_rejects_non_testnet_executor(self):
        with pytest.raises(TypeError):
            TestnetExecutorBotAdapter(
                testnet_executor=object(),  # type: ignore[arg-type]
                dry_run=True,
            )

    def test_accepts_valid_executor(self):
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_executor(), dry_run=True
        )
        assert adapter.is_dry_run is True

    def test_is_dry_run_false_when_constructed_false(self):
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_executor(), dry_run=False
        )
        assert adapter.is_dry_run is False


# ---------------------------------------------------------------------------
# execute() — delegação e dry_run
# ---------------------------------------------------------------------------

class TestAdapterExecute:

    def test_dry_run_true_does_not_call_private_api(self):
        """Com dry_run=True, place_market_order NUNCA é chamado."""
        client = _make_mock_client()
        executor = _make_executor(client)
        adapter = TestnetExecutorBotAdapter(testnet_executor=executor, dry_run=True)

        result = adapter.execute(_approved())

        assert isinstance(result, TestnetExecutionResult)
        assert result.dry_run is True
        assert result.success is True
        client.place_market_order.assert_not_called()

    def test_execute_delegates_with_fixed_dry_run(self):
        """O adapter repassa o dry_run fixado ao executor subjacente."""
        executor = _make_executor()
        executor.execute = MagicMock(  # type: ignore[method-assign]
            return_value=TestnetExecutionResult(
                success=True, operation="place_order", dry_run=True
            )
        )
        adapter = TestnetExecutorBotAdapter(testnet_executor=executor, dry_run=True)
        risk = _approved()

        adapter.execute(risk)

        executor.execute.assert_called_once_with(risk, dry_run=True)

    def test_execute_delegates_dry_run_false(self):
        executor = _make_executor()
        executor.execute = MagicMock(  # type: ignore[method-assign]
            return_value=TestnetExecutionResult(
                success=True, operation="place_order"
            )
        )
        adapter = TestnetExecutorBotAdapter(testnet_executor=executor, dry_run=False)
        risk = _approved()

        adapter.execute(risk)

        executor.execute.assert_called_once_with(risk, dry_run=False)

    def test_execute_rejects_unapproved_invariant(self):
        """risk_result não-aprovado → BybitTestnetExecutor levanta ValueError."""
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_executor(), dry_run=True
        )
        with pytest.raises(ValueError):
            adapter.execute(_blocked())

    def test_returns_executor_result_object(self):
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_executor(), dry_run=True
        )
        result = adapter.execute(_approved())
        assert isinstance(result, TestnetExecutionResult)


# ---------------------------------------------------------------------------
# Acessadores
# ---------------------------------------------------------------------------

class TestAdapterAccessors:

    def test_executor_property_returns_underlying(self):
        executor = _make_executor()
        adapter = TestnetExecutorBotAdapter(testnet_executor=executor, dry_run=True)
        assert adapter.executor is executor

    def test_get_summary_includes_dry_run(self):
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=_make_executor(), dry_run=True
        )
        summary = adapter.get_summary()
        assert summary["dry_run"] is True
        # delega ao executor subjacente (sem secrets)
        assert "n_submitted" in summary
