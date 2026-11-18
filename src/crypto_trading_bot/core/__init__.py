"""
Módulo Core — Núcleo do Sistema
================================
Contém o orquestrador principal do bot e os componentes de segurança.

Componentes:
- ModeGuard: proteção contra execução real acidental (CRÍTICO)
- BotEngine: loop principal de decisão
- EventBus: barramento interno de eventos

⚠️  O ModeGuard deve ser verificado ANTES de qualquer operação de mercado.
"""

from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError

__all__ = ["ModeGuard", "TradingModeError"]
