"""
Módulo de Exchange
===================
Abstrações e clientes para interação com exchanges de criptomoedas.

Estrutura de abstrações:
    BaseExchange → interface comum para todas as exchanges
    MockExchange → implementação simulada para testes (sem API real)
    BybitClient → cliente real Bybit (BLOQUEADO até FASE 3, requer testnet)

⚠️  O BybitClient real só é inicializado quando:
    - TRADING_MODE=testnet ou live no .env
    - Credenciais válidas configuradas no .env
    - ModeGuard permitir a conexão

Em modo paper, APENAS o MockExchange é usado.
"""

from crypto_trading_bot.exchange.base_exchange import BaseExchange, Candle, OrderBook, Ticker
from crypto_trading_bot.exchange.bybit_client import BybitAPIError, BybitClient, BybitExecutionBlockedError
from crypto_trading_bot.exchange.mock_exchange import MockExchange

__all__ = [
    "BaseExchange",
    "Candle",
    "OrderBook",
    "Ticker",
    "MockExchange",
    "BybitClient",
    "BybitAPIError",
    "BybitExecutionBlockedError",
]
