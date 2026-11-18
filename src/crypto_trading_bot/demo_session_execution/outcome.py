"""
DemoSessionOutcome + RecommendedNextAction + DemoSessionRejected (FASE 20)
============================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Frozen e JSON-serializável. SEM secrets em nenhum campo
      (validado por sanitização nas FASEs anteriores e nos testes).
    - DOES NOT EXECUTE. Outcome é apenas estrutura de relatório.
    - Provider-agnostic. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, httpx, requests, SessionRunner.
    - DemoSessionRejected é levantado pelo gate (gate.py) — não aqui.

Default seguro: recommended_next_action=RETURN_TO_PAPER em qualquer
outcome, exceto canonical clean fill (→ READY_FOR_NEXT_DEMO_SESSION).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class DemoSessionRejected(RuntimeError):
    """
    execute_demo_session_gated rejeitou execução.

    Causas: confirm_demo_session=False, operator_token vazio,
    SafetyStateMachine ≠ NORMAL, ModeGuard bloqueia, provider unusable,
    RiskEngine bloqueia, plan stale.
    """


# ---------------------------------------------------------------------------
# RecommendedNextAction
# ---------------------------------------------------------------------------

class RecommendedNextAction(str, Enum):
    """
    Próxima ação recomendada após DemoSessionOutcome. Valores são
    contrato estável — não renomear.

    Mapeamento:
        RETURN_TO_PAPER             — default seguro. Operador volta ao
                                      paper trading. Aplicável em
                                      dry-run, em outcomes ambíguos sem
                                      gravidade explícita, etc.
        MANUAL_REVIEW_REQUIRED      — triangulação ou flags manuais.
                                      Operador deve revisar antes de
                                      qualquer próxima ação.
        SAFETY_HALT_ACK_NEEDED      — safety_halt_recommended=True ou
                                      reconciliation_confidence="none".
                                      Requer acknowledge formal.
        READY_FOR_NEXT_DEMO_SESSION — canonical fill, safety NORMAL, sem
                                      flags pendentes, post-check limpo.

    FASE 22 Final — criterio explicito de CANONICAL CLEAN SESSION
    (READY_FOR_NEXT_DEMO_SESSION):
        1. executor_result.success == True
        2. dry_run == False (caminho real)
        3. reconciliation_confidence == "canonical"
        4. requires_manual_review == False
        5. safety_halt_recommended == False
        6. SL/TP server-side anexados quando signal exigiu — defesa em
           profundidade da FASE 22.4 marca manual_review_required=True
           se snapshot da posicao retornar SL/TP ausentes/zero, o que
           automaticamente desclassifica canonical.
        7. post_session_check (quando fornecido) retornou success=True
           e nao reportou positions/orders residuais nem api_errors.

    Qualquer falha em (1)-(7) -> MANUAL_REVIEW_REQUIRED ou
    SAFETY_HALT_ACK_NEEDED conforme a categoria.
    """
    RETURN_TO_PAPER = "return_to_paper"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SAFETY_HALT_ACK_NEEDED = "safety_halt_ack_needed"
    READY_FOR_NEXT_DEMO_SESSION = "ready_for_next_demo_session"


# ---------------------------------------------------------------------------
# DemoSessionOutcome
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DemoSessionOutcome:
    """
    Resultado consolidado de uma chamada a execute_demo_session_gated.

    Frozen. JSON-serializável via to_dict(). SEM secrets — todos os
    campos são derivados de DemoExecutionResult (já sanitizado pela
    FASE 15) + estado de safety + post-check.

    Atributos:
        plan_id: correlation id (sanitizado).
        dry_run: True se o gate rodou em modo simulação.
        provider_id: sempre "bybit_demo_linear" nesta fase.
        symbol: símbolo declarado no blueprint.
        side: lado do trade ("buy"/"sell").
        executor_called: True se executor.execute foi chamado;
                         False se gate rejeitou antes.
        executor_success: True se DemoExecutionResult.success=True.
        is_filled_canonical: True APENAS se reconciliation_confidence=
                             "canonical". Triangulated NUNCA é canonical.
        requires_manual_review: True se manual_review_required ou
                                triangulated com require_manual_ack.
        safety_halt_recommended: True se executor sinalizou halt.
        final_safety_state: SafetyState resultante (string).
        recommended_next_action: enum RecommendedNextAction.
        outcome_reason: motivo humano-legível sanitizado.
        executor_result_snapshot: dict sanitizado de DemoExecutionResult
                                  (sem secrets — to_dict da FASE 15).
        post_session_check_summary: snapshot do post-check (opcional).
        operator_token_sanitized: token truncado a 8 chars + "...".
        notes: notas operacionais sanitizadas (truncadas 200 chars).
        evaluated_at: tz-aware UTC.
    """
    plan_id: str
    dry_run: bool
    provider_id: str
    symbol: str
    side: str
    executor_called: bool
    executor_success: bool
    is_filled_canonical: bool
    requires_manual_review: bool
    safety_halt_recommended: bool
    final_safety_state: str
    recommended_next_action: RecommendedNextAction
    outcome_reason: str
    executor_result_snapshot: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    post_session_check_summary: Optional[Mapping[str, Any]] = None
    operator_token_sanitized: str = "<empty>"
    notes: str = ""
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValueError("plan_id deve ser string não-vazia")
        if not isinstance(self.dry_run, bool):
            raise TypeError("dry_run deve ser bool")
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id deve ser string não-vazia")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol deve ser string não-vazia")
        if not isinstance(self.side, str) or self.side not in ("buy", "sell"):
            raise ValueError(f"side deve ser 'buy'/'sell'; recebido {self.side!r}")
        if not isinstance(self.recommended_next_action, RecommendedNextAction):
            raise TypeError(
                "recommended_next_action deve ser RecommendedNextAction; "
                f"recebido {type(self.recommended_next_action).__name__}"
            )
        # Consistência: canonical fill NÃO pode coexistir com triangulated
        # ou manual_review (defesa em profundidade).
        if self.is_filled_canonical and self.requires_manual_review:
            raise ValueError(
                "DemoSessionOutcome inconsistente: is_filled_canonical=True "
                "com requires_manual_review=True"
            )
        if self.is_filled_canonical and self.safety_halt_recommended:
            raise ValueError(
                "DemoSessionOutcome inconsistente: is_filled_canonical=True "
                "com safety_halt_recommended=True"
            )
        # Recommended action consistente
        if self.safety_halt_recommended and (
            self.recommended_next_action
            is RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
        ):
            raise ValueError(
                "DemoSessionOutcome inconsistente: safety_halt_recommended=True "
                "não pode recomendar READY_FOR_NEXT_DEMO_SESSION"
            )
        if self.requires_manual_review and (
            self.recommended_next_action
            is RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
        ):
            raise ValueError(
                "DemoSessionOutcome inconsistente: requires_manual_review=True "
                "não pode recomendar READY_FOR_NEXT_DEMO_SESSION"
            )
        # tz-aware
        if self.evaluated_at.tzinfo is None:
            object.__setattr__(
                self,
                "evaluated_at",
                self.evaluated_at.replace(tzinfo=timezone.utc),
            )
        # executor_result_snapshot imutável
        if not isinstance(self.executor_result_snapshot, MappingProxyType):
            object.__setattr__(
                self,
                "executor_result_snapshot",
                MappingProxyType(dict(self.executor_result_snapshot)),
            )
        # post_session_check_summary imutável
        if (
            self.post_session_check_summary is not None
            and not isinstance(self.post_session_check_summary, MappingProxyType)
        ):
            object.__setattr__(
                self,
                "post_session_check_summary",
                MappingProxyType(dict(self.post_session_check_summary)),
            )

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "dry_run": self.dry_run,
            "provider_id": self.provider_id,
            "symbol": self.symbol,
            "side": self.side,
            "executor_called": self.executor_called,
            "executor_success": self.executor_success,
            "is_filled_canonical": self.is_filled_canonical,
            "requires_manual_review": self.requires_manual_review,
            "safety_halt_recommended": self.safety_halt_recommended,
            "final_safety_state": self.final_safety_state,
            "recommended_next_action": self.recommended_next_action.value,
            "outcome_reason": self.outcome_reason,
            "executor_result_snapshot": dict(self.executor_result_snapshot),
            "post_session_check_summary": (
                dict(self.post_session_check_summary)
                if self.post_session_check_summary is not None
                else None
            ),
            "operator_token_sanitized": self.operator_token_sanitized,
            "notes": self.notes,
            "evaluated_at": self.evaluated_at.isoformat(),
        }
