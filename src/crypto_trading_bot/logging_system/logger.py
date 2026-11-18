"""
Logger Central do Sistema
==========================
Configura e fornece instâncias de logger usando loguru.

Características:
- Saída colorida e formatada no console
- Arquivos de log rotativos por tamanho e por dia
- Logs separados por categoria (geral, risco, ordens, sinais, auditoria)
- Formato estruturado para fácil parsing
- Nível de log configurável via variável de ambiente

Uso:
    from crypto_trading_bot.logging_system.logger import get_logger, setup_logging

    setup_logging()  # Chamar UMA vez na inicialização do sistema
    logger = get_logger(__name__)
    logger.info("Sistema iniciado")
    logger.warning("Sinal bloqueado pelo risco")
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger as _loguru_logger


# Formato padrão para console
_CONSOLE_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# Formato para arquivo (sem cores, mais detalhado)
_FILE_FORMAT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "{level: <8} | "
    "{name}:{function}:{line} | "
    "{message}"
)

# Controla se o setup já foi executado
_setup_done: bool = False


def setup_logging(
    log_level: str = "INFO",
    log_dir: Optional[Path] = None,
    retention_days: int = 30,
) -> None:
    """
    Configura o sistema de logging.

    Deve ser chamado UMA VEZ na inicialização do sistema.
    Se chamado novamente, remove todos os handlers anteriores.

    Args:
        log_level: Nível mínimo de log (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_dir: Diretório para arquivos de log. Se None, usa ./logs.
        retention_days: Quantos dias manter os arquivos de log.
    """
    global _setup_done

    # Remove todos os handlers padrão do loguru
    _loguru_logger.remove()

    # Resolve o diretório de logs
    resolved_log_dir = Path(log_dir) if log_dir else Path("logs")
    resolved_log_dir.mkdir(parents=True, exist_ok=True)

    # --- Handler de Console ---
    _loguru_logger.add(
        sys.stdout,
        level=log_level,
        format=_CONSOLE_FORMAT,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # --- Handler Geral (arquivo rotativo) ---
    _loguru_logger.add(
        resolved_log_dir / "bot_{time:YYYY-MM-DD}.log",
        level=log_level,
        format=_FILE_FORMAT,
        rotation="00:00",              # Rotaciona à meia-noite
        retention=f"{retention_days} days" if retention_days > 0 else None,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,               # Desabilitado em arquivo por segurança
    )

    # --- Handler de Erros (arquivo separado) ---
    _loguru_logger.add(
        resolved_log_dir / "errors_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format=_FILE_FORMAT,
        rotation="00:00",
        retention=f"{retention_days} days" if retention_days > 0 else None,
        compression="gz",
        encoding="utf-8",
        backtrace=True,
        diagnose=False,
    )

    # --- Handler de Auditoria (ordens + risco + sinais) ---
    # Este arquivo registra TODAS as decisões críticas do sistema.
    # Deve ser tratado como imutável em produção.
    _loguru_logger.add(
        resolved_log_dir / "audit_{time:YYYY-MM-DD}.log",
        level="INFO",
        format=_FILE_FORMAT,
        filter=lambda record: record["extra"].get("audit", False),
        rotation="00:00",
        retention=f"{retention_days} days" if retention_days > 0 else None,
        compression="gz",
        encoding="utf-8",
        backtrace=False,
        diagnose=False,
    )

    _setup_done = True

    _loguru_logger.info(
        f"Sistema de logging iniciado | level={log_level} | dir={resolved_log_dir.resolve()}"
    )


def get_logger(name: str) -> "logger":  # type: ignore[name-defined]
    """
    Retorna um logger vinculado ao nome do módulo.

    O logger herda toda a configuração definida em setup_logging().
    Se setup_logging() não foi chamado, usa configuração mínima.

    Args:
        name: Nome do módulo (use __name__ para identificação automática).

    Returns:
        Instância de logger do loguru com bind ao nome do módulo.

    Exemplo:
        logger = get_logger(__name__)
        logger.info("Módulo iniciado")
    """
    if not _setup_done:
        # Configuração mínima para casos onde setup não foi chamado
        # (ex: uso isolado de módulos em testes)
        _loguru_logger.remove()
        _loguru_logger.add(sys.stdout, level="DEBUG", format=_CONSOLE_FORMAT, colorize=True)

    return _loguru_logger.bind(module=name)


def get_audit_logger(name: str) -> "logger":  # type: ignore[name-defined]
    """
    Retorna um logger de auditoria para decisões críticas.

    Todas as mensagens enviadas via este logger são gravadas
    também no arquivo de auditoria separado.

    Use para: sinais, decisões de risco, ordens, bloqueios.

    Args:
        name: Nome do módulo.

    Returns:
        Logger com flag de auditoria ativada.
    """
    return _loguru_logger.bind(module=name, audit=True)
