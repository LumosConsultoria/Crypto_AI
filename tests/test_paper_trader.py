"""
Testes do PaperTrader — Executor Simulado
===========================================
Testa o executor de paper trading de ponta a ponta.

Cobertura:
    - Inicialização segura (somente em modo paper/testnet)
    - Rejeição de sinal não aprovado
    - Execução bem-sucedida de trade
    - Fechamento de trade com PnL positivo/negativo
    - Fechamento por stop loss / take profit
    - Histórico de trades
    - Cálculo de win rate e PnL total
    - Resumo de performance
"""

from typing import Optional

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.config.settings import Settings
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import (
    PaperTrade,
    PaperTradeStatus,
    PaperTrader,
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

def _make_settings(mode: str = "paper") -> Settings:
    return Settings(trading_mode=mode, enable_live_trading=False)


def _make_risk_config() -> RiskConfig:
    return RiskConfig(
        max_daily_loss_pct=0.05,
        max_total_loss_pct=0.10,
        max_trades_per_day=10,
        max_exposure_per_asset_pct=0.50,
        max_leverage=3.0,
        min_stop_loss_pct=0.001,  # 0.1% mínimo para facilitar testes
        max_stop_loss_pct=0.10,
        max_position_size_pct=0.50,
    )


def _make_valid_signal(
    entry_price: float = 65000.0,
    side: OrderSide = OrderSide.BUY,
    position_size_usd: float = 200.0,
) -> TradingSignal:
    stop_pct = 0.02  # 2% stop loss
    if side == OrderSide.BUY:
        stop_price = round(entry_price * (1 - stop_pct), 2)
        tp_price = round(entry_price * 1.04, 2)
    else:
        stop_price = round(entry_price * (1 + stop_pct), 2)
        tp_price = round(entry_price * 0.96, 2)

    return TradingSignal(
        symbol="BTCUSDT",
        side=side,
        entry_price=entry_price,
        stop_loss_price=stop_price,
        take_profit_price=tp_price,
        position_size_usd=position_size_usd,
        leverage=1.0,
        strategy_name="test_strategy",
    )


def _make_approved_risk_result(signal: TradingSignal) -> RiskResult:
    """Cria um RiskResult aprovado para testes (sem passar pelo RiskEngine real)."""
    return RiskResult(
        approved=True,
        reason="",
        signal=signal,
        block_reason=None,
        checks_passed=["all_checks"],
        checks_failed=[],
    )


def _make_rejected_risk_result(signal: TradingSignal) -> RiskResult:
    """Cria um RiskResult rejeitado para testes."""
    from crypto_trading_bot.risk.risk_engine import RiskBlockReason
    return RiskResult(
        approved=False,
        reason="Sinal bloqueado para teste",
        signal=signal,
        block_reason=RiskBlockReason.NO_STOP_LOSS,
        checks_passed=[],
        checks_failed=["stop_loss_obrigatorio"],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def paper_settings():
    return _make_settings("paper")


@pytest.fixture
def risk_config():
    return _make_risk_config()


@pytest.fixture
def mock_exchange():
    exchange = MockExchange(
        initial_price=65000.0,
        initial_balance_usdt=5000.0,
        price_volatility=0.0,  # sem variação para testes determinísticos
    )
    return exchange


@pytest.fixture
def risk_engine(risk_config, paper_settings):
    return RiskEngine(
        initial_capital=5000.0,
        config=risk_config,
        settings=paper_settings,
    )


@pytest.fixture
def paper_trader(risk_engine, mock_exchange, paper_settings):
    guard = ModeGuard(paper_settings)
    return PaperTrader(
        risk_engine=risk_engine,
        exchange=mock_exchange,
        mode_guard=guard,
    )


@pytest.fixture
def valid_signal():
    return _make_valid_signal()


# ---------------------------------------------------------------------------
# Testes de Inicialização
# ---------------------------------------------------------------------------

class TestPaperTraderInit:
    """Testa a inicialização do PaperTrader."""

    def test_paper_trader_initializes_in_paper_mode(self, risk_engine, mock_exchange, paper_settings):
        guard = ModeGuard(paper_settings)
        trader = PaperTrader(risk_engine=risk_engine, exchange=mock_exchange, mode_guard=guard)
        assert trader is not None

    def test_paper_trader_requires_risk_engine(self, mock_exchange):
        with pytest.raises(ValueError) as exc_info:
            PaperTrader(risk_engine=None, exchange=mock_exchange)
        assert "RiskEngine" in str(exc_info.value)

    def test_initial_state_is_empty(self, paper_trader):
        assert len(paper_trader.open_trades) == 0
        assert len(paper_trader.closed_trades) == 0
        assert paper_trader.execution_count == 0
        assert paper_trader.total_pnl == 0.0
        assert paper_trader.win_rate is None


# ---------------------------------------------------------------------------
# Testes de Execução
# ---------------------------------------------------------------------------

class TestPaperTraderExecution:
    """Testa a execução de trades."""

    def test_execute_approved_signal_succeeds(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        assert result.success is True
        assert result.trade is not None

    def test_execute_creates_open_trade(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        assert len(paper_trader.open_trades) == 1
        trade = result.trade
        assert trade is not None
        assert trade.is_open is True
        assert trade.status == PaperTradeStatus.OPEN

    def test_execute_rejected_signal_raises_value_error(self, paper_trader, valid_signal):
        """PaperTrader não deve aceitar sinal não aprovado — deve lançar ValueError."""
        rejected = _make_rejected_risk_result(valid_signal)
        with pytest.raises(ValueError) as exc_info:
            paper_trader.execute(rejected)
        assert "NÃO APROVADO" in str(exc_info.value) or "aprovado" in str(exc_info.value).lower()

    def test_execution_count_increments(self, paper_trader, valid_signal):
        paper_trader.execute(_make_approved_risk_result(valid_signal))
        paper_trader.execute(_make_approved_risk_result(_make_valid_signal(entry_price=66000.0)))
        assert paper_trader.execution_count == 2

    def test_trade_contains_correct_signal(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        assert result.trade.signal is valid_signal

    def test_trade_has_unique_id(self, paper_trader, valid_signal):
        result1 = paper_trader.execute(_make_approved_risk_result(valid_signal))
        result2 = paper_trader.execute(_make_approved_risk_result(_make_valid_signal(entry_price=66000.0)))
        assert result1.trade.trade_id != result2.trade.trade_id


# ---------------------------------------------------------------------------
# Testes de Fechamento de Trade
# ---------------------------------------------------------------------------

class TestPaperTraderClose:
    """Testa o fechamento de trades."""

    def test_close_trade_moves_to_closed_list(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        trade_id = result.trade.trade_id

        close_result = paper_trader.close_trade(trade_id, close_price=66300.0)

        assert close_result.success is True
        assert len(paper_trader.open_trades) == 0
        assert len(paper_trader.closed_trades) == 1

    def test_close_trade_with_profit_has_positive_pnl(self, paper_trader):
        """Fechar acima da entrada (BUY) deve gerar PnL positivo."""
        signal = _make_valid_signal(entry_price=65000.0, position_size_usd=650.0)
        result = paper_trader.execute(_make_approved_risk_result(signal))
        trade_id = result.trade.trade_id

        # Fecha a 66300 (ACIMA de 65000 para BUY → lucro)
        close_result = paper_trader.close_trade(trade_id, close_price=66300.0)

        trade = close_result.trade
        assert trade.pnl > 0  # lucro
        assert trade.status == PaperTradeStatus.CLOSED_MANUAL

    def test_close_trade_with_stop_loss_reason(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        trade_id = result.trade.trade_id

        close_result = paper_trader.close_trade(
            trade_id,
            close_price=63700.0,
            reason="stop_loss",
        )

        assert close_result.trade.status == PaperTradeStatus.CLOSED_STOP_LOSS

    def test_close_trade_with_take_profit_reason(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        trade_id = result.trade.trade_id

        close_result = paper_trader.close_trade(
            trade_id,
            close_price=67600.0,
            reason="take_profit",
        )

        assert close_result.trade.status == PaperTradeStatus.CLOSED_TAKE_PROFIT

    def test_close_nonexistent_trade_fails(self, paper_trader):
        result = paper_trader.close_trade("NONEXISTENT_ID", close_price=65000.0)
        assert result.success is False
        assert "não encontrado" in result.reason.lower()

    def test_closed_trade_has_timestamps(self, paper_trader, valid_signal):
        result = paper_trader.execute(_make_approved_risk_result(valid_signal))
        trade_id = result.trade.trade_id

        close_result = paper_trader.close_trade(trade_id, close_price=65000.0)
        trade = close_result.trade

        assert trade.opened_at is not None
        assert trade.closed_at is not None
        assert trade.close_price == 65000.0


# ---------------------------------------------------------------------------
# Testes de Métricas
# ---------------------------------------------------------------------------

class TestPaperTraderMetrics:
    """Testa as métricas de performance do PaperTrader."""

    def test_total_pnl_accumulates(self, paper_trader):
        """PnL total deve ser a soma de todos os trades fechados."""
        # Trade 1 (lucro)
        s1 = _make_valid_signal(entry_price=65000.0, position_size_usd=650.0)
        r1 = paper_trader.execute(_make_approved_risk_result(s1))
        paper_trader.close_trade(r1.trade.trade_id, close_price=66300.0)  # lucro

        # Trade 2 (perda)
        s2 = _make_valid_signal(entry_price=65000.0, position_size_usd=650.0)
        r2 = paper_trader.execute(_make_approved_risk_result(s2))
        paper_trader.close_trade(r2.trade.trade_id, close_price=63700.0)  # perda

        # Total deve ser a soma dos dois
        expected_total = sum(t.pnl for t in paper_trader.closed_trades)
        assert abs(paper_trader.total_pnl - expected_total) < 0.01

    def test_win_rate_calculation(self, paper_trader):
        """Taxa de acerto deve ser calculada corretamente."""
        # 2 trades lucrativos + 1 perdedor = 66.7% win rate
        for entry, close in [(65000.0, 66300.0), (65000.0, 66300.0), (65000.0, 63700.0)]:
            signal = _make_valid_signal(entry_price=entry, position_size_usd=650.0)
            result = paper_trader.execute(_make_approved_risk_result(signal))
            paper_trader.close_trade(result.trade.trade_id, close_price=close)

        assert paper_trader.win_rate is not None
        assert abs(paper_trader.win_rate - 2 / 3) < 0.01

    def test_win_rate_none_before_any_trade(self, paper_trader):
        assert paper_trader.win_rate is None

    def test_get_summary_structure(self, paper_trader, valid_signal):
        paper_trader.execute(_make_approved_risk_result(valid_signal))
        summary = paper_trader.get_summary()

        assert "total_executions" in summary
        assert "open_trades" in summary
        assert "closed_trades" in summary
        assert "total_pnl" in summary
        assert "win_rate" in summary
        assert "balance" in summary
        assert summary["mode"] == "paper_simulation"
