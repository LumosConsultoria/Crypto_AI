"""
Módulo operational_safety — Máquina de estado consultiva (FASE 16)
====================================================================
⚠️  PROVIDER-AGNOSTIC. NÃO importa BybitClient, BybitDemoExecutor,
    RiskEngine, BotEngine, httpx ou providers.
⚠️  Esta máquina é CONSULTIVA. Caller decide bloquear/permitir consultando
    can_open_new_position / can_modify_positions / requires_operator_ack.
⚠️  Default initial_state = NORMAL.

Exports:
    SafetyState, SafetyEvent, InvalidSafetyTransition, SafetyStateMachine.
"""

from crypto_trading_bot.operational_safety.safety_state import (
    InvalidSafetyTransition,
    SafetyEvent,
    SafetyState,
)
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)

__all__ = [
    "SafetyState",
    "SafetyEvent",
    "InvalidSafetyTransition",
    "SafetyStateMachine",
]
