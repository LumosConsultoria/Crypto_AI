"""
position_management - Gestao de posicao + risco agregado (Bloco E2)
====================================================================
Capacidade ARQUITETURAL de scale-in/reducao/reversao — TUDO default
OFF, gated, perfil-dependente, limites do operador (V5-V8) e risco
agregado SEMPRE revalidado via RiskEngine (soberania preservada).
"""

from crypto_trading_bot.position_management.gates_position_mgmt import (
    ENV_ALLOW_PARTIAL_REDUCE,
    ENV_ALLOW_REVERSAL,
    ENV_ALLOW_SCALE_IN,
    partial_reduce_gate_enabled,
    reversal_gate_enabled,
    scale_in_gate_enabled,
)
from crypto_trading_bot.position_management.policies import (
    MultiOrderPolicy,
    PartialReduceDecision,
    ReversalDecision,
    ScaleInDecision,
    ScaleInLimits,
    ScaleInProposal,
    evaluate_partial_reduce,
    evaluate_reversal,
    evaluate_scale_in,
)
from crypto_trading_bot.position_management.position_state import (
    AggregatedRiskSnapshot,
    ExposureState,
    PositionEntry,
    PositionState,
)

__all__ = [
    "AggregatedRiskSnapshot",
    "ENV_ALLOW_PARTIAL_REDUCE",
    "ENV_ALLOW_REVERSAL",
    "ENV_ALLOW_SCALE_IN",
    "ExposureState",
    "MultiOrderPolicy",
    "PartialReduceDecision",
    "PositionEntry",
    "PositionState",
    "ReversalDecision",
    "ScaleInDecision",
    "ScaleInLimits",
    "ScaleInProposal",
    "evaluate_partial_reduce",
    "evaluate_reversal",
    "evaluate_scale_in",
    "partial_reduce_gate_enabled",
    "reversal_gate_enabled",
    "scale_in_gate_enabled",
]
