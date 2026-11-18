"""
Standard Trader — fechamento MENSAL (FASE 54). Leitura PRINCIPAL do perfil
Trader Padrao / Conta Propria: mes a mes com equity de abertura/fechamento,
retorno, custos, funding, drawdown do mes e consolidado. Sem meta Hyro; sem
daily DD de challenge; concentracao fica informativa (nao aqui).

`rows` = saidas de _trade_rows do standard_report: cada item tem exit_time
(datetime UTC), gross, net_pre_funding, funding, net. custos por trade =
gross - net_pre_funding (fees+slippage+spread combinados; o split fica no
strategy_metrics a nivel de segmento).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


def _month_key(dt) -> Optional[str]:
    if dt is None:
        return None
    return f"{dt.year}-{dt.month:02d}"


def standard_trader_monthly_close(rows: Sequence[Dict[str, Any]], *,
                                  capital: float = 5000.0) -> Dict[str, Any]:
    by_month: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        k = _month_key(r.get("exit_time"))
        if k is None:
            continue
        by_month.setdefault(k, []).append(r)
    months = sorted(by_month.keys())

    equity = capital
    full_peak = capital
    full_maxdd = 0.0
    out_rows: List[Dict[str, Any]] = []
    monthly_nets: List[float] = []
    _far = datetime.max.replace(tzinfo=timezone.utc)
    for m in months:
        mrows = sorted(by_month[m], key=lambda r: r.get("exit_time") or _far)
        start_eq = equity
        peak = start_eq
        mdd = 0.0
        gross = cost = funding = net = 0.0
        wins = 0
        for r in mrows:
            net += r["net"]
            gross += r["gross"]
            funding += r["funding"]
            cost += (r["gross"] - r["net_pre_funding"])
            if r["net"] > 0:
                wins += 1
            equity += r["net"]
            peak = max(peak, equity)
            mdd = max(mdd, peak - equity)
            full_peak = max(full_peak, equity)
            full_maxdd = max(full_maxdd, full_peak - equity)
        monthly_nets.append(net)
        out_rows.append({
            "month": m, "start_equity": round(start_eq, 2),
            "end_equity": round(equity, 2), "net_pnl_usd": round(net, 2),
            "net_return_pct": round(net / start_eq * 100, 4) if start_eq else None,
            "gross_pnl_usd": round(gross, 2),
            "fees_slippage_spread_usd": round(cost, 2),
            "funding_usd": round(funding, 2), "number_of_trades": len(mrows),
            "win_rate": round(wins / len(mrows), 4) if mrows else None,
            "max_drawdown_month_pct": round(mdd / start_eq * 100, 4)
            if start_eq else None,
            "positive_month": net > 0})

    pos = [r for r in out_rows if r["positive_month"]]
    neg = [r for r in out_rows if not r["positive_month"]]
    streak = best_streak = 0
    for r in out_rows:
        if not r["positive_month"]:
            streak += 1
            best_streak = max(best_streak, streak)
        else:
            streak = 0
    best_m = max(out_rows, key=lambda r: r["net_pnl_usd"]) if out_rows else None
    worst_m = min(out_rows, key=lambda r: r["net_pnl_usd"]) if out_rows else None
    cum_net = round(equity - capital, 2)
    return {
        "monthly": out_rows,
        "total_months": len(out_rows),
        "positive_months": len(pos),
        "negative_months": len(neg),
        "positive_month_rate": round(len(pos) / len(out_rows), 4)
        if out_rows else None,
        "best_month": ({"month": best_m["month"],
                        "net_pnl_usd": best_m["net_pnl_usd"]} if best_m else None),
        "worst_month": ({"month": worst_m["month"],
                         "net_pnl_usd": worst_m["net_pnl_usd"]}
                        if worst_m else None),
        "average_monthly_pnl": round(statistics.mean(monthly_nets), 2)
        if monthly_nets else None,
        "median_monthly_pnl": round(statistics.median(monthly_nets), 2)
        if monthly_nets else None,
        "longest_negative_month_streak": best_streak,
        "cumulative_net_pnl": cum_net,
        "cumulative_return_pct": round(cum_net / capital * 100, 4)
        if capital else None,
        "max_drawdown_full_period_usd": round(full_maxdd, 2),
        "max_drawdown_full_period_pct": round(full_maxdd / full_peak * 100, 4)
        if full_peak else None,
        "note": ("leitura PRINCIPAL do Trader Padrao; sem meta Hyro/daily-DD-"
                 "challenge; fees/slippage combinados por mes (split por trade "
                 "so a nivel de segmento em strategy_metrics)."),
    }


__all__ = ["standard_trader_monthly_close"]
