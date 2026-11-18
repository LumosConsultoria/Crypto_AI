"""
Módulo de Dados de Mercado
===========================
Responsável pela coleta, processamento e cache de dados de mercado.

TODO (FASE 3): Implementar coleta real de dados via Bybit API.

Fontes planejadas:
    - Candles OHLCV (via exchange)
    - Order book em tempo real (WebSocket)
    - Fluxo de ordens / tape reading
    - Funding rate e Open Interest (Bybit futures)
    - Volatilidade (cálculos sobre OHLCV)
    - Liquidez (análise do order book)
    - Correlação entre ativos

Fontes futuras (FASE 4+):
    - Polymarket (expectativa de mercado)
    - Notícias e dados fundamentalistas
    - Dados on-chain

Nota sobre IA:
    Dados coletados aqui são usados por estratégias determinísticas.
    A IA auxiliar pode analisar esses dados para contexto,
    mas NUNCA para gerar sinais de trading diretamente.
"""

from crypto_trading_bot.data.data_cache import DataCache, DataCacheError
from crypto_trading_bot.data.data_quality import (
    DataQualityError,
    DataQualityIssue,
    DataQualityReport,
    timeframe_to_minutes,
    validate_candles,
    validate_candles_strict,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.historical_data import HistoricalDataService
from crypto_trading_bot.data.market_data import MarketDataService

__all__ = [
    "MarketDataService",
    "FeatureEngine",
    # FASE 3G — Dados históricos reais (read-only, público)
    "DataCache",
    "DataCacheError",
    "DataQualityIssue",
    "DataQualityReport",
    "DataQualityError",
    "validate_candles",
    "validate_candles_strict",
    "timeframe_to_minutes",
    "HistoricalDataService",
]
