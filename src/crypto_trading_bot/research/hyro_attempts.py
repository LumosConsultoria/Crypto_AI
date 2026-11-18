"""
Hyro Challenge — simulacao de MULTIPLAS TENTATIVAS sequenciais (FASE 54).
========================================================================
A avaliacao de segmento inteiro (hyrotrader_eval) e diagnostico geral. Para
representar uma prop firm challenge de verdade, simulamos tentativas
SEQUENCIAIS: cada tentativa comeca com capital cheio, consome os trades em
ordem cronologica e termina ao atingir a META (10%) ou violar uma regra
(daily drawdown / max loss / session loss / kill switch / concentracao /
dias minimos / prazo maximo). Apos terminar, a proxima tentativa comeca no
proximo trade elegivel; NUNCA reutiliza trades anteriores ao inicio.

Cada tentativa RESETA capital, drawdown, kill switch, cooldown e metricas.
Custos+funding ja vem embutidos no pnl_usd dos trades. Daily DD por dia UTC.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

# thresholds do verdict (EXPLICITOS e testados)
PASS_RATE_STRONG = 0.50            # >=50% das tentativas passam => passaria
# 0 < pass_rate < 0.50 => fraco/instavel ; passed==0 => falharia


def _as_utc(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    return None


def _utc_day(ts: Optional[datetime]) -> Optional[str]:
    return ts.date().isoformat() if ts else None


def _ival(ic, key, default):
    v = (ic or {}).get(key)
    if isinstance(v, Mapping):
        v = v.get("value")
    return v if v is not None else default


def _attr(t, name, default=None):
    if isinstance(t, Mapping):
        return t.get(name, default)
    return getattr(t, name, default)


def _norm(trades: Sequence) -> List[Dict[str, Any]]:
    out = []
    for t in (trades or []):
        ein = _as_utc(_attr(t, "entry_time"))
        exo = _as_utc(_attr(t, "exit_time")) or ein
        if exo is None:
            continue
        out.append({"entry": ein, "exit": exo,
                    "pnl": float(_attr(t, "pnl_usd", 0.0) or 0.0)})
    out.sort(key=lambda x: x["exit"])
    return out


def _median(xs) -> Optional[float]:
    return round(statistics.median(xs), 4) if xs else None


def _run_one_attempt(trades, start, *, capital, daily_limit, min_equity,
                     session_limit, kill_usd, target_usd, min_days, conc_max,
                     max_dur_days, cd_threshold, cd_minutes):
    equity = capital
    gpeak = capital
    maxdd = 0.0
    start_dt = trades[start]["exit"]
    cur = None
    day_peak = capital
    day_pnl = 0.0
    days: set = set()
    day_net: Dict[str, float] = {}
    streak = 0
    cooldown_until: Optional[datetime] = None
    status = reason = None
    last = start
    j = start
    while j < len(trades):
        t = trades[j]
        if cooldown_until and t["entry"] and t["entry"] < cooldown_until:
            last = j
            j += 1
            continue
        if (max_dur_days is not None and t["exit"] and start_dt
                and (t["exit"] - start_dt).days > max_dur_days):
            status, reason = "failed", "max_duration"
            break
        day = _utc_day(t["exit"])
        if day != cur:
            cur, day_peak, day_pnl = day, equity, 0.0
        equity += t["pnl"]
        last = j
        if day:
            days.add(day)
            day_net[day] = day_net.get(day, 0.0) + t["pnl"]
        day_pnl += t["pnl"]
        gpeak = max(gpeak, equity)
        maxdd = max(maxdd, gpeak - equity)
        day_peak = max(day_peak, equity)
        if day_peak - equity >= daily_limit:
            status, reason = "failed", "daily_drawdown"
            break
        if equity <= min_equity:
            status, reason = "failed", "max_loss"
            break
        if -day_pnl >= session_limit:
            status, reason = "failed", "session_loss"
            break
        if -day_pnl >= kill_usd:
            status, reason = "failed", "kill_switch"
            break
        if t["pnl"] < 0:
            streak += 1
            if streak >= cd_threshold and t["exit"]:
                cooldown_until = t["exit"] + timedelta(minutes=cd_minutes)
                streak = 0
        else:
            streak = 0
        if equity - capital >= target_usd and len(days) >= min_days:
            tp = sum(v for v in day_net.values() if v > 0)
            if tp > 0 and (max(day_net.values()) / tp) > conc_max:
                status, reason = "failed", "concentration"
            else:
                status, reason = "passed", "profit_target_reached"
            break
        j += 1
    if status is None:                       # acabou o segmento
        if equity - capital >= target_usd and len(days) < min_days:
            status, reason = "failed", "min_days_not_met"
        else:
            status, reason = "failed", "segment_ended_without_target"
    end_dt = trades[last]["exit"]
    dur = (end_dt - start_dt).days if (end_dt and start_dt) else None
    rec = {"start_date": _utc_day(start_dt), "end_date": _utc_day(end_dt),
           "status": status, "failure_or_success_reason": reason,
           "net_pnl": round(equity - capital, 2),
           "max_drawdown": round(maxdd, 2), "days_traded": len(days),
           "duration_days": dur}
    return rec, last + 1


def simulate_hyro_attempts(
    funded_trades: Sequence, *, capital: float = 5000.0,
    daily_drawdown_pct: float = 0.04, total_loss_pct: float = 0.06,
    profit_target_pct: float = 0.10, concentration_max_pct: float = 0.40,
    min_days: int = 5, internal_controls: Optional[Mapping[str, Any]] = None,
    max_duration_days: Optional[int] = None) -> Dict[str, Any]:
    trades = _norm(funded_trades)
    cfg = dict(
        capital=capital, daily_limit=daily_drawdown_pct * capital,
        min_equity=capital * (1.0 - total_loss_pct),
        session_limit=float(_ival(internal_controls, "session_loss_pct", 0.01))
        * capital,
        kill_usd=float(_ival(internal_controls, "kill_switch_usd", 50.0)),
        target_usd=profit_target_pct * capital, min_days=min_days,
        conc_max=concentration_max_pct, max_dur_days=max_duration_days,
        cd_threshold=int(_ival(internal_controls, "consecutive_losses", 2)),
        cd_minutes=int(_ival(internal_controls, "cooldown_minutes", 15)))
    if not trades:
        return {"total_attempts": 0, "passed_attempts": 0, "failed_attempts": 0,
                "pass_rate": None, "attempts": [], "failure_reasons": {},
                "hyro_attempts_verdict": "pendente",
                "config": {"profit_target_pct": profit_target_pct,
                           "min_days": min_days,
                           "max_duration_days": max_duration_days},
                "note": "sem trades p/ simular tentativas"}
    attempts: List[Dict[str, Any]] = []
    idx = 0
    while idx < len(trades):
        rec, nxt = _run_one_attempt(trades, idx, **cfg)
        attempts.append(rec)
        idx = nxt if nxt > idx else idx + 1
    passed = [a for a in attempts if a["status"] == "passed"]
    failed = [a for a in attempts if a["status"] != "passed"]
    nets = [a["net_pnl"] for a in attempts]
    pass_rate = round(len(passed) / len(attempts), 4)
    reasons: Dict[str, int] = {}
    for a in failed:
        r = a["failure_or_success_reason"]
        reasons[r] = reasons.get(r, 0) + 1
    if not passed:
        verdict = "falharia"
    elif pass_rate >= PASS_RATE_STRONG:
        verdict = "passaria"
    else:
        verdict = "fraco_instavel"
    best = max(attempts, key=lambda a: a["net_pnl"])
    worst = min(attempts, key=lambda a: a["net_pnl"])
    durs = [a["duration_days"] for a in attempts if a["duration_days"] is not None]
    d2t = [a["duration_days"] for a in passed if a["duration_days"] is not None]
    d2f = [a["duration_days"] for a in failed if a["duration_days"] is not None]
    return {
        "total_attempts": len(attempts),
        "passed_attempts": len(passed),
        "failed_attempts": len(failed),
        "pass_rate": pass_rate,
        "best_attempt": best,
        "worst_attempt": worst,
        "median_net": _median(nets),
        "median_duration_days": _median(durs),
        "median_days_to_target": _median(d2t),
        "median_days_to_failure": _median(d2f),
        "failure_reasons": reasons,
        "attempts": attempts,
        "hyro_attempts_verdict": verdict,
        "config": {"profit_target_pct": profit_target_pct, "min_days": min_days,
                   "daily_drawdown_pct": daily_drawdown_pct,
                   "total_loss_pct": total_loss_pct,
                   "concentration_max_pct": concentration_max_pct,
                   "max_duration_days": max_duration_days,
                   "pass_rate_strong_threshold": PASS_RATE_STRONG},
        "note": ("tentativas sequenciais; cada uma reseta capital/DD/kill/"
                 "cooldown; verdict: 0 passa=falharia; pass_rate>=0,50=passaria;"
                 " senao fraco_instavel."),
    }


__all__ = ["simulate_hyro_attempts", "PASS_RATE_STRONG"]
