"""
Overlay Operacional (FASE 63) — produto nao-preditivo, read-only, auditavel.
============================================================================
Junta o Risk Overlay (FASE 57) + fonte (manual/Bybit read-only gated) +
blockers + readiness + decision trace. NUNCA ordem; demo/live bloqueados;
real_execution_allowed=False; orders_emitted=0; OOS intocado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from crypto_trading_bot.risk_overlay.models import (
    AccountState, Position, RiskLimits)
from crypto_trading_bot.risk_overlay.overlay import evaluate_risk_overlay

_BLOCK_SEVERITIES = ("high", "critical")


def _readiness(overlay: Mapping[str, Any], source_status: str,
               n_positions: int) -> Dict[str, Any]:
    """Readiness CONSULTIVO (nunca autoriza execucao). Critical => bloqueado;
    high => acao requerida; info=sinal, nao autorizacao."""
    sev = overlay.get("severity_counts", {}) or {}
    if source_status in ("gated_no_network", "unavailable", "not_configured") \
            and n_positions == 0:
        status = "insufficient_information"
        reason = "fonte read-only indisponivel e sem input manual."
    elif sev.get("critical"):
        status = "blocked_critical"
        reason = "alerta CRITICO ativo: agir (reduzir/encerrar exposicao)."
    elif sev.get("high"):
        status = "action_required"
        reason = "alerta de severidade ALTA: ajustar risco/exposicao."
    elif n_positions == 0:
        status = "flat_ok"
        reason = "sem posicao; nada a mitigar."
    else:
        status = "ready_monitor"
        reason = "risco dentro das regras; apenas monitorar."
    return {"status": status, "reason": reason,
            "authorizes_execution": False,
            "note": "readiness e SINAL consultivo; NUNCA autoriza ordem."}


def build_operational_overlay(
    account: AccountState, positions: Sequence[Position],
    limits: Optional[RiskLimits] = None, *,
    source_info: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    src = dict(source_info or {"status": "manual"})
    ov = evaluate_risk_overlay(account, positions, limits)
    blockers = [a for a in ov["alerts"] if a["severity"] in _BLOCK_SEVERITIES]
    readiness = _readiness(ov, src.get("status", "manual"), len(positions))
    decision_trace: List[Dict[str, Any]] = [
        {"step": "source", "detail": {"status": src.get("status"),
                                      "note": src.get("note"),
                                      "manual_fallback": src.get(
                                          "manual_fallback", False)}},
        {"step": "exposure", "detail": ov["exposure_summary"]},
        {"step": "alerts", "detail": {"counts": ov["severity_counts"],
                                      "total": len(ov["alerts"])}},
        {"step": "blockers", "detail": {"count": len(blockers),
                                        "codes": [b["code"] for b in blockers]}},
        {"step": "readiness", "detail": readiness},
        {"step": "safety", "detail": {"real_execution_allowed": False,
                                      "orders_emitted": 0, "demo_blocked": True,
                                      "live_blocked": True,
                                      "oos_untouched": True}},
    ]
    return {
        "schema": "operational_overlay_phase63_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "advisory_read_only_non_predictive",
        "source": src.get("status"),
        "source_note": src.get("note"),
        "limits": ov["limits"],
        "account": ov["account"],
        "positions": ov["positions"],
        "exposure_summary": ov["exposure_summary"],
        "risk_alerts": ov["alerts"],
        "blockers": blockers,
        "overall_status": ov["overall_status"],
        "readiness": readiness,
        "decision_trace": decision_trace,
        "recommendations": ov["recommendations"],
        "real_execution_allowed": False, "orders_emitted": 0,
        "demo_blocked": True, "live_blocked": True, "oos_untouched": True,
        "predictive_search_closed": True,
        "note": ("Produto operacional NAO-preditivo: avalia risco/exposicao e "
                 "alerta; NUNCA ordem. Busca preditiva BTCUSDT-only ENCERRADA "
                 "(FASE 63). RiskEngine/ModeGuard/piso 0.005 intactos."),
    }


__all__ = ["build_operational_overlay"]
