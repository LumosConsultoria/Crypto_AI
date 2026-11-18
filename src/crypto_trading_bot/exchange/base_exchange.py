"""
BaseExchange — Interface Abstrata de Exchange
==============================================
Define o contrato comum para todas as implementações de exchange.

Permite trocar de exchange (Bybit → outro) sem alterar o resto do sistema.
Toda implementação concreta (BybitClient, MockExchange) deve herdar desta classe.

Estrutura dos dados retornados é padronizada para independer da exchange.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes de mercado
# ---------------------------------------------------------------------------

@dataclass
class Ticker:
    """Dados de ticker (preço atual) de um ativo."""
    symbol: str
    last_price: float
    bid: float
    ask: float
    volume_24h: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def spread(self) -> float:
        """Spread entre ask e bid."""
        return self.ask - self.bid

    @property
    def spread_pct(self) -> float:
        """Spread percentual em relação ao último preço."""
        if self.last_price <= 0:
            return 0.0
        return self.spread / self.last_price


@dataclass
class Candle:
    """Dados de uma candle OHLCV."""
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low


@dataclass
class OrderBook:
    """Snapshot do livro de ofertas."""
    symbol: str
    bids: List[tuple[float, float]]  # [(price, qty), ...]
    asks: List[tuple[float, float]]  # [(price, qty), ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None


@dataclass
class OrderResult:
    """Resultado de uma ordem enviada à exchange."""
    order_id: str
    symbol: str
    side: str          # "buy" | "sell"
    order_type: str    # "market" | "limit"
    qty: float
    price: Optional[float]
    status: str        # "filled" | "partially_filled" | "open" | "cancelled"
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    fee: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw: Dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# BaseExchange
# ---------------------------------------------------------------------------

class BaseExchange(ABC):
    """
    Interface abstrata para clientes de exchange.

    Todas as implementações (MockExchange, BybitClient) devem seguir este contrato.
    O BotEngine e o PaperTrader interagem APENAS com esta interface.

    Métodos de dados (get_ticker, get_candles, get_order_book) são seguros em todos os modos.
    Métodos de execução (place_order, cancel_order) podem ser bloqueados pelo ModeGuard.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome da exchange (ex: 'bybit', 'mock')."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Verdadeiro se a conexão com a exchange está ativa."""
        ...

    # -----------------------------------------------------------------------
    # Métodos de Dados (read-only — seguros em todos os modos)
    # -----------------------------------------------------------------------

    @abstractmethod
    def get_ticker(self, symbol: str) -> Ticker:
        """
        Obtém o ticker atual de um símbolo.

        Args:
            symbol: Símbolo do ativo (ex: "BTCUSDT").

        Returns:
            Ticker com preço atual, bid, ask e volume.
        """
        ...

    @abstractmethod
    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> List[Candle]:
        """
        Obtém candles OHLCV históricas.

        Args:
            symbol: Símbolo do ativo.
            timeframe: Timeframe (ex: "1", "5", "15", "60", "D").
            limit: Quantidade de candles a retornar.

        Returns:
            Lista de candles ordenadas do mais antigo para o mais recente.
        """
        ...

    @abstractmethod
    def get_order_book(self, symbol: str, depth: int = 25) -> OrderBook:
        """
        Obtém snapshot do livro de ofertas.

        Args:
            symbol: Símbolo do ativo.
            depth: Profundidade do livro (quantidade de níveis por lado).

        Returns:
            OrderBook com bids e asks.
        """
        ...

    # -----------------------------------------------------------------------
    # Métodos de Execução (requerem autorização do ModeGuard)
    # -----------------------------------------------------------------------

    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        """
        Envia uma ordem a mercado.

        ⚠️  ATENÇÃO: Em modo live, esta ordem usa dinheiro real.
        Sempre verifique o ModeGuard antes de chamar este método.

        Args:
            symbol: Símbolo do ativo.
            side: "buy" ou "sell".
            qty: Quantidade do ativo.
            stop_loss: Preço de stop loss (obrigatório se configurado no RiskEngine).
            take_profit: Preço de take profit (opcional).

        Returns:
            OrderResult com detalhes da ordem.
        """
        ...

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Cancela uma ordem aberta.

        Args:
            symbol: Símbolo do ativo.
            order_id: ID da ordem a cancelar.

        Returns:
            True se cancelada com sucesso.
        """
        ...

    @abstractmethod
    def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """
        Obtém posições abertas.

        Args:
            symbol: Se fornecido, filtra por símbolo. None = todos.

        Returns:
            Lista de dicionários com detalhes das posições.
        """
        ...

    @abstractmethod
    def get_balance(self) -> Dict[str, float]:
        """
        Obtém saldo da conta.

        Returns:
            Dicionário {moeda: saldo} (ex: {"USDT": 5000.0}).
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, connected={self.is_connected})"
