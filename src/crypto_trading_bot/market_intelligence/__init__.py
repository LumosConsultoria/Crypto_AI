"""
market_intelligence - Contexto de mercado READ-ONLY (FASE 36 Bloco D)
======================================================================
Fontes consultivas (funding, OI, orderbook, noticias, polymarket,
status, vol/correlacao). Nunca decide trade; nunca aumenta risco;
fonte ausente nunca bloqueia.
"""

from crypto_trading_bot.market_intelligence.adapters import (
    ExchangeStatusAdapter,
    FundingRateAdapter,
    NewsAdapter,
    OpenInterestAdapter,
    OrderbookAdapter,
    PolymarketAdapter,
    VolatilityCorrelationAdapter,
)
from crypto_trading_bot.market_intelligence.aggregator import (
    ENV_MARKET_INTELLIGENCE,
    MarketIntelligenceAggregator,
    market_intelligence_gate_enabled,
)
from crypto_trading_bot.market_intelligence.provider_protocol import (
    ContextSlice,
    MarketContextProvider,
    unavailable_slice,
)

__all__ = [
    "ContextSlice",
    "ENV_MARKET_INTELLIGENCE",
    "ExchangeStatusAdapter",
    "FundingRateAdapter",
    "MarketContextProvider",
    "MarketIntelligenceAggregator",
    "NewsAdapter",
    "OpenInterestAdapter",
    "OrderbookAdapter",
    "PolymarketAdapter",
    "VolatilityCorrelationAdapter",
    "market_intelligence_gate_enabled",
    "unavailable_slice",
]
