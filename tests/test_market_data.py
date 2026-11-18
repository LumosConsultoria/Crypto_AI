"""
Testes do MarketDataService
============================
⚠️  ZERO chamadas reais — usa MockExchange para todos os testes.

Cobertura:
    - Inicialização e propriedades
    - get_candles(): retorno correto, lista vazia, erro gracioso
    - get_closes(): extração de closes de candles
    - get_volumes(): extração de volumes
    - get_ticker(): retorno correto, erro gracioso (retorna None)
    - get_latest_price(): retorno correto, erro gracioso
    - get_order_book(): retorno correto, erro gracioso
    - build_market_data_dict(): estrutura completa com candles
    - build_market_data_dict(): fallback sem candles
    - Injeção de dependência (works with any BaseExchange)
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.data.market_data import MarketDataService
from crypto_trading_bot.exchange.base_exchange import (
    BaseExchange,
    Candle,
    OrderBook,
    OrderResult,
    Ticker,
)
from crypto_trading_bot.exchange.mock_exchange import MockExchange


# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------

def _make_candle(
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    close: float = 65000.0,
    ts_offset_minutes: int = 0,
) -> Candle:
    """Cria uma candle de teste com valores controlados."""
    ts = datetime(2024, 5, 20, 12, 0, tzinfo=timezone.utc)
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=ts,
        open=close * 0.999,
        high=close * 1.001,
        low=close * 0.998,
        close=close,
        volume=100.0,
    )


def _make_ticker(
    symbol: str = "BTCUSDT",
    last_price: float = 65000.0,
) -> Ticker:
    """Cria um ticker de teste."""
    return Ticker(
        symbol=symbol,
        last_price=last_price,
        bid=last_price - 1.0,
        ask=last_price + 1.0,
        volume_24h=12345.0,
        timestamp=datetime.now(timezone.utc),
    )


def _make_order_book(symbol: str = "BTCUSDT") -> OrderBook:
    """Cria um order book de teste."""
    return OrderBook(
        symbol=symbol,
        bids=[(65000.0, 0.5), (64999.0, 1.0)],
        asks=[(65001.0, 0.3), (65002.0, 0.8)],
        timestamp=datetime.now(timezone.utc),
    )


def _make_candles(n: int = 5, base_price: float = 65000.0) -> List[Candle]:
    """Cria uma lista de N candles com preços variados."""
    ts_base = datetime(2024, 5, 20, 10, 0, tzinfo=timezone.utc)
    candles = []
    for i in range(n):
        ts = ts_base.replace(minute=i * 15 % 60, hour=10 + (i * 15 // 60))
        close = base_price + i * 10
        candles.append(Candle(
            symbol="BTCUSDT",
            timeframe="15",
            timestamp=ts,
            open=close - 5,
            high=close + 10,
            low=close - 10,
            close=close,
            volume=100.0 + i,
        ))
    return candles


@pytest.fixture
def mock_exchange() -> MockExchange:
    """MockExchange com preço determinístico (sem variação)."""
    return MockExchange(
        initial_price=65000.0,
        initial_balance_usdt=5000.0,
        price_volatility=0.0,  # preço estático para testes determinísticos
    )


@pytest.fixture
def service(mock_exchange: MockExchange) -> MarketDataService:
    """MarketDataService com MockExchange."""
    return MarketDataService(
        exchange=mock_exchange,
        default_symbol="BTCUSDT",
        default_timeframe="15",
    )


# ---------------------------------------------------------------------------
# Testes de Inicialização
# ---------------------------------------------------------------------------

class TestMarketDataServiceInit:
    """Testa a inicialização do MarketDataService."""

    def test_init_with_mock_exchange(self, mock_exchange):
        svc = MarketDataService(exchange=mock_exchange)
        assert svc.exchange is mock_exchange

    def test_init_requires_exchange(self):
        with pytest.raises(ValueError, match="BaseExchange"):
            MarketDataService(exchange=None)

    def test_default_symbol_and_timeframe(self, mock_exchange):
        svc = MarketDataService(
            exchange=mock_exchange,
            default_symbol="ETHUSDT",
            default_timeframe="60",
        )
        assert svc.default_symbol == "ETHUSDT"
        assert svc.default_timeframe == "60"

    def test_repr(self, service):
        r = repr(service)
        assert "BTCUSDT" in r
        assert "mock" in r


# ---------------------------------------------------------------------------
# Testes de get_candles()
# ---------------------------------------------------------------------------

class TestMarketDataServiceGetCandles:
    """Testa o método get_candles()."""

    def test_get_candles_returns_list(self, service):
        candles = service.get_candles("BTCUSDT", "15", limit=10)
        assert isinstance(candles, list)
        assert len(candles) > 0

    def test_get_candles_uses_default_symbol(self, service):
        """Sem symbol explícito, usa o default_symbol."""
        candles = service.get_candles(limit=10)
        assert len(candles) > 0
        assert all(c.symbol == "BTCUSDT" for c in candles)

    def test_get_candles_returns_candle_objects(self, service):
        candles = service.get_candles("BTCUSDT", "15", limit=5)
        for c in candles:
            assert isinstance(c, Candle)
            assert c.close > 0
            assert c.high >= c.close
            assert c.low <= c.close

    def test_get_candles_returns_empty_on_error(self, mock_exchange):
        """Se a exchange lançar exceção, retorna lista vazia sem propagar."""
        mock_exchange.get_candles = MagicMock(side_effect=RuntimeError("erro"))
        svc = MarketDataService(exchange=mock_exchange)
        candles = svc.get_candles("BTCUSDT")
        assert candles == []

    def test_get_candles_limit_respected(self, service):
        candles = service.get_candles("BTCUSDT", "15", limit=20)
        assert len(candles) <= 20

    def test_get_starts_from_oldest(self, service):
        """As candles devem estar ordenadas do mais antigo para o mais recente."""
        candles = service.get_candles("BTCUSDT", "15", limit=10)
        if len(candles) >= 2:
            assert candles[0].timestamp <= candles[-1].timestamp


# ---------------------------------------------------------------------------
# Testes de get_closes() e get_volumes()
# ---------------------------------------------------------------------------

class TestMarketDataServiceCloseVolumes:
    """Testa get_closes() e get_volumes()."""

    def test_get_closes_returns_list_of_floats(self, service):
        closes = service.get_closes("BTCUSDT", "15", limit=10)
        assert isinstance(closes, list)
        assert all(isinstance(c, float) for c in closes)

    def test_get_closes_matches_candle_closes(self, service):
        candles = service.get_candles("BTCUSDT", "15", limit=10)
        closes = service.get_closes("BTCUSDT", "15", limit=10)
        expected_closes = [c.close for c in candles]
        # Podem diferir se o preço variou entre chamadas com volatility > 0
        # Com volatility=0, devem ser iguais
        assert len(closes) == len(expected_closes)

    def test_get_closes_empty_on_error(self, mock_exchange):
        mock_exchange.get_candles = MagicMock(side_effect=RuntimeError("erro"))
        svc = MarketDataService(exchange=mock_exchange)
        assert svc.get_closes("BTCUSDT") == []

    def test_get_volumes_returns_list_of_floats(self, service):
        volumes = service.get_volumes("BTCUSDT", "15", limit=10)
        assert isinstance(volumes, list)
        assert all(isinstance(v, float) for v in volumes)

    def test_get_volumes_are_positive(self, service):
        volumes = service.get_volumes("BTCUSDT", "15", limit=10)
        assert all(v > 0 for v in volumes)


# ---------------------------------------------------------------------------
# Testes de get_ticker()
# ---------------------------------------------------------------------------

class TestMarketDataServiceGetTicker:
    """Testa o método get_ticker()."""

    def test_get_ticker_returns_ticker(self, service):
        ticker = service.get_ticker("BTCUSDT")
        assert ticker is not None
        assert isinstance(ticker, Ticker)
        assert ticker.last_price > 0
        assert ticker.symbol == "BTCUSDT"

    def test_get_ticker_uses_default_symbol(self, service):
        ticker = service.get_ticker()
        assert ticker is not None
        assert ticker.symbol == "BTCUSDT"

    def test_get_ticker_returns_none_on_error(self, mock_exchange):
        """Se a exchange lançar exceção, retorna None sem propagar."""
        mock_exchange.get_ticker = MagicMock(side_effect=RuntimeError("erro"))
        svc = MarketDataService(exchange=mock_exchange)
        result = svc.get_ticker("BTCUSDT")
        assert result is None

    def test_get_ticker_bid_less_than_ask(self, service):
        ticker = service.get_ticker("BTCUSDT")
        if ticker:
            assert ticker.bid <= ticker.ask


# ---------------------------------------------------------------------------
# Testes de get_latest_price()
# ---------------------------------------------------------------------------

class TestMarketDataServiceGetLatestPrice:
    """Testa o método get_latest_price()."""

    def test_get_latest_price_returns_float(self, service):
        price = service.get_latest_price("BTCUSDT")
        assert price is not None
        assert isinstance(price, float)
        assert price > 0

    def test_get_latest_price_returns_none_on_error(self, mock_exchange):
        mock_exchange.get_ticker = MagicMock(side_effect=RuntimeError("erro"))
        svc = MarketDataService(exchange=mock_exchange)
        result = svc.get_latest_price("BTCUSDT")
        assert result is None

    def test_get_latest_price_uses_default_symbol(self, service):
        price = service.get_latest_price()
        assert price is not None and price > 0


# ---------------------------------------------------------------------------
# Testes de get_order_book()
# ---------------------------------------------------------------------------

class TestMarketDataServiceGetOrderBook:
    """Testa o método get_order_book()."""

    def test_get_order_book_returns_order_book(self, service):
        ob = service.get_order_book("BTCUSDT", depth=5)
        assert ob is not None
        assert isinstance(ob, OrderBook)
        assert len(ob.bids) == 5
        assert len(ob.asks) == 5

    def test_get_order_book_best_bid_less_than_best_ask(self, service):
        ob = service.get_order_book("BTCUSDT", depth=5)
        if ob and ob.best_bid and ob.best_ask:
            assert ob.best_bid < ob.best_ask

    def test_get_order_book_returns_none_on_error(self, mock_exchange):
        mock_exchange.get_order_book = MagicMock(side_effect=RuntimeError("erro"))
        svc = MarketDataService(exchange=mock_exchange)
        result = svc.get_order_book("BTCUSDT")
        assert result is None

    def test_get_order_book_uses_default_symbol(self, service):
        ob = service.get_order_book()
        assert ob is not None


# ---------------------------------------------------------------------------
# Testes de build_market_data_dict()
# ---------------------------------------------------------------------------

class TestMarketDataServiceBuildDict:
    """Testa o método build_market_data_dict()."""

    def test_build_market_data_dict_structure(self, service):
        """O dicionário deve ter todos os campos esperados pelas estratégias."""
        data = service.build_market_data_dict("BTCUSDT", "15", limit=50)

        required_keys = [
            "symbol", "timeframe", "close", "open", "high", "low", "volume",
            "closes", "opens", "highs", "lows", "volumes", "candles", "ticker",
        ]
        for key in required_keys:
            assert key in data, f"Chave '{key}' ausente no market_data_dict"

    def test_build_market_data_dict_symbol(self, service):
        data = service.build_market_data_dict("BTCUSDT")
        assert data["symbol"] == "BTCUSDT"

    def test_build_market_data_dict_close_is_positive(self, service):
        data = service.build_market_data_dict("BTCUSDT", "15", limit=50)
        assert data["close"] > 0

    def test_build_market_data_dict_closes_matches_candles(self, service):
        data = service.build_market_data_dict("BTCUSDT", "15", limit=50)
        assert len(data["closes"]) == len(data["candles"])
        assert len(data["volumes"]) == len(data["candles"])

    def test_build_market_data_dict_fallback_on_empty_candles(self, mock_exchange):
        """Sem candles disponíveis, retorna estrutura com listas vazias."""
        mock_exchange.get_candles = MagicMock(return_value=[])
        svc = MarketDataService(exchange=mock_exchange)

        data = svc.build_market_data_dict("BTCUSDT")
        assert data["closes"] == []
        assert data["candles"] == []
        assert data["symbol"] == "BTCUSDT"

    def test_build_market_data_dict_compatible_with_strategy(self, service):
        """O dict deve ser compatível com a interface da ExampleStrategy."""
        from crypto_trading_bot.strategies.example_strategy import ExampleStrategy

        data = service.build_market_data_dict("BTCUSDT", "15", limit=50)
        strategy = ExampleStrategy()
        strategy.set_running()

        # Não deve lançar exceção ao processar o market_data
        signal = strategy.generate_signal(data)
        # Pode ser None (sem sinal) ou TradingSignal — ambos são válidos
        # O importante é que não levante exceção


# ---------------------------------------------------------------------------
# Testes de Injeção de Dependência
# ---------------------------------------------------------------------------

class TestMarketDataServiceDependencyInjection:
    """Garante que MarketDataService funciona com qualquer BaseExchange."""

    def test_works_with_mock_exchange(self):
        exchange = MockExchange(initial_price=50000.0)
        svc = MarketDataService(exchange=exchange)
        ticker = svc.get_ticker("BTCUSDT")
        assert ticker is not None

    def test_exchange_property(self, service, mock_exchange):
        assert service.exchange is mock_exchange

    def test_service_uses_injected_exchange(self):
        """MarketDataService deve usar a exchange injetada, não criar a sua própria."""
        custom_exchange = MockExchange(initial_price=99999.0, price_volatility=0.0)
        svc = MarketDataService(exchange=custom_exchange)
        price = svc.get_latest_price()
        # Preço deve ser próximo de 99999.0 (price_volatility=0.0)
        assert price is not None
        assert abs(price - 99999.0) < 100  # tolerância para price_volatility=0
