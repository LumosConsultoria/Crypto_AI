"""
backtest_operational - Backtest Operational Parity (FASE 37)
============================================================
Camada de backtest com PARIDADE OPERACIONAL com a demo (RiskEngine
soberano, perfil, estrategia validada, custos, decision trace, contexto
externo auditado) porem SEM execucao real, SEM API, SEM secret.

  * execution_context  -> BacktestExecutionContext (todos os toggles).
  * context_availability -> IA/MI/Poly so com dado REAL, anti look-ahead.
  * strategy_registry  -> selecao validada contra registry + perfil.
  * runner             -> run_operational_backtest (motor validado +
                          decision trace + disponibilidade de contexto).
  * report             -> BacktestOperationalReport (enabled vs
                          context_available vs decision_impact).
"""

from crypto_trading_bot.backtest_operational.context_availability import (
    CONTEXT_KINDS,
    ContextAvailability,
    ContextDataset,
    ContextSnapshot,
    LookAheadError,
    resolve_context,
    with_decision_impact,
)
from crypto_trading_bot.backtest_operational.execution_context import (
    RISK_ENGINE_MIN_STOP_LOSS_PCT,
    BacktestContextError,
    BacktestExecutionContext,
)
from crypto_trading_bot.backtest_operational.report import (
    BacktestOperationalReport,
    ContextAvailabilitySummary,
)
from crypto_trading_bot.backtest_operational.runner import (
    BacktestRunnerError,
    run_operational_backtest,
)
from crypto_trading_bot.backtest_operational.strategy_registry import (
    CANONICAL_STRATEGY_NAMES,
    StrategySelectionError,
    default_backtest_registry,
    list_backtest_strategies,
    resolve_strategy_spec,
)

__all__ = [
    "BacktestContextError",
    "BacktestExecutionContext",
    "BacktestOperationalReport",
    "BacktestRunnerError",
    "CANONICAL_STRATEGY_NAMES",
    "CONTEXT_KINDS",
    "ContextAvailability",
    "ContextAvailabilitySummary",
    "ContextDataset",
    "ContextSnapshot",
    "LookAheadError",
    "RISK_ENGINE_MIN_STOP_LOSS_PCT",
    "StrategySelectionError",
    "default_backtest_registry",
    "list_backtest_strategies",
    "resolve_strategy_spec",
    "resolve_context",
    "run_operational_backtest",
    "with_decision_impact",
]
