"""
NetComms adapters (infra; FASE 43 realocado): callables READ-ONLY
allowlisted. Toda comunicacao real de rede usa estes adapters, SEMPRE via
`run_network_op` (gated, timeout, erro sanitizado, status). NUNCA execucao/
cancel/close/place. NUNCA expoe secret/header/signature. Em TESTES injeta-se
SEMPRE um fake (estes adapters reais NUNCA rodam em teste). FastAPI-free.
"""

from crypto_trading_bot.netcomms.adapters.bybit_readonly import (
    BybitReadOnlyAdapter,
)
from crypto_trading_bot.netcomms.adapters.public_market_data import (
    PublicMarketDataAdapter,
)

__all__ = ["BybitReadOnlyAdapter", "PublicMarketDataAdapter"]
