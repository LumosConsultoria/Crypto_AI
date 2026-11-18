"""
Human Renderer (FASE 36 Bloco A)
=================================
Converte DecisionTraceEntry em narrativa LEGIVEL para o operador.

Exemplo de saida:
    "Ciclo 12: trend_pullback gerou BUY em BTCUSDT 15m porque
    BUY setup: condicoes atendidas [...]. EMA20=..., RSI=58.
    IA nao usada (ai_disabled). MI nao usada. RiskEngine aprovou.
    SL=..., TP=..., RR=2.0. Gates aprovados: [...]. Decisao final:
    ENTER — ..."
"""

from __future__ import annotations

from crypto_trading_bot.decision_trace.trace_model import (
    DecisionTraceEntry,
)


def render_trace_entry(entry: DecisionTraceEntry) -> str:
    """Narrativa de uma decisao (1 paragrafo legivel)."""
    parts = []

    head = f"Ciclo {entry.cycle_idx}:"
    strat = entry.strategy_name or "estrategia"
    side = (entry.signal_side or "hold").upper()
    where = " ".join(
        str(x) for x in (entry.symbol, entry.timeframe) if x
    )
    if entry.signal_side in ("buy", "sell"):
        parts.append(f"{head} {strat} gerou {side} em {where}".strip())
        if entry.entry_reason_technical:
            parts.append(f"porque {entry.entry_reason_technical}")
    else:
        parts.append(f"{head} {strat} ficou em HOLD em {where}".strip())
        if entry.rejection_reason_technical:
            parts.append(f"({entry.rejection_reason_technical})")

    # Indicadores principais
    ind = dict(entry.indicators)
    ind_bits = []
    if ind.get("ema_fast_value") is not None:
        ind_bits.append(
            f"EMA{ind.get('ema_fast_period', '?')}="
            f"{ind['ema_fast_value']}"
        )
    if ind.get("ema_slow_value") is not None:
        ind_bits.append(
            f"EMA{ind.get('ema_slow_period', '?')}="
            f"{ind['ema_slow_value']}"
        )
    if ind.get("rsi_value") is not None:
        ind_bits.append(f"RSI={ind['rsi_value']}")
    if ind.get("atr_value") is not None:
        ind_bits.append(f"ATR={ind['atr_value']}")
    if ind_bits:
        parts.append(", ".join(ind_bits) + ".")

    # IA
    if entry.ai_used:
        parts.append(
            f"IA: {entry.ai_status}"
            + (f" ({entry.ai_reason})" if entry.ai_reason else "")
            + "."
        )
    else:
        parts.append(
            f"IA nao usada ({entry.ai_not_used_reason or 'off'})."
        )

    # Market Intelligence
    if entry.market_intelligence_used:
        mi_bits = [f"MI usada: {list(entry.mi_sources_used)}"]
        if entry.mi_sources_stale:
            mi_bits.append(f"stale: {list(entry.mi_sources_stale)}")
        if entry.mi_risk_flags:
            mi_bits.append(f"flags: {list(entry.mi_risk_flags)}")
        parts.append("; ".join(mi_bits) + ".")
    else:
        parts.append(
            "MI nao usada"
            + (f" ({entry.mi_not_used_reason})"
               if entry.mi_not_used_reason else "")
            + "."
        )

    # RiskEngine
    if entry.risk_decision == "approved":
        risk_txt = "RiskEngine aprovou"
        if entry.estimated_risk_usd is not None:
            risk_txt += f" (risco ~{entry.estimated_risk_usd} USD)"
        parts.append(risk_txt + ".")
    elif entry.risk_decision == "rejected":
        parts.append(
            "RiskEngine REPROVOU"
            + (f": {entry.risk_reason}" if entry.risk_reason else "")
            + "."
        )

    # Plano
    if entry.planned_sl is not None:
        plan_txt = f"SL={entry.planned_sl}"
        if entry.planned_tp is not None:
            plan_txt += f", TP={entry.planned_tp}"
        if entry.risk_reward is not None:
            plan_txt += f", RR={entry.risk_reward}"
        if entry.qty is not None:
            plan_txt += f", qty={entry.qty}"
        parts.append(plan_txt + ".")

    # Gates
    if entry.gates_approved:
        parts.append(
            f"Gates aprovados: {list(entry.gates_approved)}."
        )
    if entry.gates_blocked:
        parts.append(
            f"Gates BLOQUEADOS: {list(entry.gates_blocked)}."
        )

    # Decisao final
    final = entry.final_decision.value.upper()
    parts.append(
        f"Decisao final: {final}"
        + (f" — {entry.final_reason}" if entry.final_reason else "")
        + "."
    )
    if entry.realized_pnl is not None:
        parts.append(f"P&L realizado: {entry.realized_pnl} USD.")

    return " ".join(parts)


def render_trace_entries(entries) -> str:
    """Narrativa multi-decisao (uma linha por entry)."""
    return "\n".join(render_trace_entry(e) for e in entries)


__all__ = ["render_trace_entries", "render_trace_entry"]
