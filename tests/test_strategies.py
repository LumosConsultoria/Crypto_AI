"""
Testes de Estratégias
======================
Testa a interface base e a estratégia exemplo.

Cobertura:
    - BaseStrategy: interface e estado
    - ExampleStrategy: geração de sinais
    - Estratégia sem sinal (dados insuficientes)
    - Estratégia com sinal válido (SMA + volume)
    - Respeito ao estado (WARMING_UP → RUNNING)
    - Pausar/retomar estratégia
    - Não gerar sinal quando já há posição aberta
    - Cálculos de SMA e volume médio
"""

from typing import List, Optional

import pytest

from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.example_strategy import ExampleStrategy


# ---------------------------------------------------------------------------
# Implementação concreta de teste para BaseStrategy
# ---------------------------------------------------------------------------

class ConcreteTestStrategy(BaseStrategy):
    """Implementação mínima de BaseStrategy para testar a interface."""

    def __init__(self, signal_to_return: Optional[TradingSignal] = None) -> None:
        self._signal_to_return = signal_to_return
        super().__init__()

    @property
    def name(self) -> str:
        return "concrete_test_strategy"

    def generate_signal(self, market_data: dict) -> Optional[TradingSignal]:
        return self._signal_to_return

    def reset(self) -> None:
        self._signal_to_return = None
        self._state = StrategyState.WARMING_UP


def _make_valid_signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        entry_price=65000.0,
        stop_loss_price=63700.0,
        take_profit_price=67600.0,
        position_size_usd=200.0,
        leverage=1.0,
        strategy_name="test_strategy",
    )


def _make_market_data(
    closes: List[float],
    volumes: Optional[List[float]] = None,
    symbol: str = "BTCUSDT",
) -> dict:
    """Cria market_data no formato esperado pela ExampleStrategy."""
    if volumes is None:
        volumes = [100.0] * len(closes)

    return {
        "symbol": symbol,
        "close": closes[-1] if closes else 0.0,
        "open": closes[-2] if len(closes) >= 2 else closes[-1],
        "high": closes[-1] * 1.01,
        "low": closes[-1] * 0.99,
        "volume": volumes[-1] if volumes else 0.0,
        "closes": closes,
        "volumes": volumes,
    }


def _generate_bullish_closes(base_price: float = 65000.0, n: int = 25) -> List[float]:
    """Gera lista de preços em tendência de alta para acionar a ExampleStrategy."""
    prices = []
    price = base_price * 0.95  # começa 5% abaixo
    for i in range(n):
        price = price * 1.002  # crescimento de 0.2% por período
        prices.append(round(price, 2))
    return prices


def _generate_sideways_closes(base_price: float = 65000.0, n: int = 25) -> List[float]:
    """Gera lista de preços laterais para NÃO acionar a estratégia."""
    # Todos os preços iguais
    return [base_price] * n


# ---------------------------------------------------------------------------
# Testes da BaseStrategy
# ---------------------------------------------------------------------------

