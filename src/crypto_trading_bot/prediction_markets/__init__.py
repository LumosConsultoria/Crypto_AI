"""
prediction_markets - Polymarket/prediction markets READ-ONLY (FASE 34)
=======================================================================
Camada de inteligencia/contexto/research. NUNCA executa aposta/ordem,
NUNCA altera sinal/risco/perfil/estrategia, NUNCA bypassa gates.

Execucao = seam futuro BLOQUEADO (execution_protocol).
"""

from crypto_trading_bot.prediction_markets.execution_protocol import (
    PredictionExecutionBlocked,
    PredictionMarketExecutionProtocol,
)
from crypto_trading_bot.prediction_markets.market_event_model import (
    MarketEvent,
)
from crypto_trading_bot.prediction_markets.polymarket_readonly_client import (
    PROVIDER_ID,
    PolymarketReadonlyClient,
)
from crypto_trading_bot.prediction_markets.prediction_context_builder import (
    PredictionMarketContext,
    build_prediction_context,
    disabled_context,
)
from crypto_trading_bot.prediction_markets.prediction_market_risk_flags \
    import (
        ALL_RISK_FLAGS,
        FLAG_HIGH_BTC_RELEVANCE,
        FLAG_LOW_LIQUIDITY,
        FLAG_MACRO_EVENT_VOLATILITY,
        FLAG_RAPID_PROBABILITY_SHIFT,
        derive_risk_flags,
        highest_priority_flag,
    )
from crypto_trading_bot.prediction_markets.prediction_signal_normalizer \
    import normalize_raw_event, normalize_raw_events

__all__ = [
    "ALL_RISK_FLAGS",
    "FLAG_HIGH_BTC_RELEVANCE",
    "FLAG_LOW_LIQUIDITY",
    "FLAG_MACRO_EVENT_VOLATILITY",
    "FLAG_RAPID_PROBABILITY_SHIFT",
    "MarketEvent",
    "PROVIDER_ID",
    "PolymarketReadonlyClient",
    "PredictionExecutionBlocked",
    "PredictionMarketContext",
    "PredictionMarketExecutionProtocol",
    "build_prediction_context",
    "derive_risk_flags",
    "disabled_context",
    "highest_priority_flag",
    "normalize_raw_event",
    "normalize_raw_events",
]
