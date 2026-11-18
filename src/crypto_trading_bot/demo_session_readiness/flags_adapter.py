"""
SafetyFlags + adapters duck-typed — Demo Session Readiness (FASE 19)
======================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - PROVIDER-AGNOSTIC. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, RiskEngine, BotEngine,
      providers, httpx, requests.
    - Sem rede. Sem secrets. Funções puras.
    - SafetyFlags é frozen; metadata é MappingProxyType (read-only).
    - Adapter aceita objetos duck-typed (qualquer fake/SimpleNamespace
      com os atributos esperados). Não exige DemoExecutionResult real.

PROPÓSITO:
    SafetyFlags é o contrato genérico que DemoSessionReadinessCheck
    aceita como evidência de uma última tentativa de execução demo
    (real ou mock). Atributos espelham os campos consumidos por
    SafetyStateMachine.from_safety_flags (FASE 16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


_VALID_CONFIDENCE = ("canonical", "triangulated", "none")


@dataclass(frozen=True)
class SafetyFlags:
    """
    Flags genéricas de safety/reconciliação.

    Frozen. metadata é MappingProxyType (read-only).
    Defaults conservadores: tudo limpo, confidence=canonical.

    Campos:
        manual_review_required: bool
            Última execução demo precisa de revisão humana antes de
            qualquer abertura nova.
        safety_halt_recommended: bool
            Sistema recomenda parada explícita.
        reconciliation_confidence: str
            "canonical" | "triangulated" | "none". "triangulated" indica
            fill confirmado apenas por agregação (não canônico). Default
            "canonical" — clean.
        reason: str
            Texto humano-legível (sanitizado pelo consumer no log).
        metadata: Mapping[str, Any]
            Campos auxiliares; armazenados como MappingProxyType.
    """
    manual_review_required: bool = False
    safety_halt_recommended: bool = False
    reconciliation_confidence: str = "canonical"
    reason: str = ""
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.manual_review_required, bool):
            raise TypeError("manual_review_required deve ser bool")
        if not isinstance(self.safety_halt_recommended, bool):
            raise TypeError("safety_halt_recommended deve ser bool")
        if not isinstance(self.reconciliation_confidence, str):
            raise TypeError("reconciliation_confidence deve ser string")
        if self.reconciliation_confidence not in _VALID_CONFIDENCE:
            raise ValueError(
                f"reconciliation_confidence inválido: "
                f"{self.reconciliation_confidence!r}; aceitos: "
                f"{list(_VALID_CONFIDENCE)}"
            )
        if not isinstance(self.reason, str):
            raise TypeError("reason deve ser string")
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )

    def to_dict(self) -> dict:
        """Serialização JSON-friendly. Não inclui secrets."""
        return {
            "manual_review_required": self.manual_review_required,
            "safety_halt_recommended": self.safety_halt_recommended,
            "reconciliation_confidence": self.reconciliation_confidence,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Helpers duck-typed
# ---------------------------------------------------------------------------

def safety_flags_from_dict(data: Mapping[str, Any]) -> SafetyFlags:
    """
    Constrói SafetyFlags a partir de um Mapping.

    Aceita chaves ausentes (usa defaults). Aceita extras (ignora).
    NÃO valida que `data` representa execução real — é puramente
    estrutural. Não chama rede.
    """
    if not isinstance(data, Mapping):
        raise TypeError(
            f"safety_flags_from_dict requer Mapping; "
            f"recebido {type(data).__name__}"
        )
    confidence = data.get("reconciliation_confidence", "canonical")
    if confidence is None:
        confidence = "canonical"
    return SafetyFlags(
        manual_review_required=bool(data.get("manual_review_required", False)),
        safety_halt_recommended=bool(data.get("safety_halt_recommended", False)),
        reconciliation_confidence=str(confidence),
        reason=str(data.get("reason", "") or ""),
        metadata=dict(data.get("metadata", {}) or {}),
    )


def safety_flags_from_result_like(obj: Any) -> SafetyFlags:
    """
    Constrói SafetyFlags a partir de QUALQUER objeto duck-typed.

    Aceita SimpleNamespace, dataclass, ou qualquer instância com os
    atributos esperados. Atributos ausentes ⇒ defaults conservadores.

    NÃO importa DemoExecutionResult. Não chama rede. Não levanta se o
    objeto for incompleto — usa defaults.
    """
    if obj is None:
        return SafetyFlags()
    confidence = getattr(obj, "reconciliation_confidence", "canonical")
    if confidence is None:
        confidence = "canonical"
    raw_metadata = getattr(obj, "metadata", None) or {}
    if not isinstance(raw_metadata, Mapping):
        raw_metadata = {}
    return SafetyFlags(
        manual_review_required=bool(
            getattr(obj, "manual_review_required", False)
        ),
        safety_halt_recommended=bool(
            getattr(obj, "safety_halt_recommended", False)
        ),
        reconciliation_confidence=str(confidence),
        reason=str(getattr(obj, "reason", "") or ""),
        metadata=dict(raw_metadata),
    )
