"""
AIDecisionSupport (FASE 32)
============================
Motor de fusao do parecer da IA com o perfil operacional.

⚠️  REGRA CENTRAL: a IA so REDUZ permissao. Se RiskEngine reprovou,
    IA nao aprova. Se gate reprovou, IA nao aprova. Veto da IA pode
    bloquear o ciclo ou exigir manual review conforme perfil + gate.
    A IA NUNCA aumenta permissao operacional.

Gate proprio (independente; nenhum gate implica outro):
    DEMO_ALLOW_AI_MANUAL_REVIEW=true
        Permite que o parecer manual_review da IA marque a sessao
        como manual_review_required. Sem o gate (e com perfil
        permitindo veto), o parecer bloqueante degrada para bloqueio
        conservador do ciclo (sem ordem), nunca para escalacao.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AIAdvisorProtocol,
)

ENV_AI_MANUAL_REVIEW = "DEMO_ALLOW_AI_MANUAL_REVIEW"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class AIDecisionOutcome:
    """Resultado da consulta consultiva a IA para UM ciclo."""

    ai_enabled: bool
    advice: Optional[AIAdvice] = None
    cycle_blocked: bool = False
    manual_review_required: bool = False
    not_used_reason: Optional[str] = None   # FASE 36 Bloco C

    def to_report_fields(self) -> dict:
        """Campos exigidos no report (spec FASE 32/36)."""
        return {
            "ai_enabled": bool(self.ai_enabled),
            "ai_status": (
                self.advice.status.value if self.advice else None
            ),
            "ai_reason": self.advice.reason if self.advice else None,
            "ai_warnings": (
                list(self.advice.warnings) if self.advice else []
            ),
            "ai_manual_review_required": bool(
                self.manual_review_required
            ),
            "ai_not_used_reason": self.not_used_reason,
        }


class AIDecisionSupport:
    """Consulta o advisor e funde o parecer com as permissoes do perfil.

    Args:
        advisor: implementacao de AIAdvisorProtocol (Mock em testes).
        telemetry_emit: callable(event_type, **snapshot) opcional —
            nunca propaga excecao (espelha _emit do runner).
    """

    def __init__(
        self,
        *,
        advisor: AIAdvisorProtocol,
        telemetry_emit: Optional[Callable[..., None]] = None,
    ) -> None:
        if not hasattr(advisor, "evaluate_trade_context"):
            raise TypeError(
                "advisor deve implementar AIAdvisorProtocol"
            )
        self._advisor = advisor
        self._emit = telemetry_emit or (lambda *_a, **_k: None)

    def _safe_emit(self, event_type: str, **snapshot: Any) -> None:
        try:
            self._emit(event_type, **snapshot)
        except Exception:  # noqa: BLE001
            pass

    def evaluate_cycle(
        self,
        *,
        profile,
        ai_context: Mapping[str, Any],
        cycle_idx: int,
    ) -> AIDecisionOutcome:
        """Avalia o ciclo com a IA respeitando o perfil.

        - perfil sem allow_ai_assistance -> IA nem eh consultada.
        - status neutral/caution -> ciclo segue (warnings registrados).
        - status veto/manual_review -> REDUZ permissao:
            * perfil sem allow_ai_veto: parecer vira warning (consultivo).
            * perfil com allow_ai_veto:
                - manual_review + gate ENV -> manual_review_required.
                - caso contrario -> cycle_blocked (sem ordem no ciclo).
        """
        if not getattr(profile, "allow_ai_assistance", False):
            return AIDecisionOutcome(
                ai_enabled=False,
                not_used_reason="ai_disabled_by_profile",
            )

        self._safe_emit(
            "ai_context_built", cycle_idx=cycle_idx,
            schema=str(ai_context.get("schema", "")),
        )
        try:
            advice = self._advisor.evaluate_trade_context(ai_context)
        except Exception as e:  # noqa: BLE001
            # Falha da IA NUNCA derruba o pipeline: registra e segue
            # sem parecer (sem reducao nem aumento de permissao).
            self._safe_emit(
                "ai_advice_generated", cycle_idx=cycle_idx,
                error=type(e).__name__,
            )
            return AIDecisionOutcome(ai_enabled=True, advice=None)

        if not isinstance(advice, AIAdvice):
            self._safe_emit(
                "ai_advice_generated", cycle_idx=cycle_idx,
                error="invalid_advice_type",
            )
            return AIDecisionOutcome(ai_enabled=True, advice=None)

        self._safe_emit(
            "ai_advice_generated", cycle_idx=cycle_idx,
            status=advice.status.value,
            confidence=float(advice.confidence),
            suggested_action=advice.suggested_action.value,
            warnings_count=len(advice.warnings),
        )

        if not advice.is_blocking:
            return AIDecisionOutcome(ai_enabled=True, advice=advice)

        # Parecer bloqueante (veto | manual_review): reducao de permissao.
        if not getattr(profile, "allow_ai_veto", False):
            # Perfil nao permite veto -> parecer fica consultivo.
            return AIDecisionOutcome(ai_enabled=True, advice=advice)

        if advice.status is AIAdviceStatus.VETO:
            self._safe_emit(
                "ai_veto_triggered", cycle_idx=cycle_idx,
                reason=advice.reason[:160],
            )
            return AIDecisionOutcome(
                ai_enabled=True, advice=advice, cycle_blocked=True,
            )

        # MANUAL_REVIEW: exige gate ENV proprio (independente).
        if _env_truthy(ENV_AI_MANUAL_REVIEW):
            self._safe_emit(
                "ai_manual_review_requested", cycle_idx=cycle_idx,
                reason=advice.reason[:160],
            )
            return AIDecisionOutcome(
                ai_enabled=True, advice=advice,
                cycle_blocked=True, manual_review_required=True,
            )
        # Gate ausente: degrade conservador para bloqueio do ciclo.
        self._safe_emit(
            "ai_veto_triggered", cycle_idx=cycle_idx,
            reason="manual_review requested but gate off; "
                   "conservative cycle block",
        )
        return AIDecisionOutcome(
            ai_enabled=True, advice=advice, cycle_blocked=True,
        )


__all__ = [
    "AIDecisionOutcome",
    "AIDecisionSupport",
    "ENV_AI_MANUAL_REVIEW",
]
