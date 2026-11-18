"""
MockExchange — Exchange Simulada para Testes e Paper Trading
=============================================================
Implementação completa da BaseExchange sem qualquer conexão real com API.

Características:
    - Simula preços com variação aleatória controlada
    - Mantém estado de saldo e posições em memória
    - Gera order IDs únicos
    - Registra todas as operações em log
    - Totalmente segura — nunca envia ordens reais
    - Adequada para: testes unitários, paper trading, backtesting

Uso:
    exchange = MockExchange(initial_price=65000.0)
    ticker = exchange.get_ticker("BTCUSDT")
    result = exchange.place_market_order("BTCUSDT", "buy", qty=0.01)
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from crypto_trading_bot.exchange.base_exchange import (
    BaseExchange,
    Candle,
    OrderBook,
    OrderResult,
    Ticker,
)
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


class MockExchange(BaseExchange):
    """
    Implementação simulada de exchange para paper trading e testes.

    Simula comportamento realista de uma exchange sem qualquer conexão real.
    Todos os métodos de execução são seguros e apenas atualizam estado em memória.

    Parâmetros:
        initial_price: Preço inicial do ativo principal (default: 65000.0 USD para BTC)
        initial_balance_usdt: Saldo inicial em USDT (default: 5000.0)
        price_volatility: Variação de preço simulada por tick (default: 0.001 = 0.1%)
        simulated_fee_pct: Taxa simulada por operação (default: 0.001 = 0.1%)
    """

    def __init__(
        self,
        initial_price: float = 65000.0,
        initial_balance_usdt: float = 5000.0,
        price_volatility: float = 0.001,
        simulated_fee_pct: float = 0.001,
    ) -> None:
        self._current_price = initial_price
        self._price_volatility = price_volatility
        self._fee_pct = simulated_fee_pct
        self._connected = True

        # Estado da conta simulada
        self._balance: Dict[str, float] = {"USDT": initial_balance_usdt}
        self._positions: Dict[str, Dict] = {}
        self._open_orders: Dict[str, Dict] = {}
        self._order_history: List[OrderResult] = []

        # Histórico de preços para simular candles
        self._price_history: List[float] = [initial_price]
        self._generate_price_history(periods=250)

        _logger.info(
            f"MockExchange inicializada | "
            f"price={initial_price} | "
            f"balance_usdt={initial_balance_usdt}"
        )

    # -----------------------------------------------------------------------
    # Propriedades obrigatórias
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -----------------------------------------------------------------------
    # Métodos de Dados
    # -----------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> Ticker:
        """Retorna ticker simulado com preço variável."""
        price = self._get_simulated_price()
        spread = price * 0.0001  # 0.01% de spread simulado

        return Ticker(
            symbol=symbol,
            last_price=price,
            bid=round(price - spread / 2, 2),
            ask=round(price + spread / 2, 2),
            volume_24h=round(random.uniform(10000, 50000), 2),
            timestamp=datetime.now(timezone.utc),
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> List[Candle]:
        """Retorna candles OHLCV simuladas baseadas no histórico de preços."""
        candles: List[Candle] = []
        prices = self._price_history[-limit:] if len(self._price_history) >= limit else self._price_history

        base_time = datetime.now(timezone.utc) - timedelta(minutes=len(prices) * int(timeframe or "15"))

        for i, close_price in enumerate(prices):
            # Simula OHLC com variação dentro da candle
            variation = close_price * 0.005  # 0.5% de variação intra-candle
            open_price = prices[i - 1] if i > 0 else close_price
            high = round(max(open_price, close_price) + abs(random.gauss(0, variation)), 2)
            low = round(min(open_price, close_price) - abs(random.gauss(0, variation)), 2)
            volume = round(random.uniform(50, 500), 4)

            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=base_time + timedelta(minutes=i * int(timeframe or "15")),
                open=round(open_price, 2),
                high=high,
                low=max(low, 1.0),  # preço nunca negativo
                close=round(close_price, 2),
                volume=volume,
            )
            candles.append(candle)

        return candles

    def get_order_book(self, symbol: str, depth: int = 25) -> OrderBook:
        """Retorna order book simulado em torno do preço atual."""
        price = self._current_price
        tick = price * 0.0001  # tamanho do tick simulado

        bids = [
            (round(price - tick * (i + 1), 2), round(random.uniform(0.01, 2.0), 4))
            for i in range(depth)
        ]
        asks = [
            (round(price + tick * (i + 1), 2), round(random.uniform(0.01, 2.0), 4))
            for i in range(depth)
        ]

        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
        )

    # -----------------------------------------------------------------------
    # Métodos de Execução (simulados — sem API real)
    # -----------------------------------------------------------------------

    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        """
        Simula execução de ordem a mercado.

        Atualiza saldo e posições em memória. Não envia nenhuma requisição real.

        Args:
            symbol: Símbolo do ativo.
            side: "buy" ou "sell".
            qty: Quantidade a negociar.
            stop_loss: Preço de stop loss (registrado, mas não monitorado automaticamente).
            take_profit: Preço de take profit (registrado, mas não monitorado automaticamente).

        Returns:
            OrderResult com status "filled".
        """
        fill_price = self._get_simulated_price()
        order_value = qty * fill_price
        fee = order_value * self._fee_pct
        order_id = str(uuid.uuid4())[:8].upper()

        # Atualiza saldo e posições
        if side.lower() == "buy":
            total_cost = order_value + fee
            if self._balance.get("USDT", 0) < total_cost:
                _logger.warning(
                    f"MockExchange: saldo insuficiente para {symbol} {side}. "
                    f"Requerido={total_cost:.2f}, Disponível={self._balance.get('USDT', 0):.2f}"
                )
            self._balance["USDT"] = max(0.0, self._balance.get("USDT", 0) - total_cost)
            # Registra posição aberta
            self._positions[symbol] = {
                "symbol": symbol,
                "side": "buy",
                "qty": qty,
                "entry_price": fill_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "opened_at": datetime.now(timezone.utc),
            }
        else:  # sell
            self._balance["USDT"] = self._balance.get("USDT", 0) + order_value - fee
            self._positions.pop(symbol, None)

        result = OrderResult(
            order_id=order_id,
            symbol=symbol,
            side=side.lower(),
            order_type="market",
            qty=qty,
            price=fill_price,
            status="filled",
            filled_qty=qty,
            avg_fill_price=fill_price,
            fee=fee,
            timestamp=datetime.now(timezone.utc),
            raw={
                "simulated": True,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
        )

        self._order_history.append(result)

        _logger.info(
            f"MockExchange.place_market_order | "
            f"id={order_id} | "
            f"symbol={symbol} | "
            f"side={side} | "
            f"qty={qty} | "
            f"price={fill_price} | "
            f"fee={fee:.4f} | "
            f"[SIMULADO]"
        )

        return result

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Simula cancelamento de ordem (sempre bem-sucedido)."""
        _logger.info(f"MockExchange.cancel_order | id={order_id} | symbol={symbol} | [SIMULADO]")
        self._open_orders.pop(order_id, None)
        return True

    def get_positions(self, symbol: Optional[str] = None) -> List[Dict]:
        """Retorna posições abertas simuladas."""
        if symbol:
            pos = self._positions.get(symbol)
            return [pos] if pos else []
        return list(self._positions.values())

    def get_balance(self) -> Dict[str, float]:
        """Retorna saldo simulado."""
        return dict(self._balance)

    # -----------------------------------------------------------------------
    # Métodos auxiliares
    # -----------------------------------------------------------------------

    def _get_simulated_price(self) -> float:
        """
        Gera um preço simulado com caminho aleatório (random walk).

        A variação é proporcional à volatilidade configurada.
        """
        change = random.gauss(0, self._price_volatility)
        new_price = max(1.0, self._current_price * (1 + change))
        self._current_price = round(new_price, 2)
        self._price_history.append(self._current_price)
        return self._current_price

    def _generate_price_history(self, periods: int = 250) -> None:
        """
        Gera histórico inicial de preços simulados.

        Cria um caminho aleatório para simular dados de mercado históricos.
        """
        price = self._current_price
        for _ in range(periods):
            change = random.gauss(0, self._price_volatility)
            price = max(1.0, price * (1 + change))
            self._price_history.append(round(price, 2))

    def set_price(self, price: float) -> None:
        """
        Define o preço atual manualmente.

        Útil para testes unitários que precisam de preços determinísticos.

        Args:
            price: Novo preço atual.
        """
        self._current_price = price
        self._price_history.append(price)

    @property
    def current_price(self) -> float:
        """Preço atual simulado."""
        return self._current_price

    @property
    def order_history(self) -> List[OrderResult]:
        """Histórico de ordens simuladas."""
        return list(self._order_history)
