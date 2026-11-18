"""
Testes de integração BotEngine ↔ executor injetado — FASE 6
=============================================================
⚠️  ZERO chamadas à internet (BybitClient mockado). ZERO API key real.
⚠️  ZERO ordens reais. Testnet sempre dry_run=True nestes testes.
⚠️  PaperTrader continua sendo o caminho default/legado.

Cobertura:
    - BotEngine exige EXATAMENTE UM entre paper_trader e executor:
        * ambos → ValueError
        * nenhum → ValueError
    - Caminho legado (paper_trader) continua funcionando E agora preenche
      executor_result (paralelo ao trade legado).
    - Caminho novo (TestnetExecutorBotAdapter, dry_run=True):
        * ciclo feliz → action="executed", executed=True,
          executor_result é TestnetExecutionResult, trade preservado.
        * RiskEngine bloqueia ANTES do executor (capital insuficiente) →
          action="risk_blocked", executor.execute NUNCA chamado.
        * dry_run=True NUNCA chama BybitClient privado (place_market_order).
    - INVARIANTE: was_safe sempre True.
    - INVARIANTE: HOLD nunca chama o executor.
    - get_cycle_summary expõe executor_summary quando não há paper_trader.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.bot_engine import BotEngine
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.market_data import MarketDataService
from crypto_trading_bot.exchange.bybit_client import BybitClient
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.bybit_testnet_executor import (
    BybitTestnetExecutor,
    TestnetExecutionResult,
)
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.execution.testnet_executor_adapter import (
    TestnetExecutorBotAdapter,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.helpers import StubStrategy


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


def _make_mock_client() -> MagicMock:
    client = MagicMock(spec=BybitClient)
    type(client).use_testnet = property(lambda self: True)
    type(client).has_credentials = property(lambda self: True)
    return client


def _make_pipeline(capital: float, n_candles: int = 60):
    """Constrói (market_data, feature_engine, strategy, risk_engine)."""
    mock_exchange = MockExchange()
    mock_exchange._price_history = [65000.0 + i * 50.0 for i in range(n_candles)]
    market_data = MarketDataService(exchange=mock_exchange, default_symbol="BTCUSDT")
    feature_engine = FeatureEngine()

    buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
    strategy = StubStrategy(signal=buy_signal)
    strategy.set_running()

    risk_engine = RiskEngine(initial_capital=capital)
    return market_data, feature_engine, strategy, risk_engine, mock_exchange


def _make_testnet_adapter(risk_engine: RiskEngine, client: MagicMock | None = None):
    client = client or _make_mock_client()
    guard = ModeGuard(settings=_settings_testnet_ready())
    executor = BybitTestnetExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk_engine,
        confirm_testnet_execution=True,
    )
    adapter = TestnetExecutorBotAdapter(testnet_executor=executor, dry_run=True)
    return adapter, executor, client


# ---------------------------------------------------------------------------
# Validação de construção: exatamente UM executor
# ---------------------------------------------------------------------------

class TestExecutorConstructionRules:

    def test_both_paper_and_executor_raises(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        paper = PaperTrader(risk_engine=risk)
        adapter, _, _ = _make_testnet_adapter(risk)
        with pytest.raises(ValueError, match="EXATAMENTE UM"):
            BotEngine(
                market_data_service=md,
                feature_engine=fe,
                strategy=strat,
                risk_engine=risk,
                paper_trader=paper,
                executor=adapter,
            )

    def test_neither_paper_nor_executor_raises(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        with pytest.raises(ValueError):
            BotEngine(
                market_data_service=md,
                feature_engine=fe,
                strategy=strat,
                risk_engine=risk,
            )

    def test_paper_only_constructs(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        paper = PaperTrader(risk_engine=risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, paper_trader=paper,
        )
        assert engine.paper_trader is paper
        assert engine.executor is None
        assert engine.active_executor is paper

    def test_executor_only_constructs(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        adapter, _, _ = _make_testnet_adapter(risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        assert engine.paper_trader is None
        assert engine.executor is adapter
        assert engine.active_executor is adapter


# ---------------------------------------------------------------------------
# Caminho legado (paper) — regressão + executor_result paralelo
# ---------------------------------------------------------------------------

class TestPaperPathStillWorks:

    def test_paper_executed_populates_executor_result(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        paper = PaperTrader(risk_engine=risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, paper_trader=paper,
        )
        result = engine.run_once()
        assert result.action == "executed"
        assert result.executed is True
        # legado preservado
        assert result.trade is not None
        # FASE 6: novo campo paralelo preenchido
        assert result.executor_result is not None
        # no caminho paper, executor_result e trade são o mesmo objeto (retorno
        # do PaperTrader.execute — comportamento idêntico ao anterior).
        assert result.executor_result is result.trade

    def test_paper_summary_present_legacy(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        paper = PaperTrader(risk_engine=risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, paper_trader=paper,
        )
        engine.run_once()
        summary = engine.get_cycle_summary()
        assert "paper_summary" in summary
        assert "executor_summary" not in summary


# ---------------------------------------------------------------------------
# Caminho novo (testnet adapter dry_run)
# ---------------------------------------------------------------------------

class TestTestnetExecutorPath:

    def test_executed_cycle_with_testnet_dry_run(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        adapter, _, client = _make_testnet_adapter(risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        result = engine.run_once()

        assert result.action == "executed"
        assert result.executed is True
        assert isinstance(result.executor_result, TestnetExecutionResult)
        assert result.executor_result.dry_run is True
        assert result.executor_result.success is True
        # trade legado preservado (mesmo objeto que executor_result)
        assert result.trade is result.executor_result
        # dry_run NÃO chama API privada
        client.place_market_order.assert_not_called()

    def test_risk_blocked_before_testnet_executor(self):
        """Capital insuficiente → RiskEngine bloqueia ANTES do executor."""
        md, fe, strat, risk, _ = _make_pipeline(capital=1.0)
        adapter, executor, client = _make_testnet_adapter(risk)
        # Espiona o execute do adapter para provar que NÃO foi chamado
        spy = MagicMock(wraps=adapter.execute)
        adapter.execute = spy  # type: ignore[method-assign]

        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        result = engine.run_once()

        assert result.action == "risk_blocked"
        assert result.executed is False
        spy.assert_not_called()
        client.place_market_order.assert_not_called()

    def test_hold_never_calls_testnet_executor(self):
        md, fe, _strat, risk, _ = _make_pipeline(capital=5000.0)
        hold_signal = StrategySignal.hold("BTCUSDT", "stub", reason="teste hold")
        strat = StubStrategy(signal=hold_signal)
        strat.set_running()
        adapter, _, client = _make_testnet_adapter(risk)
        spy = MagicMock(wraps=adapter.execute)
        adapter.execute = spy  # type: ignore[method-assign]

        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        result = engine.run_once()

        assert result.action == "hold"
        assert result.executed is False
        spy.assert_not_called()
        client.place_market_order.assert_not_called()

    def test_was_safe_always_true_testnet_path(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        adapter, _, _ = _make_testnet_adapter(risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        result = engine.run_once()
        assert result.was_safe is True

    def test_get_cycle_summary_has_executor_summary(self):
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        adapter, _, _ = _make_testnet_adapter(risk)
        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        engine.run_once()
        summary = engine.get_cycle_summary()
        assert "executor_summary" in summary
        assert "paper_summary" not in summary
        assert summary["executor_summary"]["dry_run"] is True


# ---------------------------------------------------------------------------
# Quality gate: BotEngine NÃO chama record_trade_opened no path executor
# (o executor é a única fonte de verdade — sem duplicação).
# ---------------------------------------------------------------------------

class TestRecordTradeOpenedExecutorPath:

    def test_botengine_does_not_record_on_executor_path(self):
        """Executor mockado: BotEngine NÃO chama record_trade_opened.

        Como o mock não registra e o BotEngine também não, a contagem é 0 —
        provando que o BotEngine não é fonte de registro (sem duplicação).
        """
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        mock_executor = MagicMock()
        mock_executor.execute.return_value = MagicMock(name="exec_result")

        spy = MagicMock(wraps=risk.record_trade_opened)
        risk.record_trade_opened = spy

        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=mock_executor,
        )
        result = engine.run_once()

        assert result.action == "executed"
        mock_executor.execute.assert_called_once()
        # BotEngine não registrou; mock não registrou → 0 (sem duplicação)
        assert spy.call_count == 0

    def test_testnet_dry_run_does_not_record(self):
        """dry_run não confirma fill → executor não registra; BotEngine também não."""
        md, fe, strat, risk, _ = _make_pipeline(capital=5000.0)
        adapter, _, _ = _make_testnet_adapter(risk)  # dry_run=True
        spy = MagicMock(wraps=risk.record_trade_opened)
        risk.record_trade_opened = spy

        engine = BotEngine(
            market_data_service=md, feature_engine=fe, strategy=strat,
            risk_engine=risk, executor=adapter,
        )
        result = engine.run_once()

        assert result.action == "executed"
        assert result.executor_result.dry_run is True
        assert spy.call_count == 0
