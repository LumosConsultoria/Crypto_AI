"""
Demo30Min UI snapshot (FASE 26)
====================================
to_ui_snapshot() canonico para CLI/dashboard/HTML futuro.

⚠️  Sanitizado. ZERO secrets. Sem API key, sem secret, sem Bearer,
    sem X-BAPI-SIGN, sem Authorization, sem sign=, sem signature,
    sem origin_string, sem .env, sem operator_token completo.

Estrutura estavel:
    stage_info | readiness | plan | session | risk_health | safety |
    verdict | audit
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from crypto_trading_bot.demo_endurance.outcome import Demo30MinOutcome
from crypto_trading_bot.demo_endurance.plan import Demo30MinPlan
from crypto_trading_bot.demo_endurance.readiness import (
    Demo30MinReadinessReport,
)


def to_ui_snapshot(
    *,
    plan: Demo30MinPlan,
    outcome: Demo30MinOutcome,
    readiness: Optional[Demo30MinReadinessReport] = None,
    last_check_at: Optional[datetime] = None,
    data_freshness_seconds: int = 0,
    blueprint_age_seconds: Optional[int] = None,
    blueprint_ttl_remaining: Optional[int] = None,
) -> Dict[str, Any]:
    """Constroi snapshot UI canonico.

    Contrato estavel:
        stage_info:  stage, mode, provider, environment, endpoint_type,
                     symbol, strategy_name, session_id, schema_version
        readiness:   status, blockers, warnings, info
        plan:        max_session_minutes, max_orders, max_open_positions,
                     blueprint_ttl_seconds_remaining,
                     planned_signal_blueprint{side, entry_price,
                         stop_loss, take_profit, qty, notional_usd}
        session:     elapsed_minutes, cycles_completed,
                     orders_planned, orders_submitted, orders_filled,
                     open_positions_count, open_orders_count,
                     conditional_orders_count, current_position_qty,
                     sl_attached, tp_attached
        risk_health: risk_pct_planned, notional_usd_planned,
                     wallet_balance_usd, equity_usd, risk_violations_count
        safety:      safety_state, safety_events_count,
                     manual_review_required, safety_halt_recommended
        verdict:     verdict, recommended_next_action, next_stage,
                     outcome_reason
        audit:       operator_token_sanitized, last_check_at,
                     data_freshness_seconds, evaluated_at
    """
    if not isinstance(plan, Demo30MinPlan):
        raise TypeError("plan deve ser Demo30MinPlan")
    if not isinstance(outcome, Demo30MinOutcome):
        raise TypeError("outcome deve ser Demo30MinOutcome")

    bp = plan.planned_blueprint
    now = last_check_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if readiness is not None:
        readiness_block = {
            "status": readiness.status.value,
            "blockers": [i.to_dict() for i in readiness.blockers],
            "warnings": [i.to_dict() for i in readiness.warnings],
            "info": [i.to_dict() for i in readiness.info],
        }
    else:
        readiness_block = {
            "status": "ready",
            "blockers": [],
            "warnings": [],
            "info": [],
        }

    # FASE 27 - mode pode ser dry_run_planned (FASE 26) ou
    # real_endurance (FASE 27). real_vs_dry_run derivado para CLI.
    is_real = (outcome.mode == "real_endurance")
    snapshot = {
        "stage_info": {
            "stage": plan.stage.value,
            "mode": outcome.mode,
            "real_vs_dry_run": "real" if is_real else "dry_run",
            "provider": plan.provider_id,
            "environment": plan.environment,
            "endpoint_type": plan.endpoint_type,
            "symbol": plan.symbol,
            "strategy_name": plan.strategy_name,
            "session_id": plan.session_id,
            "schema_version": int(plan.schema_version),
        },
        "readiness": readiness_block,
        "plan": {
            "max_session_minutes": int(plan.max_session_minutes),
            "max_orders": int(plan.max_orders),
            "max_open_positions": int(plan.max_open_positions),
            "blueprint_id": (
                plan.live_blueprint_id if plan.live_blueprint_id
                else None
            ),
            "blueprint_age_seconds": (
                int(blueprint_age_seconds)
                if blueprint_age_seconds is not None else None
            ),
            "blueprint_ttl_remaining": (
                int(blueprint_ttl_remaining)
                if blueprint_ttl_remaining is not None
                else int(bp.ttl_seconds_remaining(now))
            ),
            "blueprint_ttl_seconds_remaining": int(
                bp.ttl_seconds_remaining(now)
            ),
            "planned_signal_blueprint": {
                "side": bp.side,
                "entry_price": float(bp.entry_price),
                "stop_loss": float(bp.stop_loss),
                "take_profit": float(bp.take_profit),
                "qty": float(bp.qty),
                "notional_usd": float(bp.notional_usd),
            },
        },
        "session": {
            "elapsed_minutes": int(outcome.elapsed_minutes),
            "cycles_completed": int(outcome.cycles_completed),
            "orders_planned": int(outcome.orders_planned),
            "orders_submitted": int(outcome.orders_submitted),
            "orders_filled": int(outcome.orders_filled),
            "open_positions_count": int(outcome.open_positions_count),
            "open_orders_count": int(outcome.open_orders_count),
            "conditional_orders_count": int(outcome.conditional_orders_count),
            "current_position_qty": float(outcome.current_position_qty),
            "sl_attached": outcome.sl_attached,
            "tp_attached": outcome.tp_attached,
        },
        "risk_health": {
            "risk_pct_planned": float(outcome.risk_pct_planned),
            "notional_usd_planned": float(outcome.notional_usd_planned),
            "wallet_balance_usd": float(outcome.wallet_balance_usd),
            "equity_usd": float(outcome.wallet_balance_usd),
            "risk_violations_count": int(outcome.risk_violations_count),
        },
        "safety": {
            "safety_state": outcome.safety_state,
            "safety_events_count": int(outcome.safety_events_count),
            "manual_review_required": bool(outcome.manual_review_required),
            "safety_halt_recommended": bool(outcome.safety_halt_recommended),
        },
        "verdict": {
            "verdict": outcome.verdict.value,
            "recommended_next_action":
                outcome.recommended_next_action.value,
            "next_stage": (
                # FASE 29: estado coerente. FASE 27/28/29 entregues
                # tecnicamente; primeira execucao real demo via FASE 29
                # depende de autorizacao operacional separada.
                "demo_30_min real endurance (FASE 29 implemented; "
                "first real execution requires separate operator "
                "authorization)"
                if is_real
                else "demo_30_min planned/dry-run (FASE 26); wired "
                "dry-run real available in FASE 28 with deploy flag"
            ),
            "outcome_reason": outcome.outcome_reason,
            # FASE 29 Acceptance Polish - sinalizacao explicita,
            # sem ambiguidade, de Demo finalizada.
            "demo_finalized": bool(outcome.demo_finalized),
            "demo_finalization_scenario":
                outcome.demo_finalization_scenario,
            "apply_demo_real_invoked": bool(
                outcome.apply_demo_real_invoked
            ),
        },
        "audit": {
            "operator_token_sanitized": plan.operator_token_sanitized,
            "last_check_at": now.isoformat(),
            "data_freshness_seconds": int(data_freshness_seconds),
            "evaluated_at": outcome.ended_at.isoformat(),
            "live_blueprint_id": outcome.live_blueprint_id,
            "demo_session_outcome_snapshot": (
                dict(outcome.demo_session_outcome_snapshot)
                if outcome.demo_session_outcome_snapshot is not None
                else None
            ),
            "post_session_check_summary": (
                dict(outcome.post_session_check_summary)
                if outcome.post_session_check_summary is not None else None
            ),
        },
        # FASE 29 - bloco exit_management
        "exit_management": {
            "path": outcome.exit_management_path,
            "exit_reason": outcome.exit_reason,
            "close_orders_submitted":
                int(outcome.close_orders_submitted),
            "close_orders_filled": int(outcome.close_orders_filled),
            "reduce_only_close_invoked": (
                outcome.exit_management_path == "reduce_only_close"
            ),
        },
        # FASE 29 - flat-check final (snapshot do FlatCheckResult).
        "flat_check_final": (
            dict(outcome.flat_check_result)
            if outcome.flat_check_result is not None else {
                "is_flat": None, "positions_count": None,
                "open_orders_count": None,
                "conditional_orders_count": None,
                "residual_qty": None, "blockers": [],
            }
        ),
        # FASE 29 - P&L (apenas quando entrada ocorreu).
        "pnl": {
            "realized_pnl_usd": outcome.pnl_realized_usd,
            "pnl_source": outcome.pnl_source,
        },
        # FASE 29 - flags reais consolidadas.
        "real_flags": {
            "apply_demo_real_invoked":
                bool(outcome.apply_demo_real_invoked),
            "first_real_demo_order":
                bool(outcome.first_real_demo_order),
            "phrase_confirmation":
                bool(outcome.phrase_confirmation),
        },
    }
    return snapshot
