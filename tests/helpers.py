"""
helpers.py — Utilitários de Teste Reutilizáveis
=================================================
Contém StubStrategy, make_stub_engine (BotEngine) e
make_backtest_engine_with_stub (BacktestEngine) para cenários determinísticos.

⚠️  APENAS PARA TESTES — nunca use em src/ ou em produção.

Uso nos testes (BotEngine):
    from tests.helpers import StubStrategy, make_stub_engine

    signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
    engine, _, risk_engine, paper_trader = make_stub_engine(signal, capital=5000.0)
    result = engine.run_once()
    assert result.action == "executed"

Uso nos testes (BacktestEngine — FASE 3D.5):
    from tests.helpers import make_backtest_engine_with_stub, make_default_buy_signal

    signal = make_default_buy_signal()
    engine = make_backtest_engine_with_stub(signal=signal)
    report = engine.run(candles)
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Constantes determinísticas reutilizáveis (FASE 3D.5)
# Compatíveis com generate_candles_with_stop_hit() do backtest_data.
# ---------------------------------------------------------------------------

DEFAULT_SYMBOL: str = "BTCUSDT"
DEFAULT_ENTRY_PRICE: float = 65000.0
DEFAULT_STOP_PRICE: float = 64000.0
DEFAULT_TP_PRICE: float = 67000.0
DEFAULT_POSITION_SIZE: float = 200.0
DEFAULT_CAPITAL: float = 5000.0
DEFAULT_MIN_CANDLES: int = 5


# ---------------------------------------------------------------------------
# StubStrategy — Estratégia de Teste Controlável
# ⚠️  APENAS PARA TESTES — nunca pertence a src/
# ---------------------------------------------------------------------------

class StubStrategy:
    """
    Estratégia de teste com sinal pré-configurado.

    Permite criar cenários 100% determinísticos nos testes de integração:
        - Sempre retorna o sinal injetado (BUY ou HOLD)
        - Após on_signal_approved(), retorna HOLD (evita posição duplicada)
        - Nunca faz cálculos de indicadores
        - Zero chamadas à internet

    ⚠️  APENAS PARA TESTES — nunca pertence a src/.

    Uso:
        signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, risk_engine, paper_trader = make_stub_engine(signal)
        result = engine.run_once()
        assert result.action == "executed"
    """

    def __init__(
        self,
        signal: Any,
        block_after_trade: bool = True,
        one_shot: bool = False,
    ) -> None:
        """
        Args:
            signal: Sinal que será retornado por evaluate().
            block_after_trade: Se True, retorna HOLD enquanto há posição
                               aberta (resetado por on_trade_closed —
                               permite reentrada após fechamento).
            one_shot: Se True, emite o sinal acionável UMA vez por toda a
                      vida da estratégia: após a primeira aprovação, retorna
                      HOLD para sempre (NÃO resetado por on_trade_closed).
                      Usado em testes de backtest que validam mecânica de
                      UM trade controlado (custos/parity/stress), sem
                      depender de quando o engine notifica o fechamento.
        """
        self._stub_signal = signal
        self._block_after_trade = block_after_trade
        self._one_shot = one_shot
        self._position_open: bool = False
        self._trade_executed: bool = False
        self._signal_count: int = 0

        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.WARMING_UP

    @property
    def name(self) -> str:
        return "stub_strategy"

    @property
    def state(self):
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    @property
    def signal_count(self) -> int:
        return self._signal_count

    def set_running(self) -> None:
        """Marca estratégia como pronta para operar."""
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict[str, Any]) -> Any:
        """
        Retorna o sinal pré-configurado.

        - WARMING_UP → HOLD
        - posição aberta + block_after_trade=True → HOLD
        - caso contrário → sinal injetado
        """
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        from crypto_trading_bot.strategies.signal_model import StrategySignal

        if self._state != StrategyState.RUNNING:
            return StrategySignal.hold(
                symbol=self._stub_signal.symbol,
                strategy_name=self.name,
                reason=f"Estratégia inativa: {self._state.value}",
            )

        if self._one_shot and self._trade_executed:
            return StrategySignal.hold(
                symbol=self._stub_signal.symbol,
                strategy_name=self.name,
                reason="one_shot: trade unico ja executado",
            )

        if self._block_after_trade and self._position_open:
            return StrategySignal.hold(
                symbol=self._stub_signal.symbol,
                strategy_name=self.name,
                reason="posição já aberta",
            )

        if self._stub_signal.is_actionable:
            self._signal_count += 1
        return self._stub_signal

    def generate_signal(self, market_data: Dict[str, Any]) -> None:
        """Compatibilidade com BaseStrategy — não usado diretamente."""
        return None

    def reset(self) -> None:
        """Reseta estado interno."""
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._position_open = False
        self._trade_executed = False
        self._state = StrategyState.WARMING_UP

    def on_signal_approved(self, signal) -> None:
        """Marca posição como aberta para bloquear duplicatas."""
        self._trade_executed = True
        if self._block_after_trade:
            self._position_open = True

    def on_signal_rejected(self, signal, reason: str) -> None:
        """Chamado pelo BotEngine quando RiskEngine bloqueia o sinal."""
        pass

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        """Chamado quando posição é fechada."""
        self._position_open = False

    def __repr__(self) -> str:
        return f"StubStrategy(signal={self._stub_signal.action.value})"


# ---------------------------------------------------------------------------
# Factory: make_stub_engine
# Cria BotEngine completo com StubStrategy para cenários determinísticos
# ---------------------------------------------------------------------------

def make_stub_engine(
    signal: Any,
    capital: float = 5000.0,
    n_candles: int = 60,
    block_after_trade: bool = True,
):
    """
    Cria BotEngine completo com StubStrategy — 100% determinístico.

    Args:
        signal: Sinal que a estratégia retornará (BUY ou HOLD).
        capital: Capital inicial do RiskEngine.
                 capital=5000, size=200 → sinal aprovado (BUY executado).
                 capital=1.0, size=200  → sinal bloqueado (risk_blocked).
        n_candles: Preços no MockExchange._price_history.
                   0 → "no_candles"; 3 → "insufficient_data"; 60 → dados ok.
        block_after_trade: Se True, StubStrategy retorna HOLD após execução.

    Returns:
        (engine, stub_strategy, risk_engine, paper_trader)

    Cenários determinísticos:
        BUY executado:  make_stub_engine(buy_signal, capital=5000)
        HOLD:           make_stub_engine(hold_signal)
        risk_blocked:   make_stub_engine(buy_signal, capital=1.0)
        no_candles:     make_stub_engine(buy_signal, n_candles=0)
        insufficient:   make_stub_engine(buy_signal, n_candles=3)
    """
    from crypto_trading_bot.config.settings import Settings
    from crypto_trading_bot.core.bot_engine import BotEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.data.market_data import MarketDataService
    from crypto_trading_bot.exchange.mock_exchange import MockExchange
    from crypto_trading_bot.execution.paper_trader import PaperTrader
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    mock_exchange = MockExchange()
    if n_candles == 0:
        mock_exchange._price_history = []
    else:
        mock_exchange._price_history = [65000.0 + i * 50.0 for i in range(n_candles)]

    market_data = MarketDataService(exchange=mock_exchange, default_symbol="BTCUSDT")
    feature_engine = FeatureEngine()

    stub_strategy = StubStrategy(signal=signal, block_after_trade=block_after_trade)
    stub_strategy.set_running()

    risk_engine = RiskEngine(initial_capital=capital)
    paper_trader = PaperTrader(risk_engine=risk_engine)

    # Settings paper EXPLÍCITAS e isoladas do .env real: garante que o BotEngine
    # não dependa de TRADING_MODE configurado localmente (ex.: testnet na FASE 7).
    # trading_mode explícito tem prioridade sobre env/.env; _env_file=None ignora o .env.
    paper_settings = Settings(
        trading_mode="paper",
        enable_live_trading=False,
        enable_testnet_execution=False,
        _env_file=None,  # type: ignore[call-arg]
    )

    engine = BotEngine(
        market_data_service=market_data,
        feature_engine=feature_engine,
        strategy=stub_strategy,
        risk_engine=risk_engine,
        paper_trader=paper_trader,
        settings=paper_settings,
    )
    return engine, stub_strategy, risk_engine, paper_trader


# ---------------------------------------------------------------------------
# FASE 3D.5 — Helpers determinísticos para BacktestEngine
# ---------------------------------------------------------------------------

def make_default_buy_signal(
    symbol: str = DEFAULT_SYMBOL,
    strategy_name: str = "stub",
    entry_price: float = DEFAULT_ENTRY_PRICE,
    stop_loss_price: float = DEFAULT_STOP_PRICE,
    take_profit_price: Optional[float] = DEFAULT_TP_PRICE,
    position_size_usd: float = DEFAULT_POSITION_SIZE,
):
    """
    Constrói um StrategySignal BUY determinístico para testes de backtesting.

    Compatível com `generate_candles_with_stop_hit(entry_price=65000.0, ...)`.
    """
    from crypto_trading_bot.strategies.signal_model import StrategySignal

    return StrategySignal.buy(
        symbol=symbol,
        strategy_name=strategy_name,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        position_size_usd=position_size_usd,
    )


def make_backtest_engine_with_stub(
    *,
    signal: Any = None,
    capital: float = DEFAULT_CAPITAL,
    min_candles: int = DEFAULT_MIN_CANDLES,
    challenge_target: Optional[float] = None,
    block_after_trade: bool = True,
    one_shot: Optional[bool] = None,
    symbol: str = DEFAULT_SYMBOL,
    execution_cost_config: Any = None,
):
    """
    Cria um BacktestEngine pronto para uso com StubStrategy + RiskEngine + FeatureEngine.

    Substitui o helper local _make_engine_for_backtest que existia em
    test_backtest_engine.py — agora compartilhado entre arquivos de teste.

    Args:
        signal:                 StrategySignal injetado na StubStrategy.
                                Padrão: BUY com valores determinísticos.
        capital:                Capital inicial do RiskEngine e do backtest.
        min_candles:            Quantos candles antes da estratégia começar a operar.
        challenge_target:       Meta de challenge em USD (APENAS KPI — não bloqueia).
        block_after_trade:      Se True, StubStrategy retorna HOLD após cada execução.
        symbol:                 Símbolo passado ao BacktestEngine.
        execution_cost_config:  FASE 3E.1 — ExecutionCostConfig opcional.
                                None → custo zero (compat. FASE 3D.5).

    Returns:
        BacktestEngine pronto para `.run(candles)`.
    """
    from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    if signal is None:
        signal = make_default_buy_signal(symbol=symbol)

    # Os testes de backtest com stub validam mecanica de UM trade
    # controlado. Historicamente isso vinha do engine nao notificar
    # on_trade_closed (=> stub travado apos 1 trade). Agora o engine
    # corretamente notifica o fechamento (lifecycle/reentrada), entao o
    # modo one_shot reproduz a intencao "1 trade" de forma explicita,
    # desacoplada do bug. Default: one_shot == block_after_trade
    # (block_after_trade=False mantem multiplos trades, ex.: contagem de
    # bloqueios do RiskEngine).
    if one_shot is None:
        one_shot = block_after_trade
    strategy = StubStrategy(
        signal=signal, block_after_trade=block_after_trade,
        one_shot=one_shot,
    )
    strategy.set_running()

    risk_engine = RiskEngine(initial_capital=capital)
    feature_engine = FeatureEngine()

    return BacktestEngine(
        strategy=strategy,
        risk_engine=risk_engine,
        feature_engine=feature_engine,
        initial_capital=capital,
        min_candles=min_candles,
        symbol=symbol,
        challenge_profit_target_usd=challenge_target,
        execution_cost_config=execution_cost_config,
    )


# ---------------------------------------------------------------------------
# FASE 3E.1 — Factories de ExecutionCostConfig para testes
# ---------------------------------------------------------------------------

def make_zero_cost_config():
    """
    ExecutionCostConfig com todos os custos zerados.
    Equivalente a passar None ao BacktestEngine.
    Útil para testar regressão da FASE 3D.5.
    """
    from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
    return ExecutionCostConfig()


def make_realistic_cost_config(
    taker_fee_pct: float = 0.0006,
    slippage_pct: float = 0.0005,
    spread_pct: float = 0.0002,
):
    """
    ExecutionCostConfig com custos "realistas" para testes de integração.

    Defaults aproximados (taker fee ~0.06%, slippage ~0.05%, spread ~0.02%).
    NÃO representam tabela real de nenhuma exchange — são valores de teste.

    Args:
        taker_fee_pct: Fee de taker em fração decimal.
        slippage_pct:  Slippage adverso em fração decimal.
        spread_pct:    Spread em fração decimal.

    Returns:
        ExecutionCostConfig com os parâmetros indicados.
    """
    from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
    return ExecutionCostConfig(
        taker_fee_pct=taker_fee_pct,
        slippage_pct=slippage_pct,
        spread_pct=spread_pct,
    )


def assert_exactly_one_trade_closed_by(report, expected_reason) -> None:
    """
    Assert determinístico para cenários SL/TP/ambiguidade.

    Falha com mensagem específica se:
        - `report.total_trades != 1`
        - o único trade não fechou pelo `expected_reason`

    Substitui padrões fracos como:
        if report.total_trades > 0:
            for trade in report.trades:
                if trade.close_reason == X: ...

    Args:
        report:          BacktestReport produzido por engine.run(candles).
        expected_reason: CloseReason esperado para o trade único.
    """
    assert report.total_trades == 1, (
        f"Cenário determinístico deveria produzir exatamente 1 trade, "
        f"obtido {report.total_trades}. Trades={report.trades}"
    )
    trade = report.trades[0]
    assert trade.close_reason == expected_reason, (
        f"Trade fechado com motivo inesperado. "
        f"Esperado: {expected_reason}. Obtido: {trade.close_reason}."
    )
