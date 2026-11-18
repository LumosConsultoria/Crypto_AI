"""
Módulo session_runner — Supervisor paper-only com gates (FASE 17)
====================================================================
⚠️  PAPER-ONLY. NÃO importa BybitClient, BybitDemoExecutor,
    BybitTestnetExecutor, DemoExecutionResult, httpx, requests, providers.
⚠️  Consome SafetyStateMachine (consultiva) + OperationalProfile
    (regras de sessão). NÃO substitui RiskEngine/ModeGuard.
⚠️  Constrói pipeline UMA vez no __init__ — preserva estado entre ciclos
    (open_trades, execution_count, consecutive_losses, etc.).
⚠️  PaperTradingOrchestrator permanece intocado byte-a-byte.

Exports:
    SessionRunner, SessionRunnerConfig,
    SessionRunResult, SessionBlockEvent, SessionStopReason.
"""

from crypto_trading_bot.session_runner.config import SessionRunnerConfig
from crypto_trading_bot.session_runner.result import (
    SessionBlockEvent,
    SessionRunResult,
    SessionStopReason,
)
from crypto_trading_bot.session_runner.runner import SessionRunner

__all__ = [
    "SessionRunner",
    "SessionRunnerConfig",
    "SessionRunResult",
    "SessionBlockEvent",
    "SessionStopReason",
]
