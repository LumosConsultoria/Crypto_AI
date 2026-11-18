"""
MockAIAdvisor (FASE 32)
========================
Advisor de IA DETERMINISTICO para testes e operacao offline.

⚠️  ZERO rede, ZERO LLM, ZERO secret. Implementa AIAdvisorProtocol
    com regras simples e auditaveis. Consultivo: nunca aumenta
    permissao; apenas neutral/caution/veto/manual_review.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AISuggestedAction,
)
from crypto_trading_bot.ai_assistant.risk_commentary import (
    build_risk_commentary,
)


class MockAIAdvisor:
    """Advisor deterministico.

    Regras (em ordem; primeira que casar define o status):
        1. forced_status (teste) -> usa direto.
        2. RiskEngine reprovou -> caution (IA NUNCA aprova o que o
           risco reprovou; comentario explica).
        3. Prediction context stale -> caution + warning.
        4. Prediction risk_flags presentes -> caution (advisory).
        5. RSI extremo (>=80 ou <=20) -> caution.
        6. Default -> neutral / proceed.

    forced_status/forced_action permitem testes exercitarem veto e
    manual_review sem heuristica.
    """

    def __init__(
        self,
        *,
        forced_status: Optional[AIAdviceStatus] = None,
        forced_action: Optional[AISuggestedAction] = None,
        forced_reason: str = "",
    ) -> None:
        self._forced_status = forced_status
        self._forced_action = forced_action
        self._forced_reason = forced_reason
        self.calls = 0
        self.last_context: Optional[Mapping[str, Any]] = None

    def evaluate_trade_context(
        self, context: Mapping[str, Any],
    ) -> AIAdvice:
        self.calls += 1
        self.last_context = context

        if self._forced_status is not None:
            return AIAdvice(
                status=self._forced_status,
                confidence=1.0,
                reason=self._forced_reason or "forced by test",
                suggested_action=(
                    self._forced_action or AISuggestedAction.MANUAL_REVIEW
                    if self._forced_status in (
                        AIAdviceStatus.VETO, AIAdviceStatus.MANUAL_REVIEW,
                    )
                    else self._forced_action or AISuggestedAction.PROCEED
                ),
            )

        signal = dict(context.get("signal_snapshot") or {})
        risk = dict(context.get("risk_summary") or {})
        prediction = context.get("prediction_context") or None

        warnings = tuple(build_risk_commentary(
            risk_summary=risk, signal_snapshot=signal,
            prediction_context=prediction,
        ))

        # 2. Risco reprovado -> IA nao aprova (caution + wait).
        if risk and not risk.get("approved", True):
            return AIAdvice(
                status=AIAdviceStatus.CAUTION,
                confidence=0.9,
                reason="RiskEngine rejected signal; AI defers to risk",
                warnings=warnings,
                suggested_action=AISuggestedAction.WAIT,
            )
        # 3. Prediction stale.
        if prediction and prediction.get("stale"):
            return AIAdvice(
                status=AIAdviceStatus.CAUTION,
                confidence=0.6,
                reason="prediction context is stale",
                warnings=warnings + (
                    "prediction_context_stale",
                ),
                suggested_action=AISuggestedAction.WAIT,
            )
        # 4. Prediction risk flags.
        if prediction and prediction.get("risk_flags"):
            return AIAdvice(
                status=AIAdviceStatus.CAUTION,
                confidence=0.7,
                reason=(
                    "prediction markets flag macro/event risk: "
                    + ", ".join(
                        list(prediction.get("risk_flags") or [])[:3]
                    )
                ),
                warnings=warnings,
                suggested_action=AISuggestedAction.WAIT,
            )
        # 5. RSI extremo.
        rsi = signal.get("rsi_value")
        if isinstance(rsi, (int, float)) and (rsi >= 80 or rsi <= 20):
            return AIAdvice(
                status=AIAdviceStatus.CAUTION,
                confidence=0.6,
                reason=f"extreme RSI {rsi}",
                warnings=warnings,
                suggested_action=AISuggestedAction.WAIT,
            )
        # 6. Default neutro.
        return AIAdvice(
            status=AIAdviceStatus.NEUTRAL,
            confidence=0.5,
            reason="no anomaly detected",
            warnings=warnings,
            suggested_action=AISuggestedAction.PROCEED,
        )


__all__ = ["MockAIAdvisor"]
