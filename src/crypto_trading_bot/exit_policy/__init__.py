"""
Módulo Exit Policy — Gestão de Saída Determinística e Auditável (FASE 11)
==========================================================================
⚠️  REGRAS FUNDAMENTAIS:
    1. ExitPolicy NÃO executa ordem. Apenas decide e audita.
    2. ExitPolicy NÃO chama executor, NÃO chama rede, NÃO usa API key.
    3. ExitPolicy NÃO chama RiskEngine — RiskEngine é a SEGUNDA camada
       de proteção (anti-flip + invariantes) sem alteração.
    4. ExitDecision.auto_execute_blocked descreve a camada de CAPABILITY
       do provider. Capability ≠ autorização de execução. Mesmo False,
       execução real depende de ProviderStatus, ModeGuard, ambiente e
       fase futura de integração.
    5. require_reduce_only_for_auto_close=False NÃO libera fechamento
       automático em providers sem reduceOnly. Override afeta apenas
       o campo requires_reduce_only reportado.

Exports:
    ExitDecision, ExitReason, ExitSource, PositionSide,
    OpenPositionState, make_hold_decision, ExitPolicy
"""

from crypto_trading_bot.exit_policy.exit_decision import (
    ExitDecision,
    ExitReason,
    ExitSource,
    OpenPositionState,
    PositionSide,
    make_hold_decision,
)
from crypto_trading_bot.exit_policy.exit_policy import ExitPolicy
from crypto_trading_bot.exit_policy.paper_session import (
    PaperExitOrchestrator,
    paper_trade_to_open_position,
)

__all__ = [
    "ExitDecision",
    "ExitReason",
    "ExitSource",
    "PositionSide",
    "OpenPositionState",
    "make_hold_decision",
    "ExitPolicy",
    # FASE 13 — Paper Activation (opt-in)
    "PaperExitOrchestrator",
    "paper_trade_to_open_position",
]
