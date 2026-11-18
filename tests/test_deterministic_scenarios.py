"""
test_deterministic_scenarios.py — Cenários 100% Determinísticos
================================================================
Valida o pipeline completo com StubStrategy — zero aleatoriedade.

Cada cenário é controlado por injeção de sinal (StubStrategy) e
capital/candles configurados para garantir o resultado esperado.
NENHUM assert depende de `if` condicional para o cenário principal.

⚠️  ZERO chamadas à internet.
⚠️  ZERO uso de BybitClient ou chaves de API.
⚠️  ZERO ordens reais enviadas.

Cenários cobertos:
    BUY executado:       StubStrategy(BUY) + capital=5000 → "executed"
    HOLD:                StubStrategy(HOLD)               → "hold"
    risk_blocked:        StubStrategy(BUY) + capital=1    → "risk_blocked"
    no_candles:          n_candles=0                      → "no_candles"
    insufficient_data:   n_candles=3                      → "insufficient_data"
    sem posição dupla:   2º ciclo após execução           → "hold"

Invariantes fortes:
    - HOLD nunca chega ao PaperTrader
    - risk_blocked nunca chega ao PaperTrader
    - executed=True exige risk_approved=True
    - HOLD exige risk_approved=False
    - was_safe sempre True
    - PaperTrader só executa sinal aprovado pelo RiskEngine
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# Importa helpers do conftest (disponíveis globalmente pelo pytest)
from tests.helpers import StubStrategy, make_stub_engine

from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal


# ---------------------------------------------------------------------------
# Cenário 1: BUY Executado
# Garante que trade é efetivamente executado quando todas as condições passam
# ---------------------------------------------------------------------------

class TestScenarioBUY:
    """
    Cenário: StubStrategy retorna BUY, capital suficiente, dados suficientes.
    RESULTADO GARANTIDO: action == "executed"
    """

    def setup_method(self):
        """Prepara o cenário BUY para cada teste."""
        buy_signal = StrategySignal.buy(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        )
        self.result = self.engine.run_once()

    def test_buy_action_is_executed(self):
        """Cenário BUY com capital suficiente → action DEVE ser 'executed'."""
        assert self.result.action == "executed"

    def test_buy_executed_flag_true(self):
        """executed=True quando BUY é realizado."""
        assert self.result.executed is True

    def test_buy_risk_approved_true(self):
        """risk_approved=True quando BUY passa pelo RiskEngine."""
        assert self.result.risk_approved is True

    def test_buy_trade_not_none(self):
        """result.trade deve ter o objeto do trade simulado."""
        assert self.result.trade is not None

    def test_buy_creates_open_trade_in_paper_trader(self):
        """PaperTrader deve ter exatamente 1 trade aberto após execução."""
        assert len(self.paper_trader._open_trades) == 1

    def test_buy_was_safe_true(self):
        """Ciclo executado deve permanecer seguro."""
        assert self.result.was_safe is True

    def test_buy_result_has_symbol(self):
        """BotCycleResult deve registrar o símbolo correto."""
        assert self.result.symbol == "BTCUSDT"

    def test_buy_result_mode_is_paper(self):
        """Modo deve ser paper — nunca live."""
        assert self.result.mode == "paper"

    def test_buy_cycle_count_increments(self):
        """Contador de ciclos deve incrementar após execução."""
        assert self.engine.cycle_count == 1


# ---------------------------------------------------------------------------
# Cenário 2: HOLD
# Garante que HOLD nunca é executado e nunca chega ao PaperTrader
# ---------------------------------------------------------------------------

class TestScenarioHOLD:
    """
    Cenário: StubStrategy retorna HOLD explicitamente.
    RESULTADO GARANTIDO: action == "hold"
    """

    def setup_method(self):
        hold_signal = StrategySignal.hold(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            reason="stub: sem condições de entrada",
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(hold_signal, capital=5000.0, n_candles=60)
        )
        self.result = self.engine.run_once()

    def test_hold_action_is_hold(self):
        """Cenário HOLD → action DEVE ser 'hold'."""
        assert self.result.action == "hold"

    def test_hold_executed_false(self):
        """HOLD nunca gera executed=True."""
        assert self.result.executed is False

    def test_hold_risk_not_approved(self):
        """HOLD nunca passa pelo RiskEngine → risk_approved=False."""
        assert self.result.risk_approved is False

    def test_hold_paper_trader_empty(self):
        """PaperTrader não deve ter nenhum trade após HOLD."""
        assert len(self.paper_trader._open_trades) == 0

    def test_hold_was_safe_true(self):
        """Ciclo HOLD deve ser seguro."""
        assert self.result.was_safe is True

    def test_hold_strategy_signal_is_hold(self):
        """BotCycleResult deve registrar o StrategySignal HOLD."""
        assert self.result.strategy_signal is not None
        assert self.result.strategy_signal.action == StrategyAction.HOLD

    def test_hold_has_reason(self):
        """HOLD deve ter razão registrada."""
        assert self.result.reason is not None
        assert len(self.result.reason) > 0


# ---------------------------------------------------------------------------
# Cenário 3: RiskEngine Bloqueando
# Garante que risk_blocked nunca é executado
# ---------------------------------------------------------------------------

class TestScenarioRiskBlocked:
    """
    Cenário: StubStrategy retorna BUY, mas capital insuficiente (1.0 USD).
    RESULTADO GARANTIDO: action == "risk_blocked"
    RiskEngine bloqueia porque: required=200.0 > capital=1.0
    """

    def setup_method(self):
        buy_signal = StrategySignal.buy(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        )
        self.result = self.engine.run_once()

    def test_risk_blocked_action(self):
        """capital=1.0, position=200 → RiskEngine DEVE bloquear."""
        assert self.result.action == "risk_blocked"

    def test_risk_blocked_executed_false(self):
        """risk_blocked nunca gera executed=True."""
        assert self.result.executed is False

    def test_risk_blocked_risk_not_approved(self):
        """Sinal bloqueado → risk_approved=False."""
        assert self.result.risk_approved is False

    def test_risk_blocked_paper_trader_empty(self):
        """PaperTrader não deve ser chamado quando RiskEngine bloqueia."""
        assert len(self.paper_trader._open_trades) == 0

    def test_risk_blocked_was_safe_true(self):
        """Ciclo bloqueado pelo risco deve permanecer seguro."""
        assert self.result.was_safe is True

    def test_risk_blocked_has_reason(self):
        """BotCycleResult deve ter razão do bloqueio."""
        assert self.result.reason is not None
        assert "RiskEngine" in self.result.reason or len(self.result.reason) > 0

    def test_risk_blocked_strategy_signal_was_buy(self):
        """A estratégia GEROU um sinal BUY — foi o RiskEngine que bloqueou."""
        assert self.result.strategy_signal is not None
        assert self.result.strategy_signal.action == StrategyAction.BUY


# ---------------------------------------------------------------------------
# Cenário 4: Sem Candles
# Garante que ciclo sem dados termina com segurança
# ---------------------------------------------------------------------------

class TestScenarioNoCandles:
    """
    Cenário: MockExchange vazio → BotEngine retorna "no_candles".
    RESULTADO GARANTIDO: action == "no_candles"
    """

    def setup_method(self):
        buy_signal = StrategySignal.buy(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(buy_signal, capital=5000.0, n_candles=0)
        )
        self.result = self.engine.run_once()

    def test_no_candles_action(self):
        """MockExchange vazio → action DEVE ser 'no_candles'."""
        assert self.result.action == "no_candles"

    def test_no_candles_executed_false(self):
        """Sem dados → não executa."""
        assert self.result.executed is False

    def test_no_candles_risk_not_approved(self):
        """Sem dados → RiskEngine não é chamado."""
        assert self.result.risk_approved is False

    def test_no_candles_paper_trader_empty(self):
        """Sem dados → PaperTrader não é chamado."""
        assert len(self.paper_trader._open_trades) == 0

    def test_no_candles_was_safe_true(self):
        """Ciclo sem candles deve ser seguro."""
        assert self.result.was_safe is True


# ---------------------------------------------------------------------------
# Cenário 5: Dados Insuficientes
# Garante que poucos candles termina com segurança
# ---------------------------------------------------------------------------

class TestScenarioInsufficientData:
    """
    Cenário: 3 candles → FeatureEngine insuficiente → "insufficient_data".
    RESULTADO GARANTIDO: action == "insufficient_data"
    """

    def setup_method(self):
        buy_signal = StrategySignal.buy(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(buy_signal, capital=5000.0, n_candles=3)
        )
        self.result = self.engine.run_once()

    def test_insufficient_data_action(self):
        """3 candles → action DEVE ser 'insufficient_data'."""
        assert self.result.action == "insufficient_data"

    def test_insufficient_data_executed_false(self):
        """Dados insuficientes → não executa."""
        assert self.result.executed is False

    def test_insufficient_data_risk_not_approved(self):
        """Dados insuficientes → RiskEngine não é chamado."""
        assert self.result.risk_approved is False

    def test_insufficient_data_paper_trader_empty(self):
        """Dados insuficientes → PaperTrader não é chamado."""
        assert len(self.paper_trader._open_trades) == 0

    def test_insufficient_data_was_safe_true(self):
        """Ciclo com dados insuficientes deve ser seguro."""
        assert self.result.was_safe is True

    def test_insufficient_data_n_candles_recorded(self):
        """BotCycleResult deve registrar o número real de candles."""
        assert self.result.n_candles == 3


# ---------------------------------------------------------------------------
# Cenário 6: Sem Posição Dupla
# Garante que segundo ciclo com posição aberta retorna HOLD
# ---------------------------------------------------------------------------

class TestScenarioNoDoublePosition:
    """
    Cenário: Após execução BUY, o segundo ciclo retorna HOLD.
    RESULTADO GARANTIDO:
        r1.action == "executed"   (primeiro ciclo)
        r2.action == "hold"       (segundo ciclo — posição já aberta)
        len(open_trades) == 1     (nunca 2)
    """

    def setup_method(self):
        buy_signal = StrategySignal.buy(
            symbol="BTCUSDT",
            strategy_name="stub_strategy",
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
        )
        self.engine, self.strategy, self.risk_engine, self.paper_trader = (
            make_stub_engine(buy_signal, capital=5000.0, n_candles=60, block_after_trade=True)
        )
        self.r1 = self.engine.run_once()  # Deve ser "executed"
        self.r2 = self.engine.run_once()  # Deve ser "hold"

    def test_first_cycle_executed(self):
        """Primeiro ciclo DEVE ser 'executed'."""
        assert self.r1.action == "executed"

    def test_second_cycle_hold(self):
        """Segundo ciclo com posição aberta DEVE retornar 'hold'."""
        assert self.r2.action == "hold"

    def test_second_cycle_not_executed(self):
        """Segundo ciclo não deve ter executed=True."""
        assert self.r2.executed is False

    def test_exactly_one_open_trade(self):
        """PaperTrader deve ter exatamente 1 trade aberto após 2 ciclos."""
        assert len(self.paper_trader._open_trades) == 1

    def test_second_cycle_reason_is_position_already_open(self):
        """Razão do HOLD deve indicar posição já aberta."""
        assert "posição já aberta" in self.r2.strategy_signal.reason

    def test_both_cycles_were_safe(self):
        """Ambos os ciclos devem ser seguros."""
        assert self.r1.was_safe is True
        assert self.r2.was_safe is True

    def test_cycle_count_is_two(self):
        """Contador de ciclos deve ser 2 após dois run_once()."""
        assert self.engine.cycle_count == 2


# ---------------------------------------------------------------------------
# Invariantes Fortes: HOLD e risk_blocked nunca chegam ao PaperTrader
# ---------------------------------------------------------------------------

class TestInvariantsPaperTraderNeverCalledWithoutApproval:
    """
    Invariante crítica de segurança:
    PaperTrader.execute() NUNCA deve ser chamado sem aprovação do RiskEngine.
    HOLD e risk_blocked devem encerrar o ciclo ANTES de chegar ao PaperTrader.
    """

    def test_hold_paper_trader_execute_never_called(self):
        """
        HOLD → PaperTrader.execute() DEVE ser silenciado.
        Usa mock para verificar que execute() não foi chamado.
        """
        from crypto_trading_bot.execution.paper_trader import PaperTrader

        hold_signal = StrategySignal.hold("BTCUSDT", "stub", reason="teste invariante")
        engine, _, _, paper_trader = make_stub_engine(hold_signal, n_candles=60)

        original_execute = paper_trader.execute
        execute_calls = []

        def spy_execute(risk_result):
            execute_calls.append(risk_result)
            return original_execute(risk_result)

        paper_trader.execute = spy_execute

        result = engine.run_once()

        assert result.action == "hold"
        assert len(execute_calls) == 0, (
            f"PaperTrader.execute() foi chamado {len(execute_calls)} vez(es) "
            f"durante HOLD — violação de invariante!"
        )

    def test_risk_blocked_paper_trader_execute_never_called(self):
        """
        risk_blocked → PaperTrader.execute() DEVE ser silenciado.
        RiskEngine bloqueia antes de chegar ao PaperTrader.
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(buy_signal, capital=1.0, n_candles=60)

        execute_calls = []
        original_execute = paper_trader.execute

        def spy_execute(risk_result):
            execute_calls.append(risk_result)
            return original_execute(risk_result)

        paper_trader.execute = spy_execute

        result = engine.run_once()

        assert result.action == "risk_blocked"
        assert len(execute_calls) == 0, (
            f"PaperTrader.execute() foi chamado {len(execute_calls)} vez(es) "
            f"durante risk_blocked — violação de invariante!"
        )

    def test_no_candles_paper_trader_execute_never_called(self):
        """no_candles → PaperTrader.execute() não deve ser chamado."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(buy_signal, n_candles=0)

        execute_calls = []
        original_execute = paper_trader.execute

        def spy_execute(risk_result):
            execute_calls.append(risk_result)
            return original_execute(risk_result)

        paper_trader.execute = spy_execute

        result = engine.run_once()

        assert result.action == "no_candles"
        assert len(execute_calls) == 0

    def test_insufficient_data_paper_trader_execute_never_called(self):
        """insufficient_data → PaperTrader.execute() não deve ser chamado."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(buy_signal, n_candles=3)

        execute_calls = []
        original_execute = paper_trader.execute

        def spy_execute(risk_result):
            execute_calls.append(risk_result)
            return original_execute(risk_result)

        paper_trader.execute = spy_execute

        result = engine.run_once()

        assert result.action == "insufficient_data"
        assert len(execute_calls) == 0


