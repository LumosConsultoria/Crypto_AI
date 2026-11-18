"""
UI Contracts - Snapshots (FASE 36 Bloco G)
===========================================
Contratos de dados para a tela operacional FUTURA. A UI visual NAO e
implementada agora; estes snapshots JA sao produzidos em JSON pelo
runner/CLI/readiness, sem hardcode visual.

⚠️  Offline/puro. ZERO secret (compoe apenas dados ja sanitizados).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence


def build_decision_trace_snapshot(
    *, traces: Sequence[Mapping[str, Any]], limit: int = 20,
) -> dict:
    """DecisionTraceSnapshot: ultimas decisoes + narrativa humana."""
    from crypto_trading_bot.decision_trace import (
        DecisionTraceEntry, FinalDecision, render_trace_entry,
    )
    recent = list(traces)[-limit:]
    rendered = []
    for t in recent:
        try:
            entry_kwargs = {
                k: v for k, v in dict(t).items()
                if k in DecisionTraceEntry.__dataclass_fields__
                and k not in ("final_decision", "timestamp")
            }
            entry = DecisionTraceEntry(
                final_decision=FinalDecision(t["final_decision"]),
                timestamp=datetime.fromisoformat(t["timestamp"]),
                **entry_kwargs,
            )
            rendered.append(render_trace_entry(entry))
        except Exception:  # noqa: BLE001
            rendered.append(str(t.get("final_reason", ""))[:200])
    return {
        "schema": "decision_trace_snapshot_v1",
        "total_traces": len(traces),
        "recent": recent,
        "recent_human": rendered,
    }


def build_position_management_snapshot(
    *,
    position: Optional[Mapping[str, Any]] = None,
    exposure: Optional[Mapping[str, Any]] = None,
    aggregated_risk: Optional[Mapping[str, Any]] = None,
    scale_in_enabled: bool = False,
    partial_reduce_enabled: bool = False,
    reversal_policy: str = "blocked",
) -> dict:
    """PositionManagementSnapshot (UI-ready)."""
    return {
        "schema": "position_management_snapshot_v1",
        "position": dict(position) if position else None,
        "exposure": dict(exposure) if exposure else None,
        "aggregated_risk": (
            dict(aggregated_risk) if aggregated_risk else None
        ),
        "scale_in_enabled": bool(scale_in_enabled),
        "partial_reduce_enabled": bool(partial_reduce_enabled),
        "reversal_policy": reversal_policy,
        "scale_in_allowed_this_phase": False,
        "auto_reversal_allowed": False,
    }


def build_readiness_snapshot(
    *, readiness_report: Mapping[str, Any],
) -> dict:
    """ReadinessSnapshot (UI-ready)."""
    rep = dict(readiness_report)
    return {
        "schema": "readiness_snapshot_v1",
        "verdict": rep.get("verdict"),
        "blockers": list(rep.get("blockers") or []),
        "warnings": list(rep.get("warnings") or []),
        "reports_scanned": rep.get("reports_scanned", 0),
        "note": rep.get("note"),
    }


def build_session_snapshot(
    *,
    outcome: Mapping[str, Any],
    profile: Any,
) -> dict:
    """SessionSnapshot: estado consolidado da sessao (UI-ready)."""
    oc = dict(outcome)
    summ = dict(oc.get("session_summary") or {})
    return {
        "schema": "session_snapshot_v1",
        "session_id": oc.get("session_id"),
        "provider": getattr(profile, "allowed_provider_ids", ()),
        "environment": getattr(profile, "allowed_environments", ()),
        "profile": getattr(profile, "name", "?"),
        "strategy": oc.get("strategy_name"),
        "symbol": oc.get("symbol"),
        "execution_mode": oc.get("execution_mode"),
        "real_time_mode": oc.get("real_time_mode"),
        "status": oc.get("ended_reason"),
        "cycles_completed": oc.get("cycles_completed"),
        "expected_cycles": oc.get("expected_cycles"),
        "signals_evaluated": oc.get("signals_evaluated"),
        "would_orders": oc.get("would_orders"),
        "orders_submitted": oc.get("orders_submitted"),
        "trades_completed": oc.get("trades_completed"),
        "total_realized_pnl": oc.get("total_realized_pnl"),
        "ai_enabled": summ.get("ai_enabled"),
        "ai_status": summ.get("ai_status"),
        "ai_not_used_reason": summ.get("ai_not_used_reason"),
        "prediction_market_context": summ.get(
            "prediction_market_context",
        ),
        "warnings": list(oc.get("warnings") or []),
        "final_flat_check_passed": oc.get("final_flat_check_passed"),
    }


def build_operator_dashboard_snapshot(
    *,
    session: Optional[Mapping[str, Any]] = None,
    decision_traces: Sequence[Mapping[str, Any]] = (),
    position_mgmt: Optional[Mapping[str, Any]] = None,
    readiness: Optional[Mapping[str, Any]] = None,
    options_registry: Any = None,
    required_inputs_report: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict:
    """OperatorDashboardSnapshot COMPLETO (item 8 da spec).

    Acoes permitidas/bloqueadas derivam do Options Registry:
    opcao current_enabled + status available => permitida;
    caso contrario => bloqueada com motivo explicito.
    """
    now = now or datetime.now(timezone.utc)
    allowed_actions = []
    blocked_actions = []
    if options_registry is not None:
        for opt in options_registry.all_options:
            d = opt.to_dict()
            row = {
                "option_id": d["option_id"],
                "label": d["label"],
                "ui_group": d["ui_group"],
            }
            if d["current_enabled"] and d["status"] == "available":
                allowed_actions.append(row)
            else:
                reason = (
                    d["blocked_reason"]
                    or (
                        "missing: "
                        + "; ".join(d["missing_information"])
                        if d["missing_information"] else None
                    )
                    or (
                        f"gate {d['required_gate_name']} off"
                        if d["required_gate_name"]
                        and not d["current_enabled"] else None
                    )
                    or f"status={d['status']}"
                )
                blocked_actions.append(
                    {**row, "blocked_reason": reason},
                )
    return {
        "schema": "operator_dashboard_snapshot_v1",
        "generated_at": now.isoformat(),
        "session": dict(session) if session else None,
        "decision_trace": build_decision_trace_snapshot(
            traces=decision_traces,
        ),
        "position_management": (
            dict(position_mgmt) if position_mgmt
            else build_position_management_snapshot()
        ),
        "readiness": (
            build_readiness_snapshot(readiness_report=readiness)
            if readiness else None
        ),
        "required_inputs": (
            dict(required_inputs_report)
            if required_inputs_report else None
        ),
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "options_total": (
            len(options_registry.all_options)
            if options_registry is not None else 0
        ),
    }


__all__ = [
    "build_decision_trace_snapshot",
    "build_operator_dashboard_snapshot",
    "build_position_management_snapshot",
    "build_readiness_snapshot",
    "build_session_snapshot",
]
