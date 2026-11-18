"""
DecisionTraceBuilder (FASE 36 Bloco A)
=======================================
Constroi DecisionTraceEntry a partir dos artefatos JA produzidos pelo
pipeline (signal snapshot FASE 29.x, risk_summary, ai fields,
prediction/MI snapshot, gate results) — sem recalcular nada.

⚠️  Puro/offline. Campos ausentes ficam None/() — nunca inventados.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from crypto_trading_bot.decision_trace.trace_model import (
    DecisionTraceEntry,
    FinalDecision,
)


_INDICATOR_KEYS = (
    "ema_fast_period", "ema_slow_period", "ema_fast_value",
    "ema_slow_value", "rsi_period", "rsi_value", "atr_period",
    "atr_value", "last_close", "last_high", "last_low", "last_volume",
)


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_trace_entry(
    *,
    cycle_idx: int,
    session_id: str = "",
    final_decision: FinalDecision,
    final_reason: str,
    now: Optional[datetime] = None,
    profile: Any = None,
    provider_id: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
    signal_snapshot: Optional[Mapping[str, Any]] = None,
    trading_signal: Any = None,
    risk_summary: Optional[Mapping[str, Any]] = None,
    exposure_before: Optional[float] = None,
    exposure_after: Optional[float] = None,
    position_before: Optional[Mapping[str, Any]] = None,
    open_orders_before: Optional[int] = None,
    conditional_orders_before: Optional[int] = None,
    ai_report_fields: Optional[Mapping[str, Any]] = None,
    ai_not_used_reason: Optional[str] = None,
    mi_snapshot: Optional[Mapping[str, Any]] = None,
    mi_not_used_reason: Optional[str] = None,
    gates_approved: Sequence[str] = (),
    gates_blocked: Sequence[str] = (),
    realized_pnl: Optional[float] = None,
    trade_idx: Optional[int] = None,
) -> DecisionTraceEntry:
    """Monta a entry consolidando artefatos do ciclo."""
    now = now or datetime.now(timezone.utc)
    snap = dict(signal_snapshot or {})

    indicators = {
        k: snap[k] for k in _INDICATOR_KEYS if k in snap
    }

    # Motivos tecnicos a partir do snapshot FASE 29.x.
    side = snap.get("signal_side")
    entry_reason = None
    rejection_reason = None
    if side in ("buy", "sell"):
        conds = snap.get(
            "long_conditions" if side == "buy" else "short_conditions",
        ) or {}
        met = [k for k, v in dict(conds).items() if v is True]
        entry_reason = (
            f"{side.upper()} setup: condicoes atendidas {met}"
            if met else f"{side.upper()} setup"
        )
    else:
        hold_reason = snap.get("hold_reason")
        failed_l = list(snap.get("failed_conditions_long") or [])
        failed_s = list(snap.get("failed_conditions_short") or [])
        if hold_reason or failed_l or failed_s:
            rejection_reason = (
                f"hold_reason={hold_reason}; "
                f"failed_long={failed_l}; failed_short={failed_s}"
            )[:300]

    # Plano de trade a partir do TradingSignal (quando ha).
    planned_sl = planned_tp = rr = qty = notional = lev = None
    if trading_signal is not None:
        entry_price = _f(getattr(trading_signal, "entry_price", None))
        planned_sl = _f(getattr(
            trading_signal, "stop_loss_price", None,
        ))
        planned_tp = _f(getattr(
            trading_signal, "take_profit_price", None,
        ))
        notional = _f(getattr(
            trading_signal, "position_size_usd", None,
        ))
        lev = _f(getattr(trading_signal, "leverage", None))
        if entry_price and planned_sl and planned_tp and \
                entry_price != planned_sl:
            rr = round(
                abs(planned_tp - entry_price)
                / abs(entry_price - planned_sl), 4,
            )
        if entry_price and notional:
            qty = round(notional / entry_price, 8)

    risk = dict(risk_summary or {})
    risk_decision = None
    if "approved" in risk:
        risk_decision = "approved" if risk.get("approved") else "rejected"
    est_risk_usd = None
    if qty is not None and planned_sl is not None and \
            trading_signal is not None:
        entry_price = _f(getattr(trading_signal, "entry_price", None))
        if entry_price:
            est_risk_usd = round(
                abs(entry_price - planned_sl) * qty, 6,
            )

    # --- diagnostico SL x piso de risco (pos-demo 3) ---
    # planned_sl_pct: do TradingSignal (entry/stop) OU do snapshot do
    # HOLD risk-aware (stop_below_min_risk_floor). Em %.
    planned_sl_pct = None
    if trading_signal is not None:
        ts_pct = _f(getattr(trading_signal, "stop_loss_pct", None))
        if ts_pct is not None:
            planned_sl_pct = round(ts_pct * 100.0, 4)
    if planned_sl_pct is None and snap.get("planned_sl_pct") is not None:
        planned_sl_pct = _f(snap.get("planned_sl_pct"))
    min_sl_pct_required = None
    raw_min = risk.get("min_stop_loss_pct")
    if raw_min is None:
        raw_min = snap.get("min_sl_pct_required")
        if raw_min is not None:
            min_sl_pct_required = _f(raw_min)
    elif raw_min is not None:
        # risk config guarda fracao (0.005); reportamos em %.
        min_sl_pct_required = round(_f(raw_min) * 100.0, 4)
    sl_gap_to_min_pct = None
    risk_rejection_category = None
    recommended_action = None
    if planned_sl_pct is not None and min_sl_pct_required is not None:
        sl_gap_to_min_pct = round(
            min_sl_pct_required - planned_sl_pct, 4,
        )
        below = planned_sl_pct < min_sl_pct_required
        rejected = risk_decision == "rejected"
        is_sl_block = below and (
            rejected or final_decision in (
                FinalDecision.SKIP, FinalDecision.BLOCK, FinalDecision.HOLD,
            )
        )
        if is_sl_block:
            risk_rejection_category = "stop_loss_below_minimum"
            recommended_action = (
                "SL planejado abaixo do piso de risco. Opcoes (sem "
                "baixar o piso): aumentar stop_atr_multiplier OU definir "
                "min_stop_loss_pct na estrategia (clamp/reject) OU "
                "aguardar regime de maior volatilidade. Rodar Strategy "
                "Parameter Advisor antes de ajustar."
            )

    ai_fields = dict(ai_report_fields or {})
    ai_used = bool(ai_fields.get("ai_enabled", False)) and \
        ai_fields.get("ai_status") is not None

    mi = dict(mi_snapshot or {})
    mi_used = bool(mi)

    return DecisionTraceEntry(
        trace_id=f"trace-{uuid.uuid4().hex[:12]}",
        cycle_idx=cycle_idx,
        timestamp=now,
        session_id=session_id,
        strategy_id=snap.get("strategy_id"),
        strategy_name=snap.get("strategy_name"),
        strategy_version=snap.get("strategy_version"),
        profile_name=getattr(profile, "name", None),
        provider_id=provider_id,
        symbol=symbol or snap.get("symbol"),
        timeframe=timeframe,
        candle_price=_f(snap.get("last_close")),
        indicators=indicators,
        signal_side=side,
        signal_confidence=_f(snap.get("signal_confidence")),
        entry_reason_technical=entry_reason,
        rejection_reason_technical=rejection_reason,
        risk_decision=risk_decision,
        risk_reason=(risk.get("reason") or None),
        estimated_risk_usd=est_risk_usd,
        exposure_before=exposure_before,
        exposure_after=exposure_after,
        planned_sl=planned_sl,
        planned_tp=planned_tp,
        risk_reward=rr,
        qty=qty,
        notional_usd=notional,
        leverage=lev,
        position_before=position_before,
        open_orders_before=open_orders_before,
        conditional_orders_before=conditional_orders_before,
        ai_used=ai_used,
        ai_not_used_reason=(
            None if ai_used else (ai_not_used_reason or "ai_disabled")
        ),
        ai_status=ai_fields.get("ai_status"),
        ai_reason=ai_fields.get("ai_reason"),
        market_intelligence_used=mi_used,
        mi_not_used_reason=(
            None if mi_used else (
                mi_not_used_reason or "market_intelligence_disabled"
            )
        ),
        mi_sources_used=tuple(mi.get("sources_used") or ()),
        mi_sources_stale=tuple(mi.get("sources_stale") or ()),
        mi_sources_unavailable=tuple(
            mi.get("sources_unavailable") or (),
        ),
        mi_risk_flags=tuple(mi.get("risk_flags") or ()),
        news_used="news" in (mi.get("sources_used") or ()),
        funding_used="funding" in (mi.get("sources_used") or ()),
        open_interest_used="open_interest" in (
            mi.get("sources_used") or ()
        ),
        orderbook_used="orderbook" in (mi.get("sources_used") or ()),
        liquidity_correlation_used="liquidity_correlation" in (
            mi.get("sources_used") or ()
        ),
        context_inconclusive=bool(mi.get("inconclusive", False)),
        gates_approved=tuple(gates_approved),
        gates_blocked=tuple(gates_blocked),
        final_decision=final_decision,
        final_reason=final_reason,
        realized_pnl=realized_pnl,
        trade_idx=trade_idx,
        planned_sl_pct=planned_sl_pct,
        min_sl_pct_required=min_sl_pct_required,
        sl_gap_to_min_pct=sl_gap_to_min_pct,
        risk_rejection_category=risk_rejection_category,
        recommended_action=recommended_action,
    )


__all__ = ["build_trace_entry"]
