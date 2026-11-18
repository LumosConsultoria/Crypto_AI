"""
MarketDataService — Serviço de Dados de Mercado
==================================================
Camada de alto nível para coleta e acesso a dados de mercado.

Responsabilidades:
    - Fornecer interface unificada para dados de mercado
    - Abstrair a exchange subjacente (Mock ou Bybit)
    - Validar dados recebidos antes de retornar
    - Logar todas as operações de dados
    - Preparado para cache futuro (TODO FASE 4)

⚠️  Separação de responsabilidades:
    BybitClient (HTTP) → MarketDataService (serviço) → Strategy/BotEngine

    A Strategy e o BotEngine NÃO devem usar BybitClient diretamente.
    Sempre use MarketDataService como intermediário.

⚠️  Sobre IA:
    MarketDataService fornece dados para estratégias DETERMINÍSTICAS.
    A IA pode receber esses dados para análise de contexto, mas NUNCA
    para gerar sinais de trading diretamente.

Uso:
    # Com MockExchange (paper trading / testes):
    from crypto_trading_bot.exchange.mock_exchange import MockExchange
    service = MarketDataService(exchange=MockExchange())
    candles = service.get_candles("BTCUSDT", "15")
    ticker = service.get_ticker("BTCUSDT")
    price = service.get_latest_price("BTCUSDT")

    # Com BybitClient (dados reais, read-only):
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    service = MarketDataService(exchange=BybitClient(use_testnet=True))
    candles = service.get_candles("BTCUSDT", "15", limit=200)
"""

from __future__ import annotations

from typing import List, Optional

from crypto_trading_bot.exchange.base_exchange import BaseExchange, Candle, OrderBook, Ticker
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


