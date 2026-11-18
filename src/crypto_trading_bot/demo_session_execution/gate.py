"""
Demo Session Execution Gate — triple-locked single-shot (FASE 20)
=====================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - DOES NOT EXECUTE BY DEFAULT. dry_run=True default. Execução real
      exige confirm_demo_session=True + operator_token + dry_run=False
      + ModeGuard.assert_demo_execution_allowed(True) + provider OPT_IN
      confirmado + SafetyStateMachine em NORMAL + RiskEngine aprovação
      fresca. Qualquer falha levanta DemoSessionRejected ANTES de tocar
      o executor.
    - Provider-agnostic. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, httpx, requests, SessionRunner.
    - Executor é INJETADO via DemoExecutorProtocol duck-typed.
    - SINGLE-SHOT: nenhum for/while. Uma chamada = no máximo uma
      tentativa ao executor.
    - SafetyStateMachine NÃO é resetada automaticamente. Operador é
      responsável por acknowledge → resolve → reset externamente.
    - Audit estruturado sanitizado. Sem secrets em logs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType, SimpleNamespace
from typing import Any, Callable, Optional, Protocol

from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.demo_session_execution.outcome import (
    DemoSessionOutcome,
    DemoSessionRejected,
    RecommendedNextAction,
)
from crypto_trading_bot.demo_session_execution.plan import (
    BlueprintSide,
    DemoSessionPlan,
)
from crypto_trading_bot.execution.provider_registry import (
    ProviderRegistry,
)
from crypto_trading_bot.logging_system.logger import (
    get_audit_logger,
    get_logger,
)
from crypto_trading_bot.operational_safety.safety_state import SafetyState
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)


_DEMO_PROVIDER_ID = "bybit_demo_linear"

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Protocol injetado (duck-typed; sem importar BybitDemoExecutor)
# ---------------------------------------------------------------------------

class DemoExecutorProtocol(Protocol):
    """
    Interface mínima esperada do executor demo.

    Não importa BybitDemoExecutor. Qualquer objeto com método compatível
    pode ser passado (fake, mock, executor real). A FASE 15 já define
    BybitDemoExecutor.execute com essa assinatura.
    """

    def execute(
        self,
        risk_result: RiskResult,
        dry_run: bool = True,
    ) -> Any:
        """Retorna objeto duck-typed com atributos compatíveis com
        DemoExecutionResult (success, operation, reason, dry_run,
        manual_review_required, safety_halt_recommended,
        reconciliation_confidence, trade)."""
        ...


# ---------------------------------------------------------------------------
# Sanitização (mesma defesa em profundidade das FASEs 16/18/19)
# ---------------------------------------------------------------------------

_SUSPICIOUS_LOG_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def _sanitize_token(token: str) -> str:
    if not isinstance(token, str) or not token.strip():
        return "<empty>"
    lower = token.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        return "<redacted_suspicious_token>"
    return token[:8] + ("..." if len(token) > 8 else "")


def _sanitize_notes(notes: str) -> str:
    if not isinstance(notes, str):
        return ""
    truncated = notes[:200]
    lower = truncated.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        return "<redacted_suspicious_notes>"
    return truncated


def _sanitize_reason(text: str) -> str:
    """Mesma política — truncar e redactar suspeitos."""
    return _sanitize_notes(text)


# ---------------------------------------------------------------------------
# Conversão SignalBlueprint → TradingSignal (para RiskEngine)
# ---------------------------------------------------------------------------

def _blueprint_to_trading_signal(plan: DemoSessionPlan) -> TradingSignal:
    """Constrói TradingSignal a partir do blueprint. Sem hardcode de
    sizing/leverage — vem do blueprint."""
    bp = plan.blueprint
    side = OrderSide.BUY if bp.side is BlueprintSide.BUY else OrderSide.SELL
    return TradingSignal(
        symbol=bp.symbol,
        side=side,
        entry_price=float(bp.entry_price),
        stop_loss_price=float(bp.stop_loss),
        position_size_usd=float(bp.position_size_usd),
        strategy_name=bp.strategy_name,
        take_profit_price=float(bp.take_profit),
        leverage=float(bp.leverage),
    )


# ---------------------------------------------------------------------------
# Helpers para extrair atributos de result duck-typed (FASE 15 DemoExecutionResult)
# ---------------------------------------------------------------------------

def _result_attr(result: Any, name: str, default: Any) -> Any:
    return getattr(result, name, default)


def _result_to_snapshot(result: Any) -> dict:
    """Snapshot sanitizado do DemoExecutionResult duck-typed.

    Se o result expõe to_dict (FASE 15), usa. Senão, monta defensivamente
    extraindo campos conhecidos."""
    if hasattr(result, "to_dict") and callable(result.to_dict):
        try:
            d = dict(result.to_dict())
            # Sanitiza string reason
            if "reason" in d and isinstance(d["reason"], str):
                d["reason"] = _sanitize_reason(d["reason"])
            return d
        except Exception:
            pass
    return {
        "success": bool(_result_attr(result, "success", False)),
        "operation": str(_result_attr(result, "operation", "")),
        "reason": _sanitize_reason(str(_result_attr(result, "reason", ""))),
        "dry_run": bool(_result_attr(result, "dry_run", False)),
        "manual_review_required": bool(
            _result_attr(result, "manual_review_required", False)
        ),
        "safety_halt_recommended": bool(
            _result_attr(result, "safety_halt_recommended", False)
        ),
        "reconciliation_confidence": str(
            _result_attr(result, "reconciliation_confidence", "canonical")
        ),
    }


# ---------------------------------------------------------------------------
# execute_demo_session_gated — função imperativa SINGLE-SHOT
# ---------------------------------------------------------------------------

def execute_demo_session_gated(
    plan: DemoSessionPlan,
    *,
    risk_engine: RiskEngine,
    demo_executor: DemoExecutorProtocol,
    safety_machine: SafetyStateMachine,
    mode_guard: ModeGuard,
    provider_registry: ProviderRegistry,
    operator_token: str,
    confirm_demo_session: bool = False,
    dry_run: bool = True,
    notes: str = "",
    post_session_check_fn: Optional[Callable[[], Any]] = None,
    now: Optional[datetime] = None,
) -> DemoSessionOutcome:
    """
    Gate single-shot para sessão demo curta.

    NUNCA tem loop. UMA chamada = no máximo UMA tentativa do executor.

    Triple-lock humano + invariantes de plan:
        1. confirm_demo_session=True (kwarg explícito)
        2. operator_token string não-vazia
        3. dry_run=True por default; False exige aprovação consciente
        4. plan.readiness_report.is_ready_for_gated_demo=True
        5. plan dentro da janela de freshness
        6. SafetyStateMachine.state == NORMAL
        7. ModeGuard.assert_demo_execution_allowed(confirm_demo_execution=True)
        8. ProviderRegistry.assert_usable("bybit_demo_linear", confirm_provider=True)
        9. RiskEngine.validate_signal(...) aprovação FRESCA
       10. blueprint SL/TP obrigatórios (já validado em SignalBlueprint)

    Pós-submit (sempre executado se o executor foi chamado):
        a. safety_machine.from_safety_flags(result) — duck-typed
        b. post_session_check_fn() opcional (read-only) — se fornecido
        c. produz DemoSessionOutcome com RecommendedNextAction

    Args:
        plan: produzido por build_demo_session_plan.
        risk_engine: RiskEngine real ou fake; .validate_signal exigido.
        demo_executor: implementa DemoExecutorProtocol; injetado.
        safety_machine: SafetyStateMachine; estado consultado e alimentado.
        mode_guard: ModeGuard; assert_demo_execution_allowed chamado.
        provider_registry: ProviderRegistry; .assert_usable chamado.
        operator_token: identificação do operador (sanitizada em audit).
        confirm_demo_session: DEVE ser True para execução. Default False.
        dry_run: True (default) simula; False exige todos os gates.
        notes: notas operacionais (sanitizadas em audit).
        post_session_check_fn: callable opcional executado APÓS o submit.
        now: relógio injetável.

    Returns:
        DemoSessionOutcome frozen.

    Raises:
        DemoSessionRejected: qualquer gate quebrado antes de chamar
                             o executor. Nenhuma chamada de rede ocorre.
    """
    safe_token = _sanitize_token(operator_token)
    safe_notes = _sanitize_notes(notes)

    # Gate 1: confirm_demo_session
    if confirm_demo_session is not True:
        _audit_rejected(plan, safe_token, "missing_confirm")
        raise DemoSessionRejected(
            "confirm_demo_session deve ser True (kwarg explícito)"
        )

    # Gate 2: operator_token
    if not isinstance(operator_token, str) or not operator_token.strip():
        _audit_rejected(plan, "<empty>", "missing_operator_token")
        raise DemoSessionRejected("operator_token deve ser string não-vazia")

    # Gate 3: dry_run tipo
    if not isinstance(dry_run, bool):
        _audit_rejected(plan, safe_token, "invalid_dry_run_type")
        raise DemoSessionRejected("dry_run deve ser bool")

    # Gate 4: plan tipo
    if not isinstance(plan, DemoSessionPlan):
        # Nem registramos plan.plan_id (não existe).
        raise DemoSessionRejected(
            "plan deve ser DemoSessionPlan; "
            f"recebido {type(plan).__name__}"
        )

    # Gate 5: readiness do plan (defesa contra mutação maliciosa do plan)
    report = plan.readiness_report
    if not report.is_ready_for_gated_demo:
        _audit_rejected(plan, safe_token, "readiness_not_ready")
        raise DemoSessionRejected(
            "plan.readiness_report.is_ready_for_gated_demo=False"
        )
    if report.total_blocks != 0:
        _audit_rejected(plan, safe_token, "readiness_has_blocks")
        raise DemoSessionRejected(
            f"plan.readiness_report.total_blocks={report.total_blocks}"
        )
    if report.provider_id != _DEMO_PROVIDER_ID:
        _audit_rejected(plan, safe_token, "wrong_provider")
        raise DemoSessionRejected(
            f"readiness provider_id={report.provider_id!r} "
            f"(esperado {_DEMO_PROVIDER_ID!r})"
        )

    # Gate 6: freshness do plan
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    created = plan.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age = (clock - created).total_seconds()
    if age < 0:
        _audit_rejected(plan, safe_token, "plan_future_clock")
        raise DemoSessionRejected(
            "plan.created_at no futuro — relógio inconsistente"
        )
    if age > plan.readiness_max_age_seconds:
        _audit_rejected(plan, safe_token, "plan_stale")
        raise DemoSessionRejected(
            f"plan stale: idade={age:.0f}s > limite="
            f"{plan.readiness_max_age_seconds}s"
        )

    # Gate 7: SafetyStateMachine NORMAL
    if safety_machine.state is not SafetyState.NORMAL:
        _audit_rejected(plan, safe_token, "safety_not_normal")
        raise DemoSessionRejected(
            f"SafetyStateMachine.state={safety_machine.state.value} "
            "(esperado NORMAL). Operador deve completar ack→resolve→reset."
        )
    if safety_machine.requires_operator_ack:
        _audit_rejected(plan, safe_token, "safety_requires_ack")
        raise DemoSessionRejected(
            "SafetyStateMachine.requires_operator_ack=True"
        )

    # Gate 8: ModeGuard triple-lock
    try:
        mode_guard.assert_demo_execution_allowed(
            confirm_demo_execution=True,
            context="execute_demo_session_gated",
        )
    except Exception as e:
        _audit_rejected(plan, safe_token, "mode_guard_blocked")
        raise DemoSessionRejected(
            f"ModeGuard bloqueou: {type(e).__name__}"
        ) from e

    # Gate 9: ProviderRegistry (read-only consulta + assert_usable)
    try:
        provider_registry.assert_usable(
            _DEMO_PROVIDER_ID, confirm_provider=True
        )
    except Exception as e:
        _audit_rejected(plan, safe_token, "provider_blocked")
        raise DemoSessionRejected(
            f"ProviderRegistry bloqueou: {type(e).__name__}"
        ) from e

    # Gate 10: RiskEngine fresco
    trading_signal = _blueprint_to_trading_signal(plan)
    risk_result = risk_engine.validate_signal(trading_signal)
    if not getattr(risk_result, "approved", False):
        reason = _sanitize_reason(str(getattr(risk_result, "reason", "")))
        _audit_rejected(plan, safe_token, f"risk_blocked:{reason}")
        raise DemoSessionRejected(
            f"RiskEngine bloqueou: {reason}"
        )

    # ===== TODOS OS GATES PASSARAM — chamada SINGLE-SHOT ao executor =====
    _audit.info(
        "DEMO_SESSION_EXECUTE_BEGIN | "
        f"plan_id={plan.plan_id} | "
        f"operator_token={safe_token} | "
        f"dry_run={dry_run} | "
        f"symbol={plan.blueprint.symbol} | "
        f"side={plan.blueprint.side.value}"
    )
    result = demo_executor.execute(risk_result=risk_result, dry_run=dry_run)

    # Alimenta safety_machine — duck-typed; FASE 16
    try:
        safety_machine.from_safety_flags(result)
    except Exception as e:
        # Não interrompe — apenas registra. Outcome refletirá ambiguidade.
        _logger.warning(
            f"safety_machine.from_safety_flags falhou: {type(e).__name__}"
        )

    # Post-session-check (opcional, read-only por contrato)
    post_check_summary: Optional[dict] = None
    if post_session_check_fn is not None:
        try:
            post = post_session_check_fn()
            post_check_summary = _result_to_snapshot(post)
        except Exception as e:
            post_check_summary = {
                "success": False,
                "reason": f"post_check_failed:{type(e).__name__}",
            }

    # Constrói outcome
    snapshot = _result_to_snapshot(result)
    confidence = str(
        _result_attr(result, "reconciliation_confidence", "canonical")
    )
    manual_required_raw = bool(
        _result_attr(result, "manual_review_required", False)
    )
    halt_recommended = bool(
        _result_attr(result, "safety_halt_recommended", False)
    )
    success = bool(_result_attr(result, "success", False))

    # require_manual_ack do profile + triangulated → manual_review
    requires_manual_review = bool(
        manual_required_raw
        or (
            confidence == "triangulated"
            and plan.profile.require_manual_ack_on_triangulation
        )
    )

    # Post-check com problemas reforça manual_review/halt — pode invalidar
    # canonical fill se reportar resíduo/erro.
    if post_check_summary is not None:
        if not post_check_summary.get("success", True):
            requires_manual_review = True
        if post_check_summary.get("manual_review_required"):
            requires_manual_review = True
        if post_check_summary.get("safety_halt_recommended"):
            halt_recommended = True

    # Triangulated NUNCA é canonical fill. Manual review ou halt também
    # desqualificam canonical. Calculado APÓS post-check para refletir
    # achados de resíduo/erro do safe_check_only.
    is_canonical = bool(
        success
        and not dry_run
        and confidence == "canonical"
        and not requires_manual_review
        and not halt_recommended
    )

    # Recommended action
    if halt_recommended or confidence == "none":
        next_action = RecommendedNextAction.SAFETY_HALT_ACK_NEEDED
    elif requires_manual_review:
        next_action = RecommendedNextAction.MANUAL_REVIEW_REQUIRED
    elif is_canonical:
        next_action = RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
    else:
        next_action = RecommendedNextAction.RETURN_TO_PAPER

    outcome_reason = _build_outcome_reason(
        dry_run=dry_run,
        success=success,
        confidence=confidence,
        requires_manual_review=requires_manual_review,
        halt_recommended=halt_recommended,
        is_canonical=is_canonical,
    )

    outcome = DemoSessionOutcome(
        plan_id=plan.plan_id,
        dry_run=dry_run,
        provider_id=_DEMO_PROVIDER_ID,
        symbol=plan.blueprint.symbol,
        side=plan.blueprint.side.value,
        executor_called=True,
        executor_success=success,
        is_filled_canonical=is_canonical,
        requires_manual_review=requires_manual_review,
        safety_halt_recommended=halt_recommended,
        final_safety_state=safety_machine.state.value,
        recommended_next_action=next_action,
        outcome_reason=outcome_reason,
        executor_result_snapshot=MappingProxyType(snapshot),
        post_session_check_summary=(
            MappingProxyType(post_check_summary)
            if post_check_summary is not None
            else None
        ),
        operator_token_sanitized=safe_token,
        notes=safe_notes,
        evaluated_at=clock,
    )

    _audit.info(
        "DEMO_SESSION_EXECUTED | "
        f"plan_id={plan.plan_id} | "
        f"operator_token={safe_token} | "
        f"dry_run={dry_run} | "
        f"executor_success={success} | "
        f"is_canonical={is_canonical} | "
        f"manual_review={requires_manual_review} | "
        f"halt={halt_recommended} | "
        f"final_safety={safety_machine.state.value} | "
        f"next={next_action.value}"
    )
    return outcome


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _build_outcome_reason(
    *,
    dry_run: bool,
    success: bool,
    confidence: str,
    requires_manual_review: bool,
    halt_recommended: bool,
    is_canonical: bool,
) -> str:
    if halt_recommended:
        return "SAFETY_HALT_RECOMMENDED"
    if confidence == "none":
        return "RECONCILIATION_FAILED"
    if confidence == "triangulated":
        return "FILLED_BY_TRIANGULATION_REQUIRES_REVIEW"
    if requires_manual_review:
        return "MANUAL_REVIEW_REQUIRED"
    if dry_run and success:
        return "DRY_RUN_SUCCESS"
    if is_canonical:
        return "FILLED_CANONICAL"
    if not success:
        return "EXECUTOR_FAILURE"
    return "OUTCOME_AMBIGUOUS"


def _audit_rejected(
    plan: Any, safe_token: str, reason_code: str,
) -> None:
    """Linha estruturada de rejeição. Não vaza secrets."""
    plan_id = getattr(plan, "plan_id", "<unknown>")
    _audit.info(
        "DEMO_SESSION_GATE_REJECTED | "
        f"plan_id={plan_id} | "
        f"operator_token={safe_token} | "
        f"reason='{reason_code}'"
    )