class TestBaseStrategy:
    """Testa a interface e comportamentos da BaseStrategy."""

    def test_strategy_initializes_in_warming_up_state(self):
        strategy = ConcreteTestStrategy()
        assert strategy.state == StrategyState.WARMING_UP
        assert strategy.is_running is False

    def test_strategy_name_is_accessible(self):
        strategy = ConcreteTestStrategy()
        assert strategy.name == "concrete_test_strategy"

    def test_signal_count_starts_at_zero(self):
        strategy = ConcreteTestStrategy()
        assert strategy.signal_count == 0

    def test_last_signal_is_none_initially(self):
        strategy = ConcreteTestStrategy()
        assert strategy.last_signal is None

    def test_strategy_set_running(self):
        strategy = ConcreteTestStrategy()
        strategy.set_running()
        assert strategy.state == StrategyState.RUNNING
        assert strategy.is_running is True

    def test_strategy_pause_and_resume(self):
        strategy = ConcreteTestStrategy()
        strategy.set_running()
        assert strategy.is_running is True

        strategy.pause()
        assert strategy.state == StrategyState.PAUSED
        assert strategy.is_running is False

        strategy.resume()
        assert strategy.state == StrategyState.RUNNING
        assert strategy.is_running is True

    def test_safe_generate_signal_returns_none_when_warming_up(self):
        """Estratégia em WARMING_UP não deve gerar sinais."""
        signal = _make_valid_signal()
        strategy = ConcreteTestStrategy(signal_to_return=signal)
        # Estado WARMING_UP → _safe_generate_signal deve retornar None
        result = strategy._safe_generate_signal({})
        assert result is None

    def test_safe_generate_signal_returns_signal_when_running(self):
        """Estratégia em RUNNING deve gerar sinais."""
        signal = _make_valid_signal()
        strategy = ConcreteTestStrategy(signal_to_return=signal)
        strategy.set_running()

        result = strategy._safe_generate_signal({"any": "data"})
        assert result is signal
        assert strategy.signal_count == 1
        assert strategy.last_signal is signal

    def test_safe_generate_signal_returns_none_when_paused(self):
        """Estratégia pausada não deve gerar sinais."""
        signal = _make_valid_signal()
        strategy = ConcreteTestStrategy(signal_to_return=signal)
        strategy.set_running()
        strategy.pause()

        result = strategy._safe_generate_signal({})
        assert result is None
        assert strategy.signal_count == 0

    def test_safe_generate_catches_exception(self):
        """_safe_generate_signal não deve propagar exceções."""
        class BrokenStrategy(BaseStrategy):
            @property
            def name(self) -> str:
                return "broken"

            def generate_signal(self, market_data):
                raise RuntimeError("Erro proposital para teste")

            def reset(self) -> None:
                pass

        strategy = BrokenStrategy()
        strategy.set_running()
        result = strategy._safe_generate_signal({})

        assert result is None
        assert strategy.state == StrategyState.ERROR

    def test_reset_clears_state(self):
        strategy = ConcreteTestStrategy()
        strategy.set_running()
        strategy.reset()
        assert strategy._signal_to_return is None

    def test_repr_contains_name_and_state(self):
        strategy = ConcreteTestStrategy()
        repr_str = repr(strategy)
        assert "concrete_test_strategy" in repr_str
        assert "warming_up" in repr_str


# ---------------------------------------------------------------------------
# Testes da ExampleStrategy
# ---------------------------------------------------------------------------

