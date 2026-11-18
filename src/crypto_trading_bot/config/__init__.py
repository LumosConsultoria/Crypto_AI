"""
Módulo de Configuração
======================
Carrega e valida todas as configurações do sistema a partir de variáveis
de ambiente (.env). Nenhum segredo deve estar em código.

Uso:
    from crypto_trading_bot.config import settings, risk_config
"""

from crypto_trading_bot.config.settings import Settings, get_settings
from crypto_trading_bot.config.risk_config import RiskConfig, get_risk_config
from crypto_trading_bot.config.exchange_config import ExchangeConfig, get_exchange_config

__all__ = [
    "Settings",
    "get_settings",
    "RiskConfig",
    "get_risk_config",
    "ExchangeConfig",
    "get_exchange_config",
]
