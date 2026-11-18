"""
ReadinessRules (FASE 35)
=========================
Regras e thresholds do readiness supervisionado.

⚠️  CONSULTIVO: o verdict NUNCA habilita live/mainnet por si. Ele
    consolida evidencias para decisao HUMANA supervisionada.
⚠️  Funcoes puras, offline, deterministicas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


# Thresholds minimos (documentados; editaveis)
MIN_TOTAL_SESSIONS = 2
MAX_SAFETY_EVENTS = 0
MAX_API_FAILURES_TOTAL = 3
MAX_UNRESOLVED_MANUAL_REVIEWS = 0


@dataclass(frozen=True)
class ReadinessEvidence:
    """Evidencias consolidadas de reports/telemetry (offline).

    Todos os campos vem de reports JA SALVOS — nada de rede.
    """

    total_sessions: int = 0
    short_demo_clean_count: int = 0        # A_clean / full cycle clean
    short_demo_completed_count: int = 0
    long_demo_completed_count: int = 0
    residual_positions: int = 0
    unexpected_open_orders: int = 0
    orders_missing_sl_tp: int = 0
    flat_check_failures: int = 0
    unresolved_pnl_count: int = 0
    safety_events_total: int = 0
    api_failures_total: int = 0
    risk_violations_total: int = 0
    unresolved_manual_reviews: int = 0
    ai_critical_vetoes: int = 0
    ai_warnings_total: int = 0
    advisor_overfitting_critical: int = 0
    prediction_critical_unhandled: int = 0
    prediction_warnings_total: int = 0
    short_validated: bool = False
    multi_order_gate_validated: bool = False
    profile_compliance_ok: bool = True
    justifications: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not isinstance(self.justifications, tuple):
            object.__setattr__(
                self, "justifications", tuple(self.justifications),
            )

    def to_dict(self) -> dict:
        return {
            "total_sessions": int(self.total_sessions),
            "short_demo_clean_count": int(self.short_demo_clean_count),
            "short_demo_completed_count": int(
                self.short_demo_completed_count
            ),
            "long_demo_completed_count": int(
                self.long_demo_completed_count
            ),
            "residual_positions": int(self.residual_positions),
            "unexpected_open_orders": int(self.unexpected_open_orders),
            "orders_missing_sl_tp": int(self.orders_missing_sl_tp),
            "flat_check_failures": int(self.flat_check_failures),
            "unresolved_pnl_count": int(self.unresolved_pnl_count),
            "safety_events_total": int(self.safety_events_total),
            "api_failures_total": int(self.api_failures_total),
            "risk_violations_total": int(self.risk_violations_total),
            "unresolved_manual_reviews": int(
                self.unresolved_manual_reviews
            ),
            "ai_critical_vetoes": int(self.ai_critical_vetoes),
            "ai_warnings_total": int(self.ai_warnings_total),
            "advisor_overfitting_critical": int(
                self.advisor_overfitting_critical
            ),
            "prediction_critical_unhandled": int(
                self.prediction_critical_unhandled
            ),
            "prediction_warnings_total": int(
                self.prediction_warnings_total
            ),
            "short_validated": bool(self.short_validated),
            "multi_order_gate_validated": bool(
                self.multi_order_gate_validated
            ),
            "profile_compliance_ok": bool(self.profile_compliance_ok),
            "justifications": list(self.justifications),
        }


def evaluate_rules(
    evidence: ReadinessEvidence, *, profile=None,
) -> Tuple[str, List[str], List[str]]:
    """Aplica as regras minimas. Retorna (verdict, blockers, warnings).

    verdicts: ready | not_ready | manual_review_required |
              insufficient_history
    """
    blockers: List[str] = []
    warnings: List[str] = []

    # 0. Historico minimo.
    if evidence.total_sessions < MIN_TOTAL_SESSIONS:
        return (
            "insufficient_history",
            [
                f"total_sessions={evidence.total_sessions} < "
                f"{MIN_TOTAL_SESSIONS}"
            ],
            warnings,
        )

    # 1. Condicoes que exigem manual review imediato.
    review: List[str] = []
    if evidence.safety_events_total > MAX_SAFETY_EVENTS:
        review.append(
            f"safety_events={evidence.safety_events_total} > "
            f"{MAX_SAFETY_EVENTS}"
        )
    if evidence.unresolved_manual_reviews > \
            MAX_UNRESOLVED_MANUAL_REVIEWS:
        review.append(
            "manual reviews nao resolvidos: "
            f"{evidence.unresolved_manual_reviews}"
        )
    if evidence.ai_critical_vetoes > 0:
        review.append(
            f"AI vetos criticos: {evidence.ai_critical_vetoes}"
        )
    if evidence.prediction_critical_unhandled > 0:
        review.append(
            "prediction market alerts criticos nao tratados: "
            f"{evidence.prediction_critical_unhandled}"
        )
    if review:
        return ("manual_review_required", review, warnings)

    # 2. Criterios minimos para ready.
    has_short_ok = evidence.short_demo_clean_count >= 1 or any(
        "short_demo" in j for j in evidence.justifications
    )
    if not has_short_ok:
        blockers.append(
            "nenhuma demo curta A_clean (nem justificativa tecnica)"
        )
    has_long_ok = evidence.long_demo_completed_count >= 1 or any(
        "long_demo" in j for j in evidence.justifications
    )
    if not has_long_ok:
        blockers.append(
            "nenhuma demo longa concluida (nem justificativa)"
        )
    if evidence.residual_positions > 0:
        blockers.append(
            f"posicao residual: {evidence.residual_positions}"
        )
    if evidence.unexpected_open_orders > 0:
        blockers.append(
            "ordens pendentes inesperadas: "
            f"{evidence.unexpected_open_orders}"
        )
    if evidence.orders_missing_sl_tp > 0:
        blockers.append(
            f"ordens sem SL/TP: {evidence.orders_missing_sl_tp}"
        )
    if evidence.flat_check_failures > 0:
        blockers.append(
            f"flat-check inconsistente: {evidence.flat_check_failures}"
        )
    if evidence.unresolved_pnl_count > 0:
        blockers.append(
            f"P&L nao resolvido: {evidence.unresolved_pnl_count}"
        )
    if evidence.api_failures_total > MAX_API_FAILURES_TOTAL:
        blockers.append(
            f"api_failures={evidence.api_failures_total} > "
            f"{MAX_API_FAILURES_TOTAL}"
        )
    if evidence.risk_violations_total > 0:
        blockers.append(
            f"violacoes RiskEngine: {evidence.risk_violations_total}"
        )
    if not evidence.profile_compliance_ok:
        blockers.append("profile compliance reprovado")
    if evidence.advisor_overfitting_critical > 0:
        blockers.append(
            "advisor com overfitting critico: "
            f"{evidence.advisor_overfitting_critical}"
        )

    # 3. Gates: short/multi-order so contam como prontos se validados.
    if profile is not None:
        if getattr(profile, "allow_short_demo", False) and \
                not evidence.short_validated:
            blockers.append(
                "perfil permite short demo mas short NAO foi validado"
            )
        if getattr(profile, "allow_multi_order_demo", False) and \
                not evidence.multi_order_gate_validated:
            blockers.append(
                "perfil permite multi-order mas gate NAO foi validado"
            )

    # 4. Warnings consultivos (nao bloqueiam sozinhos).
    if evidence.ai_warnings_total > 0:
        warnings.append(
            f"ai_warnings_total={evidence.ai_warnings_total}"
        )
    if evidence.prediction_warnings_total > 0:
        warnings.append(
            "prediction_warnings_total="
            f"{evidence.prediction_warnings_total}"
        )

    verdict = "ready" if not blockers else "not_ready"
    return (verdict, blockers, warnings)


__all__ = [
    "MAX_API_FAILURES_TOTAL",
    "MAX_SAFETY_EVENTS",
    "MIN_TOTAL_SESSIONS",
    "ReadinessEvidence",
    "evaluate_rules",
]
