"""
Crypto Trading Bot
==================
Bot de trading quantitativo/assistido por IA para criptomoedas.

Modo padrão: PAPER TRADING (simulação sem ordens reais).
Nenhuma ordem real é enviada sem ativação explícita e intencional.

Versão: 0.1.0
"""

__version__ = "0.1.0"
__author__ = "Thiago"
__description__ = "Crypto Trading Bot — Paper Trading First"

# Importação explícita do ModeGuard para garantir que a proteção
# seja carregada assim que o pacote for importado.
from crypto_trading_bot.core.mode_guard import ModeGuard

__all__ = ["ModeGuard", "__version__"]
