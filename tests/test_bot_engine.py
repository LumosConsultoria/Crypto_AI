"""
Testes do BotEngine
====================
⚠️  ZERO chamadas à internet — usa MockExchange e dados determinísticos.

Cobertura:
    - Inicialização com dependências injetadas
    - run_once() → BotCycleResult com action correto em cada cenário
    - Ciclo com candles vazios → "no_candles"
    - Ciclo com candles insuficientes → "insufficient_data"
    - Ciclo com estratégia inativa → "hold" (evaluate retorna HOLD por estado)
    - Ciclo com HOLD intencional → "hold"
    - Ciclo com RiskEngine bloqueando → "risk_blocked" (determinístico via StubStrategy)
    - Ciclo feliz: sinal aprovado + trade executado → "executed" (determinístico via StubStrategy)
    - INVARIANTE: HOLD nunca gera executed=True
    - INVARIANTE: risk_blocked nunca gera executed=True
    - INVARIANTE: was_safe sempre True
    - INVARIANTE: PaperTrader nunca chamado sem aprovação do RiskEngine
    - Contagem de ciclos incrementa corretamente

Estratégia de testes:
    - Cenários com EmaRsiStrategy real: testam a estratégia de produção
      (no_candles, insufficient_data, warming_up, HOLD por tendência de baixa)
    - Cenários com StubStrategy: testam o fluxo do BotEngine de forma determinística
      (executed, risk_blocked, invariantes)
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

# Importa helpers determinísticos do conftest
from tests.helpers import StubStrategy, make_stub_engine

from crypto_trading_bot.config.settings import Settings
from crypto_trading_bot.core.bot_engine import BotEngine
from crypto_trading_bot.core.cycle_result import BotCycleResult
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.market_data import MarketDataService
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal


# ---------------------------------------------------------------------------
# Helpers — EmaRsiStrategy real (produção)
# ---------------------------------------------------------------------------

def _make_engine(
    n_candles: int = 60,
    rsi_overbought: float = 99.9,    # bypass RSI (próximo do máximo válido)
    position_size_usd: float = 200.0,
    initial_capital: float = 5000.0,
    trend: float = 50.0,
) -> tuple[BotEngine, EmaRsiStrategy, RiskEngine, PaperTrader]:
    """
    Cria BotEngine com EmaRsiStrategy real (estratégia de produção).

    Usar para testes que validam comportamento da EmaRsiStrategy ou
    cenários onde o resultado não precisa ser determinístico (ex: no_candles,
    insufficient_data, warming_up).

    Para cenários determinísticos (executed, risk_blocked), use make_stub_engine().
    """
    mock_exchange = MockExchange()
    if n_candles == 0:
        mock_exchange._price_history = []
    elif trend < 0:
        mock_exchange._price_history = [65000.0 + i * trend for i in range(n_candles)]
    else:
        mock_exchange._price_history = [65000.0 + i * trend for i in range(n_candles)]

    market_data = MarketDataService(exchange=mock_exchange, default_symbol="BTCUSDT")
    feature_engine = FeatureEngine()
    strategy = EmaRsiStrategy(
        rsi_overbought=rsi_overbought,
        position_size_usd=position_size_usd,
    )
    risk_engine = RiskEngine(initial_capital=initial_capital)
    paper_trader = PaperTrader(risk_engine=risk_engine)

    # Settings paper EXPLÍCITAS e isoladas do .env real (FASE 7: o .env local pode
    # estar em TRADING_MODE=testnet). trading_mode explícito > env/.env; _env_file=None
    # ignora o arquivo .env. Mantém result.mode/repr determinísticos em "paper".
    paper_settings = Settings(
        trading_mode="paper",
        enable_live_trading=False,
        enable_testnet_execution=False,
        _env_file=None,  # type: ignore[call-arg]
    )

    engine = BotEngine(
        market_data_service=market_data,
        feature_engine=feature_engine,
        strategy=strategy,
        risk_engine=risk_engine,
        paper_trader=paper_trader,
        settings=paper_settings,
    )
    return engine, strategy, risk_engine, paper_trader


# ---------------------------------------------------------------------------
# Testes de Inicialização
# ---------------------------------------------------------------------------

class TestBotEngineInit:
    """Testa a inicialização do BotEngine com injeção de dependências."""

    def test_bot_engine_initializes(self):
        engine, *_ = _make_engine()
        assert engine is not None

    def test_bot_engine_not_running_on_init(self):
        engine, *_ = _make_engine()
        assert engine.is_running is False

    def test_cycle_count_starts_at_zero(self):
        engine, *_ = _make_engine()
        assert engine.cycle_count == 0

    def test_repr_contains_mode_and_strategy(self):
        engine, *_ = _make_engine()
        r = repr(engine)
        assert "paper" in r
        assert "ema_rsi" in r

    def test_strategy_accessible(self):
        engine, strategy, *_ = _make_engine()
        assert engine.strategy is strategy

    def test_risk_engine_accessible(self):
        engine, _, risk_engine, _ = _make_engine()
        assert engine.risk_engine is risk_engine

    def test_paper_trader_accessible(self):
        engine, _, _, paper_trader = _make_engine()
        assert engine.paper_trader is paper_trader

    def test_stub_engine_initializes(self):
        """StubStrategy também funciona como estratégia injetável no BotEngine."""
        signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, strategy, *_ = make_stub_engine(signal)
        assert engine is not None
        assert isinstance(strategy, StubStrategy)


# ---------------------------------------------------------------------------
# Testes de Ciclos com Dados Ausentes / Insuficientes (EmaRsiStrategy real)
# ---------------------------------------------------------------------------

class TestBotEngineSafeReturns:
    """Testa retornos seguros quando dados são insuficientes."""

    def test_no_candles_returns_no_candles_action(self):
        """MockExchange sem candles → action='no_candles'."""
        engine, strategy, *_ = _make_engine(n_candles=0)
        strategy.set_running()
        result = engine.run_once()
        assert result.action == "no_candles"

    def test_no_candles_not_executed(self):
        engine, strategy, *_ = _make_engine(n_candles=0)
        strategy.set_running()
        result = engine.run_once()
        assert result.executed is False
        assert result.risk_approved is False

    def test_insufficient_data_action(self):
        """Poucos candles para FeatureEngine → action='insufficient_data'."""
        engine, strategy, *_ = _make_engine(n_candles=5)
        strategy.set_running()
        result = engine.run_once()
        assert result.action == "insufficient_data"

    def test_insufficient_data_not_executed(self):
        engine, strategy, *_ = _make_engine(n_candles=5)
        strategy.set_running()
        result = engine.run_once()
        assert result.executed is False

    def test_insufficient_data_n_candles_recorded(self):
        engine, strategy, *_ = _make_engine(n_candles=5)
        strategy.set_running()
        result = engine.run_once()
        assert result.n_candles == 5


# ---------------------------------------------------------------------------
# Testes de HOLD (EmaRsiStrategy real — WARMING_UP garantido)
# ---------------------------------------------------------------------------

class TestBotEngineHold:
    """Testa que HOLD nunca é executado."""

    def test_warming_up_strategy_returns_hold(self):
        """Estratégia em WARMING_UP → evaluate() retorna HOLD → action='hold'."""
        engine, strategy, *_ = _make_engine(n_candles=60)
        # strategy está em WARMING_UP (não chamamos set_running())
        result = engine.run_once()
        assert result.action == "hold"
        assert result.executed is False

    def test_hold_never_executed_downtrend(self):
        """Tendência de baixa → EMA9 < EMA21 → HOLD (determinístico)."""
        engine, strategy, *_ = _make_engine(n_candles=60, trend=-50.0)
        strategy.set_running()
        result = engine.run_once()
        # Trend negativo garante EMA9 < EMA21 → HOLD
        assert result.executed is False
        assert result.risk_approved is False

    def test_hold_was_safe_is_true(self):
        engine, *_ = _make_engine(n_candles=60)
        result = engine.run_once()  # strategy em WARMING_UP → HOLD
        assert result.was_safe is True

    def test_hold_has_strategy_signal(self):
        """Mesmo em HOLD, um StrategySignal é registrado no resultado."""
        engine, *_ = _make_engine(n_candles=60)
        result = engine.run_once()  # WARMING_UP → HOLD
        assert result.strategy_signal is not None
        assert result.strategy_signal.action == StrategyAction.HOLD

    def test_stub_hold_action_is_deterministic(self):
        """StubStrategy(HOLD) → action SEMPRE é 'hold' (sem aleatoriedade)."""
        hold_signal = StrategySignal.hold("BTCUSDT", "stub", reason="teste")
        engine, *_ = make_stub_engine(hold_signal, n_candles=60)
        result = engine.run_once()
        assert result.action == "hold"  # sem condicional — garantido por StubStrategy

    def test_stub_hold_never_reaches_risk_engine(self):
        """HOLD → risk_approved=False (RiskEngine não foi chamado)."""
        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, *_ = make_stub_engine(hold_signal, n_candles=60)
        result = engine.run_once()
        assert result.action == "hold"
        assert result.risk_approved is False  # sem condicional


# ---------------------------------------------------------------------------
# Testes de Bloqueio pelo RiskEngine (determinístico via StubStrategy)
# ---------------------------------------------------------------------------

class TestBotEngineRiskBlocked:
    """Testa que sinal bloqueado pelo RiskEngine não é executado."""

    def test_risk_blocked_action_is_deterministic(self):
        """
        StubStrategy(BUY) + capital=1.0 → RiskEngine DEVE bloquear.
        required=200 > capital=1.0 → bloqueio garantido.
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, _ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "risk_blocked"  # sem condicional

    def test_risk_blocked_executed_false(self):
        """Sinal bloqueado NUNCA gera executed=True."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, _ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "risk_blocked"
        assert result.executed is False  # sem condicional

    def test_risk_blocked_risk_approved_false(self):
        """risk_blocked → risk_approved=False."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, _ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "risk_blocked"
        assert result.risk_approved is False  # sem condicional

    def test_risk_blocked_was_safe(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, _ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "risk_blocked"
        assert result.was_safe is True  # sem condicional

    def test_paper_trader_not_called_when_risk_blocks(self):
        """PaperTrader NÃO deve ser chamado quando RiskEngine bloqueia."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()

        assert result.action == "risk_blocked"
        assert len(paper_trader._open_trades) == 0  # sem condicional


# ---------------------------------------------------------------------------
# Testes do Ciclo Completo (Happy Path — determinístico via StubStrategy)
# ---------------------------------------------------------------------------

class TestBotEngineExecution:
    """Testa o ciclo completo com sinal aprovado e trade executado."""

    def test_executed_action_is_deterministic(self):
        """
        StubStrategy(BUY) + capital=5000 → action DEVE ser 'executed'.
        Cenário controlado — sem aleatoriedade.
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"  # sem condicional

    def test_executed_has_risk_approved_true(self):
        """executed=True → risk_approved DEVE ser True (invariante)."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.risk_approved is True  # sem condicional

    def test_executed_has_executed_true(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.executed is True  # sem condicional

    def test_executed_has_trade(self):
        """executed=True → result.trade não pode ser None."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.trade is not None  # sem condicional

    def test_cycle_count_increments(self):
        engine, strategy, *_ = _make_engine(n_candles=60)
        strategy.set_running()

        assert engine.cycle_count == 0
        engine.run_once()
        assert engine.cycle_count == 1
        engine.run_once()
        assert engine.cycle_count == 2

    def test_executed_paper_trader_has_open_trade(self):
        """Quando executado, PaperTrader deve ter trade em _open_trades."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert len(paper_trader._open_trades) == 1  # sem condicional

    def test_executed_was_safe_true(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.was_safe is True  # sem condicional


# ---------------------------------------------------------------------------
# Testes de Invariantes de Segurança
# ---------------------------------------------------------------------------

class TestBotEngineInvariants:
    """Testa as invariantes de segurança do BotEngine."""

    def test_was_safe_always_true_no_candles(self):
        engine, strategy, *_ = _make_engine(n_candles=0)
        strategy.set_running()
        result = engine.run_once()
        assert result.was_safe is True

    def test_was_safe_always_true_insufficient(self):
        engine, strategy, *_ = _make_engine(n_candles=5)
        strategy.set_running()
        result = engine.run_once()
        assert result.was_safe is True

    def test_was_safe_always_true_hold(self):
        engine, *_ = _make_engine(n_candles=60)
        result = engine.run_once()
        assert result.was_safe is True

    def test_was_safe_always_true_after_execution(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.was_safe is True

    def test_result_has_required_fields(self):
        """BotCycleResult deve ter todos os campos obrigatórios."""
        engine, *_ = _make_engine(n_candles=60)
        result = engine.run_once()

        assert hasattr(result, "symbol")
        assert hasattr(result, "action")
        assert hasattr(result, "risk_approved")
        assert hasattr(result, "executed")
        assert hasattr(result, "reason")
        assert hasattr(result, "timestamp")
        assert hasattr(result, "strategy_name")

    def test_result_symbol_matches_settings(self):
        engine, *_ = _make_engine()
        result = engine.run_once()
        assert result.symbol == "BTCUSDT"

    def test_result_strategy_name_matches_ema_rsi(self):
        engine, strategy, *_ = _make_engine()
        result = engine.run_once()
        assert result.strategy_name == strategy.name

    def test_result_strategy_name_matches_stub(self):
        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, strategy, *_ = make_stub_engine(hold_signal)
        result = engine.run_once()
        assert result.strategy_name == "stub_strategy"

    def test_result_mode_is_paper(self):
        engine, *_ = _make_engine()
        result = engine.run_once()
        assert result.mode == "paper"

    def test_cycle_result_has_timestamp(self):
        engine, *_ = _make_engine()
        result = engine.run_once()
        assert isinstance(result.timestamp, datetime)

    def test_to_dict_has_required_keys(self):
        engine, *_ = _make_engine()
        result = engine.run_once()
        d = result.to_dict()
        for key in ["symbol", "action", "risk_approved", "executed", "reason",
                    "timestamp", "strategy_name", "was_safe"]:
            assert key in d, f"Chave ausente: {key}"

    def test_multiple_cycles_all_safe(self):
        """Múltiplos ciclos consecutivos devem ser todos seguros."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        for _ in range(5):
            result = engine.run_once()
            assert result.was_safe is True

    def test_hold_never_gets_risk_approved(self):
        """HOLD → risk_approved DEVE ser False (sem condicional)."""
        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, *_ = make_stub_engine(hold_signal, n_candles=60)
        result = engine.run_once()
        assert result.action == "hold"
        assert result.risk_approved is False  # sem condicional

    def test_executed_requires_risk_approved(self):
        """executed=True → risk_approved DEVE ser True (sem condicional)."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.executed is True
        assert result.risk_approved is True  # sem condicional


# ---------------------------------------------------------------------------
# Testes de Start/Stop
# ---------------------------------------------------------------------------

class TestBotEngineStartStop:
    """Testa os métodos start/stop do loop contínuo."""

    def test_start_and_stop(self):
        """start() sobe o flag running; stop() desce."""
        import threading
        import time

        engine, strategy, *_ = _make_engine(n_candles=0)
        strategy.set_running()
        engine._cycle_interval_seconds = 0.05  # ciclo rápido para teste

        done = threading.Event()

        def _run():
            engine.start()
            done.set()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        time.sleep(0.15)
        engine.stop()
        done.wait(timeout=2.0)

        assert engine.is_running is False

    def test_stop_without_start_is_safe(self):
        """Chamar stop() sem start() não deve gerar erro."""
        engine, *_ = _make_engine()
        engine.stop()
        assert engine.is_running is False

    def test_get_cycle_summary_structure(self):
        engine, strategy, *_ = _make_engine(n_candles=60)
        strategy.set_running()
        engine.run_once()

        summary = engine.get_cycle_summary()
        assert "cycle_count" in summary
        assert "mode" in summary
        assert "strategy" in summary
        assert "risk_summary" in summary


# ---------------------------------------------------------------------------
# Quality gate: record_trade_opened tem UMA única fonte de verdade (executor)
# Regressão do bug FASE 6 onde o BotEngine duplicava o registro de abertura.
# ---------------------------------------------------------------------------

class TestRecordTradeOpenedSingleSource:
    """O registro de abertura de trade deve ocorrer EXATAMENTE uma vez.

    Fonte de verdade: o executor (PaperTrader). O BotEngine NÃO pode chamar
    record_trade_opened — fazê-lo duplicava trades_today/exposição.
    """

    def test_paper_executed_records_exactly_once(self):
        from unittest.mock import MagicMock

        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _strat, risk, _paper = make_stub_engine(
            buy_signal, capital=5000.0, n_candles=60
        )
        spy = MagicMock(wraps=risk.record_trade_opened)
        risk.record_trade_opened = spy

        result = engine.run_once()

        assert result.action == "executed"
        assert spy.call_count == 1  # exatamente UMA vez (era 2 antes do fix)

    def test_paper_executed_state_reflects_single_trade(self):
        """trades_today=1 e exposição=size — não duplicados."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _strat, risk, _paper = make_stub_engine(
            buy_signal, capital=5000.0, n_candles=60
        )
        engine.run_once()

        summary = risk.get_status_summary()
        assert summary["trades_today"] == 1
        assert summary["open_positions"]["BTCUSDT"] == 200.0
        assert summary["total_open_exposure"] == 200.0

    def test_risk_blocked_records_zero_times(self):
        from unittest.mock import MagicMock

        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        # capital=1.0 → RiskEngine bloqueia
        engine, _strat, risk, _paper = make_stub_engine(
            buy_signal, capital=1.0, n_candles=60
        )
        spy = MagicMock(wraps=risk.record_trade_opened)
        risk.record_trade_opened = spy

        result = engine.run_once()

        assert result.action == "risk_blocked"
        assert spy.call_count == 0

    def test_hold_records_zero_times(self):
        from unittest.mock import MagicMock

        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, _strat, risk, _paper = make_stub_engine(hold_signal, n_candles=60)
        spy = MagicMock(wraps=risk.record_trade_opened)
        risk.record_trade_opened = spy

        result = engine.run_once()

        assert result.action == "hold"
        assert spy.call_count == 0

    def test_legacy_trade_field_still_populated(self):
        """BotCycleResult.trade legado continua preenchido no path paper."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.action == "executed"
        assert result.trade is not None
        assert result.executor_result is not None
        assert result.executor_result is result.trade
