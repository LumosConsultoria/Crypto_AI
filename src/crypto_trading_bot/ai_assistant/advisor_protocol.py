"""
AIAdvisorProtocol + AIAdvice (FASE 32)
=======================================
Contrato da IA de APOIO de decisao.

⚠️  REGRA FUNDAMENTAL E INVIOLAVEL:
    A IA NUNCA envia ordem, NUNCA escolhe ordem sozinha, NUNCA altera
    TradingSignal/RiskResult/estrategia/perfil/risco, NUNCA bypassa
    RiskEngine/ModeGuard/gates, NUNCA transforma HOLD em BUY/SELL,
    NUNCA autoriza live/mainnet, NUNCA decide aposta em prediction
    markets.

    A IA so pode REDUZIR permissao (caution/veto/manual_review) ou
    permanecer neutra. does_not_override_risk_engine eh SEMPRE True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Tuple, runtime_checkable


class AIAdviceStatus(str, Enum):
    NEUTRAL = "neutral"
    CAUTION = "caution"
    VETO = "veto"
    MANUAL_REVIEW = "manual_review"


class AISuggestedAction(str, Enum):
    PROCEED = "proceed"
    WAIT = "wait"
    MANUAL_REVIEW = "manual_review"
    RESEARCH_REQUIRED = "research_required"


@dataclass(frozen=True)
class AIAdvice:
    """Parecer CONSULTIVO da IA sobre um ciclo de trade.

    does_not_override_risk_engine eh invariante True: tentar construir
    com False levanta ValueError (defesa em profundidade).
    """

    status: AIAdviceStatus
    confidence: float                  # 0..1
    reason: str
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    suggested_action: AISuggestedAction = AISuggestedAction.PROCEED
    does_not_override_risk_engine: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.status, AIAdviceStatus):
            raise TypeError("status deve ser AIAdviceStatus")
        if not isinstance(self.suggested_action, AISuggestedAction):
            raise TypeError(
                "suggested_action deve ser AISuggestedAction"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence em [0,1]: {self.confidence}"
            )
        if self.does_not_override_risk_engine is not True:
            raise ValueError(
                "does_not_override_risk_engine deve ser SEMPRE True: "
                "a IA nunca sobrepoe o RiskEngine"
            )
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        # Sanitiza reason (truncado; nunca carrega payload bruto)
        if not isinstance(self.reason, str):
            object.__setattr__(self, "reason", "")
        elif len(self.reason) > 300:
            object.__setattr__(self, "reason", self.reason[:300] + "...")

    @property
    def is_blocking(self) -> bool:
        """True se o parecer pede bloqueio/revisao (reducao de permissao)."""
        return self.status in (
            AIAdviceStatus.VETO, AIAdviceStatus.MANUAL_REVIEW,
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "confidence": float(self.confidence),
            "reason": self.reason,
            "warnings": list(self.warnings),
            "suggested_action": self.suggested_action.value,
            "does_not_override_risk_engine": True,
        }


@runtime_checkable
class AIAdvisorProtocol(Protocol):
    """Protocolo de advisor de IA. Implementacoes DEVEM ser consultivas."""

    def evaluate_trade_context(
        self, context: Mapping[str, Any],
    ) -> AIAdvice:
        """Avalia o contexto sanitizado de um ciclo e retorna AIAdvice.

        context: TradeCycleContextForAI.to_dict() — APENAS valores
        tecnicos/decisao; nunca secrets/objetos de execucao.
        """
        ...


__all__ = [
    "AIAdvice",
    "AIAdviceStatus",
    "AIAdvisorProtocol",
    "AISuggestedAction",
]
