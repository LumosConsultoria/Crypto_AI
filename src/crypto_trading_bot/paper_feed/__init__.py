"""
paper_feed - feeds paper offline para SessionRunner (FASE 25)
================================================================
Modulo provider-agnostic e offline. Permite injetar candles
deterministicas no SessionRunner sem alterar MockExchange/MarketDataService
nem o pipeline real.

Tipos suportados (PaperFeedType):
    MOCK_RANDOM_WALK     - comportamento legado (default)
    SYNTHETIC_TRENDING   - control scenario para trend_pullback
    SYNTHETIC_RANGING    - control scenario para volatility_breakout
    CACHE                - data/historical/{symbol}_{timeframe}.csv local

⚠️  SEGURANCA:
    - NAO importa BybitClient/BybitDemoExecutor/httpx/requests.
    - NAO chama rede.
    - NAO le .env.
    - NAO expoe API key/secret/signature.
    - Cache eh APENAS leitura local; cache miss falha com erro claro.
"""

from crypto_trading_bot.paper_feed.adapter import PaperFeedAdapter
from crypto_trading_bot.paper_feed.exchange import FeedBackedMockExchange
from crypto_trading_bot.paper_feed.synthetic import (
    build_cache_feed,
    build_synthetic_ranging_feed,
    build_synthetic_trending_feed,
    build_synthetic_trend_pullback_feed,
    DEFAULT_RANGING_CENTER_PRICE,
    DEFAULT_RANGING_N,
    DEFAULT_RANGING_RANGE_PCT,
    DEFAULT_TRENDING_BASE_PRICE,
    DEFAULT_TRENDING_N,
    DEFAULT_TRENDING_TREND_PCT,
    DEFAULT_TRENDING_VOLATILITY_PCT,
)
from crypto_trading_bot.paper_feed.types import (
    PaperFeedType,
    is_synthetic,
    requires_signal_exercise,
)

__all__ = [
    "FeedBackedMockExchange",
    "PaperFeedAdapter",
    "PaperFeedType",
    "build_cache_feed",
    "build_synthetic_ranging_feed",
    "build_synthetic_trending_feed",
    "build_synthetic_trend_pullback_feed",
    "is_synthetic",
    "requires_signal_exercise",
    "DEFAULT_TRENDING_BASE_PRICE",
    "DEFAULT_TRENDING_N",
    "DEFAULT_TRENDING_TREND_PCT",
    "DEFAULT_TRENDING_VOLATILITY_PCT",
    "DEFAULT_RANGING_CENTER_PRICE",
    "DEFAULT_RANGING_N",
    "DEFAULT_RANGING_RANGE_PCT",
]