class MarketDataService:
    """
    Serviço de alto nível para acesso a dados de mercado.

    Recebe qualquer implementação de BaseExchange via injeção de dependência,
    garantindo que o código do domínio (estratégias, bot engine) seja
    completamente desacoplado da exchange específica.

    Esta abstração permite:
    - Trocar MockExchange ↔ BybitClient sem alterar a estratégia
    - Adicionar cache, retry, normalização de dados em um único lugar
    - Testar estratégias offline com dados simulados

    Parâmetros:
        exchange: Implementação de BaseExchange a usar.
                  Em paper trading: MockExchange.
                  Em FASE 3A: BybitClient(read-only).
        default_symbol: Símbolo padrão para chamadas sem symbol explícito.
        default_timeframe: Timeframe padrão (ex: "15" para 15 minutos).
    """

    def __init__(
        self,
        exchange: BaseExchange,
        default_symbol: str = "BTCUSDT",
        default_timeframe: str = "15",
    ) -> None:
        """
        Inicializa o MarketDataService.

        Args:
            exchange: Implementação de BaseExchange (obrigatório).
            default_symbol: Símbolo padrão.
            default_timeframe: Timeframe padrão.

        Raises:
            ValueError: Se exchange for None.
        """
        if exchange is None:
            raise ValueError(
                "MarketDataService requer uma instância de BaseExchange. "
                "Use MockExchange para paper trading ou BybitClient para dados reais."
            )

        self._exchange = exchange
        self._default_symbol = default_symbol
        self._default_timeframe = default_timeframe

        _logger.info(
            f"MarketDataService inicializado | "
            f"exchange={exchange.name} | "
            f"default_symbol={default_symbol} | "
            f"default_timeframe={default_timeframe}"
        )

    # -----------------------------------------------------------------------
    # Dados de Candlestick / OHLCV
    # -----------------------------------------------------------------------

    def get_candles(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 200,
    ) -> List[Candle]:
        """
        Obtém candles OHLCV históricas.

        As candles são retornadas em ordem cronológica (mais antiga → mais recente).
        A mais recente é a última da lista: `candles[-1]`.

        Args:
            symbol: Símbolo do ativo. Se None, usa default_symbol.
            timeframe: Timeframe. Se None, usa default_timeframe.
                       Exemplos: "1", "5", "15", "60", "240", "D".
            limit: Quantidade de candles a retornar.

        Returns:
            Lista de Candle ordenadas do mais antigo para o mais recente.
            Retorna lista vazia em caso de erro (com log de warning).

        Exemplo:
            candles = service.get_candles("BTCUSDT", "15", limit=100)
            last_candle = candles[-1]
            closes = [c.close for c in candles]
        """
        sym = symbol or self._default_symbol
        tf = timeframe or self._default_timeframe

        _logger.debug(
            f"MarketDataService.get_candles | "
            f"symbol={sym} | timeframe={tf} | limit={limit} | "
            f"exchange={self._exchange.name}"
        )

        try:
            candles = self._exchange.get_candles(symbol=sym, timeframe=tf, limit=limit)
        except Exception as e:
            _logger.error(
                f"MarketDataService.get_candles: erro ao buscar dados | "
                f"symbol={sym} | exchange={self._exchange.name} | error={e}"
            )
            return []

        if not candles:
            _logger.warning(
                f"MarketDataService.get_candles: lista vazia retornada | "
                f"symbol={sym} | exchange={self._exchange.name}"
            )

        return candles

    def get_closes(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 200,
    ) -> List[float]:
        """
        Retorna apenas os preços de fechamento das candles.

        Conveniente para indicadores que precisam apenas dos closes (SMA, EMA, RSI...).

        Args:
            symbol: Símbolo do ativo.
            timeframe: Timeframe.
            limit: Quantidade de candles.

        Returns:
            Lista de floats com os preços de fechamento (mais antigo → mais recente).
        """
        candles = self.get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        return [c.close for c in candles]

    def get_volumes(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 200,
    ) -> List[float]:
        """
        Retorna apenas os volumes das candles.

        Args:
            symbol: Símbolo do ativo.
            timeframe: Timeframe.
            limit: Quantidade de candles.

        Returns:
            Lista de floats com os volumes (mais antigo → mais recente).
        """
        candles = self.get_candles(symbol=symbol, timeframe=timeframe, limit=limit)
        return [c.volume for c in candles]

    # -----------------------------------------------------------------------
    # Dados de Ticker / Preço Atual
    # -----------------------------------------------------------------------

    def get_ticker(self, symbol: Optional[str] = None) -> Optional[Ticker]:
        """
        Obtém o ticker atual (preço, bid, ask, volume 24h).

        Args:
            symbol: Símbolo do ativo. Se None, usa default_symbol.

        Returns:
            Ticker com dados atuais, ou None se houver erro.
        """
        sym = symbol or self._default_symbol

        _logger.debug(
            f"MarketDataService.get_ticker | symbol={sym} | exchange={self._exchange.name}"
        )

        try:
            ticker = self._exchange.get_ticker(symbol=sym)
            return ticker
        except Exception as e:
            _logger.error(
                f"MarketDataService.get_ticker: erro | "
                f"symbol={sym} | exchange={self._exchange.name} | error={e}"
            )
            return None

    def get_latest_price(self, symbol: Optional[str] = None) -> Optional[float]:
        """
        Retorna apenas o último preço de um ativo.

        Conveniência sobre get_ticker() para quando se precisa apenas do preço.

        Args:
            symbol: Símbolo do ativo. Se None, usa default_symbol.

        Returns:
            Último preço como float, ou None se houver erro.

        Exemplo:
            price = service.get_latest_price("BTCUSDT")
            if price:
                print(f"BTC atual: ${price:,.2f}")
        """
        ticker = self.get_ticker(symbol=symbol)
        if ticker is None:
            return None
        return ticker.last_price

    # -----------------------------------------------------------------------
    # Order Book
    # -----------------------------------------------------------------------

    def get_order_book(
        self,
        symbol: Optional[str] = None,
        depth: int = 25,
    ) -> Optional[OrderBook]:
        """
        Obtém snapshot do livro de ofertas (somente leitura).

        Args:
            symbol: Símbolo do ativo. Se None, usa default_symbol.
            depth: Profundidade do livro (quantidade de níveis por lado).

        Returns:
            OrderBook com bids e asks, ou None se houver erro.

        Exemplo:
            ob = service.get_order_book("BTCUSDT", depth=10)
            if ob:
                print(f"Melhor bid: {ob.best_bid}")
                print(f"Melhor ask: {ob.best_ask}")
                print(f"Mid price: {ob.mid_price}")
        """
        sym = symbol or self._default_symbol

        _logger.debug(
            f"MarketDataService.get_order_book | "
            f"symbol={sym} | depth={depth} | exchange={self._exchange.name}"
        )

        try:
            order_book = self._exchange.get_order_book(symbol=sym, depth=depth)
            return order_book
        except Exception as e:
            _logger.error(
                f"MarketDataService.get_order_book: erro | "
                f"symbol={sym} | exchange={self._exchange.name} | error={e}"
            )
            return None

    # -----------------------------------------------------------------------
    # Utilitários
    # -----------------------------------------------------------------------

    def build_market_data_dict(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        limit: int = 200,
    ) -> dict:
        """
        Constrói o dicionário de market_data no formato esperado pelas estratégias.

        Este método agrega candles e ticker em um único dicionário padronizado,
        compatível com o formato que BaseStrategy.generate_signal() espera.

        Args:
            symbol: Símbolo do ativo.
            timeframe: Timeframe.
            limit: Quantidade de candles.

        Returns:
            Dicionário com:
                symbol, close, open, high, low, volume, closes, volumes,
                candles (lista completa), ticker (objeto Ticker ou None)

        Exemplo:
            market_data = service.build_market_data_dict("BTCUSDT", "15", limit=100)
            signal = strategy.generate_signal(market_data)
        """
        sym = symbol or self._default_symbol
        tf = timeframe or self._default_timeframe

        candles = self.get_candles(symbol=sym, timeframe=tf, limit=limit)
        ticker = self.get_ticker(symbol=sym)

        if candles:
            last = candles[-1]
            return {
                "symbol": sym,
                "timeframe": tf,
                "close": last.close,
                "open": last.open,
                "high": last.high,
                "low": last.low,
                "volume": last.volume,
                "timestamp": last.timestamp,
                "closes": [c.close for c in candles],
                "opens": [c.open for c in candles],
                "highs": [c.high for c in candles],
                "lows": [c.low for c in candles],
                "volumes": [c.volume for c in candles],
                "timestamps": [c.timestamp for c in candles],
                "candles": candles,
                "ticker": ticker,
            }

        # Sem dados de candle disponíveis
        return {
            "symbol": sym,
            "timeframe": tf,
            "close": ticker.last_price if ticker else 0.0,
            "open": 0.0,
            "high": 0.0,
            "low": 0.0,
            "volume": 0.0,
            "timestamp": None,
            "closes": [],
            "opens": [],
            "highs": [],
            "lows": [],
            "volumes": [],
            "timestamps": [],
            "candles": [],
            "ticker": ticker,
        }

    @property
    def exchange(self) -> BaseExchange:
        """A exchange subjacente sendo utilizada."""
        return self._exchange

    @property
    def default_symbol(self) -> str:
        return self._default_symbol

    @property
    def default_timeframe(self) -> str:
        return self._default_timeframe

    def __repr__(self) -> str:
        return (
            f"MarketDataService("
            f"exchange={self._exchange.name}, "
            f"symbol={self._default_symbol}, "
            f"timeframe={self._default_timeframe})"
        )
