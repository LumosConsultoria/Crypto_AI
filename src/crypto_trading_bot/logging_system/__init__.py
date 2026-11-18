"""
Sistema de Logs
================
Fornece logging estruturado para todo o sistema.

Todos os logs são formatados de forma auditável e armazenados
em arquivos rotativos. Logs de decisões de risco e ordens
são mantidos em arquivos separados para auditoria.

Uso:
    from crypto_trading_bot.logging_system import get_logger

    logger = get_logger(__name__)
    logger.info("Mensagem de log")
"""

from crypto_trading_bot.logging_system.logger import get_logger, setup_logging

__all__ = ["get_logger", "setup_logging"]
