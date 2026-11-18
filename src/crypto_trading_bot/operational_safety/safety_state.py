"""
SafetyState + SafetyEvent — Tipos imutáveis da máquina de safety (FASE 16)
============================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Módulo PROVIDER-AGNOSTIC. NÃO importa BybitClient, BybitDemoExecutor,
      DemoExecutionResult, RiskEngine, httpx ou providers.
    - SafetyEvent é frozen e serializável. NUNCA armazena api_key,
      api_secret, headers sensíveis, X-BAPI-SIGN ou Bearer tokens.
    - Estes tipos são CONSULTIVOS: caller decide bloquear/permitir.
      A FASE 16 entrega a base; runners consumidores ficam para fase futura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# SafetyState
# ---------------------------------------------------------------------------

class SafetyState(str, Enum):
    """
    Estados operacionais da máquina de safety.

    Valores são contrato — não renomear sem nova fase de quebra.

    Significado e implicações de continuidade:
        NORMAL                  — operação normal autorizada.
        MANUAL_REVIEW_REQUIRED  — fato ambíguo detectado (ex.: fill
                                  confirmado por triangulação). Bloqueia
                                  abertura de novas posições; permite
                                  diagnóstico/leitura. Exige ack humano.
        SAFETY_HALT_RECOMMENDED — sistema sugere parar; ainda não parou.
                                  Bloqueia abertura de novas posições.
        SAFETY_HALT_ACTIVE      — halt explicitamente ativado. Bloqueia
                                  abertura E modificação de posições.
                                  Apenas leitura/diagnóstico.
        OPERATOR_ACKNOWLEDGED   — operador confirmou estar ciente. Ainda
                                  exige resolve() explícito para retomar.
        RESOLVED                — incidente fechado. Próximo reset volta
                                  para NORMAL.
    """
    NORMAL = "normal"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SAFETY_HALT_RECOMMENDED = "safety_halt_recommended"
    SAFETY_HALT_ACTIVE = "safety_halt_active"
    OPERATOR_ACKNOWLEDGED = "operator_acknowledged"
    RESOLVED = "resolved"


# ---------------------------------------------------------------------------
# Exception de transição inválida
# ---------------------------------------------------------------------------

class InvalidSafetyTransition(ValueError):
    """
    Tentativa de transição inválida na SafetyStateMachine.

    Não silencia. Caller deve tratar OU corrigir o fluxo.
    """


# ---------------------------------------------------------------------------
# SafetyEvent — registro imutável de cada transição
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SafetyEvent:
    """
    Registro imutável de uma transição de estado da máquina.

    Frozen. Metadata é MappingProxyType (read-only).
    Timestamp é tz-aware (UTC). NUNCA armazena secrets.

    Atributos:
        event_type:    string identificadora do evento (ex.:
                       "MANUAL_REVIEW_REQUIRED", "SAFETY_HALT_TRIGGERED",
                       "OPERATOR_ACKNOWLEDGED", "SAFETY_STATE_RESOLVED",
                       "SAFETY_STATE_RESET").
        from_state:    SafetyState antes da transição.
        to_state:      SafetyState depois da transição.
        reason:        contexto humano-legível (sanitizado).
        triggered_at:  UTC; naive ⇒ promovido para UTC.
        metadata:      Mapping imutável; campos auxiliares de auditoria.
    """
    event_type: str
    from_state: SafetyState
    to_state: SafetyState
    reason: str
    triggered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        # Garante UTC tz-aware
        if self.triggered_at.tzinfo is None:
            object.__setattr__(
                self,
                "triggered_at",
                self.triggered_at.replace(tzinfo=timezone.utc),
            )
        # Garante metadata imutável
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )
        # Sanity: event_type não-vazio
        if not isinstance(self.event_type, str) or not self.event_type.strip():
            raise ValueError(
                f"SafetyEvent.event_type deve ser string não-vazia; "
                f"recebido {self.event_type!r}"
            )

    def to_dict(self) -> dict:
        """Serializa para dict JSON-friendly (sem secrets)."""
        return {
            "event_type": self.event_type,
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "triggered_at": self.triggered_at.isoformat(),
            "metadata": dict(self.metadata),
        }