class TestExampleStrategy:
    """Testa a ExampleStrategy (SMA20 + volume)."""

    def test_strategy_initializes_correctly(self):
        strategy = ExampleStrategy()
        assert strategy.name == "example_sma20_strategy"
        assert strategy.state == StrategyState.WARMING_UP

    def test_no_signal_with_insufficient_data(self):
        """Menos de 21 candles → sem sinal."""
        strategy = ExampleStrategy()
        strategy.set_running()

        # Apenas 5 candles — insuficiente para SMA20
        market_data = _make_market_data(closes=[65000.0] * 5)
        result = strategy.generate_signal(market_data)
        assert result is None

    def test_no_signal_with_empty_data(self):
        """Dados vazios → sem sinal."""
        strategy = ExampleStrategy()
        strategy.set_running()

        result = strategy.generate_signal({})
        assert result is None

    def test_no_signal_with_zero_price(self):
        """Preço zero → sem sinal."""
        strategy = ExampleStrategy()
        strategy.set_running()

        market_data = _make_market_data(closes=[0.0] * 25)
        result = strategy.generate_signal(market_data)
        assert result is None

    def test_signal_generated_when_price_above_sma(self):
        """Preço acima da SMA20 com volume acima da média → sinal de compra."""
        strategy = ExampleStrategy()
        strategy.set_running()

        # Gera preços em alta para que o preço atual esteja ACIMA da SMA20
        closes = _generate_bullish_closes(base_price=65000.0, n=25)
        volumes = [200.0] * 25  # todas as candles com mesmo volume

        # Aumenta o volume da última candle para acionar a condição de volume
        volumes[-1] = 300.0  # acima da média de 200

        market_data = _make_market_data(closes=closes, volumes=volumes)
        result = strategy.generate_signal(market_data)

        # Com preço crescendo, o close atual deve estar acima da SMA20
        assert result is not None
        assert result.side == OrderSide.BUY
        assert result.stop_loss_price > 0
        assert result.stop_loss_price < result.entry_price  # stop abaixo da entrada
        assert result.strategy_name == "example_sma20_strategy"

    def test_signal_has_stop_loss_below_entry_for_buy(self):
        """Stop loss de compra deve estar abaixo do preço de entrada."""
        strategy = ExampleStrategy()
        strategy.set_running()

        closes = _generate_bullish_closes(base_price=65000.0, n=25)
        volumes = [200.0] * 24 + [300.0]
        market_data = _make_market_data(closes=closes, volumes=volumes)

        result = strategy.generate_signal(market_data)
        if result is not None:
            assert result.stop_loss_price < result.entry_price

    def test_no_signal_when_position_already_open(self):
        """Quando já há posição aberta, não deve gerar novo sinal."""
        strategy = ExampleStrategy()
        strategy.set_running()
        strategy._has_open_position = True  # simula posição aberta

        closes = _generate_bullish_closes(base_price=65000.0, n=25)
        volumes = [200.0] * 24 + [300.0]
        market_data = _make_market_data(closes=closes, volumes=volumes)

        result = strategy.generate_signal(market_data)
        assert result is None

    def test_position_state_updated_on_signal_approved(self):
        """on_signal_approved deve marcar posição como aberta."""
        strategy = ExampleStrategy()
        assert strategy._has_open_position is False

        signal = _make_valid_signal()
        strategy.on_signal_approved(signal)

        assert strategy._has_open_position is True

    def test_position_state_updated_on_trade_closed(self):
        """on_trade_closed deve marcar posição como fechada."""
        strategy = ExampleStrategy()
        strategy._has_open_position = True

        strategy.on_trade_closed("BTCUSDT", pnl=50.0)

        assert strategy._has_open_position is False

    def test_reset_clears_position_state(self):
        """reset() deve limpar o estado de posição."""
        strategy = ExampleStrategy()
        strategy.set_running()
        strategy._has_open_position = True

        strategy.reset()

        assert strategy._has_open_position is False
        assert strategy.state == StrategyState.WARMING_UP

    def test_custom_parameters(self):
        """Estratégia deve respeitar parâmetros customizados."""
        strategy = ExampleStrategy(
            sma_period=10,
            stop_loss_pct=0.01,
            take_profit_pct=0.03,
            position_size_usd=100.0,
        )
        assert strategy._sma_period == 10
        assert strategy._stop_loss_pct == 0.01
        assert strategy._take_profit_pct == 0.03
        assert strategy._position_size_usd == 100.0


# ---------------------------------------------------------------------------
# Testes dos Métodos Auxiliares da ExampleStrategy
# ---------------------------------------------------------------------------

class TestExampleStrategyHelpers:
    """Testa os métodos auxiliares estáticos da ExampleStrategy."""

    def test_sma_calculation(self):
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        sma = ExampleStrategy._calculate_sma(closes, period=3)
        # Média dos últimos 3: (3+4+5)/3 = 4.0
        assert sma is not None
        assert abs(sma - 4.0) < 1e-9

    def test_sma_returns_none_with_insufficient_data(self):
        closes = [1.0, 2.0]
        sma = ExampleStrategy._calculate_sma(closes, period=5)
        assert sma is None

    def test_sma_full_period(self):
        closes = [10.0, 20.0, 30.0, 40.0, 50.0]
        sma = ExampleStrategy._calculate_sma(closes, period=5)
        assert sma is not None
        assert abs(sma - 30.0) < 1e-9  # (10+20+30+40+50)/5 = 30

    def test_avg_volume_calculation(self):
        volumes = [100.0, 200.0, 300.0, 400.0, 500.0]
        avg = ExampleStrategy._calculate_avg_volume(volumes, period=3)
        # Média dos últimos 3: (300+400+500)/3 = 400.0
        assert avg is not None
        assert abs(avg - 400.0) < 1e-9

    def test_avg_volume_returns_none_with_empty_list(self):
        avg = ExampleStrategy._calculate_avg_volume([], period=5)
        assert avg is None

    def test_avg_volume_returns_none_with_insufficient_data(self):
        avg = ExampleStrategy._calculate_avg_volume([100.0, 200.0], period=5)
        assert avg is None
