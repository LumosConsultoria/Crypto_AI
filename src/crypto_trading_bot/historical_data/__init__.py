"""
historical_data - Historical Data Fetcher (FASE 37 Parte A/B)
=============================================================
Camada READ-ONLY para buscar candles historicos via provider
(fake offline | binance publico read-only), normalizar para o CSV
canonico OHLCV/UTC e acionar Data Readiness.

⚠️  ZERO ordem / execucao / credencial de trade. Provider real usa
    SOMENTE endpoint publico read-only. Em testes, SEMPRE o
    FakeHistoricalProvider.
"""

from crypto_trading_bot.historical_data.fetcher import (
    CANONICAL_SCHEMA_VERSION,
    FetchResult,
    fetch_historical,
)
from crypto_trading_bot.historical_data.providers import (
    BinancePublicProvider,
    CandleRow,
    FakeHistoricalProvider,
    HistoricalDataError,
    HistoricalDataProvider,
    KNOWN_SYMBOLS,
    SUPPORTED_PROVIDERS,
    SUPPORTED_TIMEFRAMES,
    get_provider,
    normalize_timeframe,
    validate_fetch_request,
)

__all__ = [
    "BinancePublicProvider",
    "CANONICAL_SCHEMA_VERSION",
    "CandleRow",
    "FakeHistoricalProvider",
    "FetchResult",
    "HistoricalDataError",
    "HistoricalDataProvider",
    "KNOWN_SYMBOLS",
    "SUPPORTED_PROVIDERS",
    "SUPPORTED_TIMEFRAMES",
    "fetch_historical",
    "get_provider",
    "normalize_timeframe",
    "validate_fetch_request",
]
