"""
Relatorios da microestrutura (FASE 63): data_quality + shadow + classificacao.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.microstructure import features as F
from crypto_trading_bot.microstructure.models import Tick

# criterio "promissor em shadow" (operador)
MIN_SIGNALS = 100
PF_MIN = 1.20
MAXDD_LIMIT_PCT = 15.0
CONCENTRATION_MAX = 0.50


def _p95(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return round(statistics.quantiles(xs, n=20)[18] if len(xs) >= 20
                 else max(xs), 4)


def build_data_quality(ticks: Sequence[Tick]) -> Dict[str, Any]:
    spreads = [F.spread_bps(t.book) for t in ticks]
    depths = [(t.book.depth("bid") + t.book.depth("ask")) / 2 for t in ticks]
    snaps = [t.book for t in ticks]
    ofis = [F.window_ofi(snaps, t.ts, 10.0) for t in ticks]
    ofis = [abs(o) for o in ofis if o is not None]
    n_trades = sum(len(t.trades) for t in ticks)
    buy = sum(tr.size for t in ticks for tr in t.trades if tr.side == "buy")
    sell = sum(tr.size for t in ticks for tr in t.trades if tr.side == "sell")
    uptime = (ticks[-1].ts - ticks[0].ts) if len(ticks) >= 2 else 0.0
    sp = [s for s in spreads if s is not None]
    return {
        "schema": "microstructure_phase63_data_quality_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(uptime, 1), "book_updates": len(ticks),
        "trades_tape": n_trades,
        "spread_bps_mean": round(statistics.mean(sp), 4) if sp else None,
        "spread_bps_p95": _p95(spreads),
        "depth_mean": round(statistics.mean(depths), 4) if depths else None,
        "ofi_abs_mean": round(statistics.mean(ofis), 4) if ofis else None,
        "ofi_abs_p95": _p95(ofis),
        "aggression_ratio": round(buy / (buy + sell), 4)
        if (buy + sell) > 0 else None,
        "real_execution_allowed": False, "orders_emitted": 0,
        "demo_blocked": True, "live_blocked": True, "oos_untouched": True,
    }


def _maxdd_pct(trades, capital):
    eq = capital
    peak = capital
    mdd = 0.0
    for t in sorted(trades, key=lambda x: x["exit_ts"]):
        eq += t["net_pnl_usd"]
        peak = max(peak, eq)
        if peak > 0:
            mdd = max(mdd, (peak - eq) / peak)
    return round(mdd * 100, 4)


def _side_stats(trades, side):
    s = [t for t in trades if t["direction"] == side]
    net = sum(t["net_pnl_usd"] for t in s)
    return {"n": len(s), "net_pnl_usd": round(net, 4)}


def _classify(n, net, pf, exp, mdd, conc, long_s, short_s) -> str:
    if n < MIN_SIGNALS:
        return "insufficient_data"
    if net <= 0 or pf is None or pf < PF_MIN or exp <= 0:
        return "no_edge"
    strong = (mdd <= MAXDD_LIMIT_PCT and conc is not None
              and conc < CONCENTRATION_MAX and long_s["net_pnl_usd"] > 0
              and short_s["net_pnl_usd"] > 0)
    return "candidate_for_demo_review" if strong else "promising_shadow"


def build_shadow_report(shadow: Dict[str, Any], ticks: Sequence[Tick], *,
                        capital: float = 5000.0) -> Dict[str, Any]:
    trades = shadow.get("trades", [])
    sig = shadow.get("signals", {})
    nets = [t["net_pnl_usd"] for t in trades]
    n = len(trades)
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    net = round(sum(nets), 4)
    gross = round(sum(t["gross_pnl_usd"] for t in trades), 4)
    fees = round(sum(t["fees_usd"] for t in trades), 4)
    slip = round(sum(t["slippage_usd"] for t in trades), 4)
    pf = (round(sum(wins) / -sum(losses), 4) if losses
          else (None if not wins else float("inf")))
    exp = round(net / n, 4) if n else 0.0
    mdd = _maxdd_pct(trades, capital) if trades else 0.0
    gross_win = sum(wins)
    top3 = sum(sorted(wins, reverse=True)[:3])
    conc = round(top3 / gross_win, 4) if gross_win > 0 else None
    long_s, short_s = _side_stats(trades, "long"), _side_stats(trades, "short")
    by_reason: Dict[str, int] = {}
    for t in trades:
        by_reason[t["exit_reason"]] = by_reason.get(t["exit_reason"], 0) + 1
    cls = (_classify(n, net, pf, exp, mdd, conc, long_s, short_s)
           if shadow.get("status") == "ok" else "insufficient_data")
    return {
        "schema": "microstructure_phase63_shadow_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": shadow.get("status"),
        "warmup_seconds_collected": shadow.get("warmup_seconds_collected"),
        "config_calibrated": shadow.get("config_calibrated"),
        "signals": sig,
        "fills_simulated": n, "fills_long": long_s["n"],
        "fills_short": short_s["n"], "exit_reasons": by_reason,
        "gross_pnl_usd": gross, "net_pnl_usd": net, "fees_usd": fees,
        "slippage_usd": slip,
        "profit_factor_net": pf, "expectancy_net_usd": exp,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "max_drawdown_pct_shadow": mdd,
        "avg_hold_seconds": round(statistics.mean(
            [t["hold_seconds"] for t in trades]), 2) if trades else None,
        "long_side": long_s, "short_side": short_s,
        "top3_winners_share_of_gross_profit": conc,
        "costs_explain_all_profit": (net <= 0),
        "classification": cls,
        "promising_criteria": {"min_signals": MIN_SIGNALS, "pf_min": PF_MIN,
                               "maxdd_limit_pct": MAXDD_LIMIT_PCT,
                               "concentration_max": CONCENTRATION_MAX},
        "real_execution_allowed": False, "orders_emitted": 0,
        "demo_blocked": True, "live_blocked": True, "oos_untouched": True,
        "decision": ("pedir_aprovacao_antes_de_demo"
                     if cls == "candidate_for_demo_review"
                     else ("coletar_mais_dados" if cls == "insufficient_data"
                           else "rejeitar")),
    }


__all__ = ["build_data_quality", "build_shadow_report", "MIN_SIGNALS"]