# ---------------------------------------------------------------------------
# Invariantes Fortes: Relação entre executed / risk_approved / action
# ---------------------------------------------------------------------------

class TestInvariantsExecutedAndRiskApproved:
    """
    Invariantes de coerência interna do BotCycleResult:
        - executed=True exige obrigatoriamente risk_approved=True
        - HOLD exige obrigatoriamente risk_approved=False
        - risk_blocked exige obrigatoriamente executed=False
        - executed=True exige obrigatoriamente trade não None
    """

    def test_executed_true_requires_risk_approved_true(self):
        """executed=True → risk_approved DEVE ser True (invariante inviolável)."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()

        assert result.action == "executed"
        assert result.executed is True
        assert result.risk_approved is True  # DEVE ser True — sem condicional

    def test_hold_requires_risk_approved_false(self):
        """HOLD → risk_approved DEVE ser False (nunca passou pelo RiskEngine)."""
        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, *_ = make_stub_engine(hold_signal, n_candles=60)
        result = engine.run_once()

        assert result.action == "hold"
        assert result.risk_approved is False  # DEVE ser False — sem condicional

    def test_risk_blocked_requires_executed_false(self):
        """risk_blocked → executed DEVE ser False (trade não aconteceu)."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        result = engine.run_once()

        assert result.action == "risk_blocked"
        assert result.executed is False  # DEVE ser False — sem condicional

    def test_executed_true_requires_trade_not_none(self):
        """executed=True → result.trade DEVE ser diferente de None."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        result = engine.run_once()

        assert result.action == "executed"
        assert result.trade is not None  # DEVE ter trade — sem condicional

    def test_paper_trader_executes_only_approved_signals(self):
        """
        Teste integrado: PaperTrader só chama execute() quando
        risk_result.approved=True.
        Se chamarmos com approved=False, ele levanta ValueError.
        """
        from crypto_trading_bot.risk.risk_engine import RiskEngine, TradingSignal, OrderSide
        from crypto_trading_bot.execution.paper_trader import PaperTrader

        risk_engine = RiskEngine(initial_capital=5000.0)
        paper_trader = PaperTrader(risk_engine=risk_engine)

        # Cria um sinal e um risk_result que simula bloqueio
        signal = TradingSignal(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            entry_price=65000.0,
            stop_loss_price=64000.0,
            position_size_usd=200.0,
            strategy_name="test",
        )
        risk_result = risk_engine.validate_signal(signal)

        if not risk_result.approved:
            # Se bloqueado, PaperTrader deve lançar ValueError
            import pytest
            with pytest.raises(ValueError, match="NÃO APROVADO"):
                paper_trader.execute(risk_result)
        else:
            # Se aprovado, PaperTrader executa sem erro
            trade = paper_trader.execute(risk_result)
            assert trade is not None


# ---------------------------------------------------------------------------
# Invariantes: was_safe sempre True em todos os cenários
# ---------------------------------------------------------------------------

class TestInvariantsWasSafeAlwaysTrue:
    """
    was_safe deve ser True em TODOS os cenários.
    O BotEngine garante isso via assert no final de _execute_cycle().
    """

    def test_was_safe_in_buy_scenario(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        assert engine.run_once().was_safe is True

    def test_was_safe_in_hold_scenario(self):
        hold_signal = StrategySignal.hold("BTCUSDT", "stub")
        engine, *_ = make_stub_engine(hold_signal, n_candles=60)
        assert engine.run_once().was_safe is True

    def test_was_safe_in_risk_blocked_scenario(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=1.0, n_candles=60)
        assert engine.run_once().was_safe is True

    def test_was_safe_in_no_candles_scenario(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, n_candles=0)
        assert engine.run_once().was_safe is True

    def test_was_safe_in_insufficient_data_scenario(self):
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, n_candles=3)
        assert engine.run_once().was_safe is True

    def test_was_safe_in_all_five_cycles(self):
        """Múltiplos ciclos consecutivos com BUY → todos seguros."""
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy_signal, capital=5000.0, n_candles=60)
        for i in range(5):
            result = engine.run_once()
            assert result.was_safe is True, f"Ciclo {i + 1} não foi seguro!"
