"""
HyroTrader Challenge Evaluation (FASE 47) — overlay de reporting
=================================================================
Sobre a sequencia de trades (realizados, PnL liquido incl. fees + funding)
calcula e REGISTRA as regras HyroTrader + controles internos que o RiskEngine
NAO suporta, separando **enforced-by-RiskEngine vs simulado-no-overlay vs
not_supported**:

Externas HyroTrader: drawdown diario TRAILING pelo pico de equity intradiario
(reset UTC); perda total / equity minimo 4700; concentracao <=40% do lucro em
1 dia; minimo 5 dias; stop obrigatorio.
Controles internos: 2 perdas consecutivas => cooldown 15min; perda de sessao
1%; kill switch US$50.

⚠️ O verdict "passaria no desafio?" NAO pode ignorar esses controles: se
algum estiver `not_supported`, o verdict sai `incompleto_controles_internos_
ausentes` (nunca um "passaria" limpo). Overlay de RELATORIO; nao enforce no
engine; RiskEngine/ModeGuard/piso intactos.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ----------------------------- normalizacao -------------------------------

def _attr(obj, name, default=None):
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_utc(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    return None


@dataclass(frozen=True)
class _Trade:
    entry_time: Optional[datetime]
    exit_time: Optional[datetime]
    pnl_usd: float
    has_stop: bool


def _normalize(trades: Sequence) -> List[_Trade]:
    out: List[_Trade] = []
    for t in (trades or []):
        ein = _as_utc(_attr(t, "entry_time"))
        exo = _as_utc(_attr(t, "exit_time")) or ein
        pnl = float(_attr(t, "pnl_usd", 0.0) or 0.0)
        stop = _attr(t, "stop_loss", _attr(t, "stop_price", None))
        has_stop = stop is not None
        out.append(_Trade(entry_time=ein, exit_time=exo, pnl_usd=pnl,
                          has_stop=has_stop))
    # ordena por saida (realizacao); entradas sem ts vao ao fim de forma estavel
    out.sort(key=lambda x: (x.exit_time or datetime.max.replace(
        tzinfo=timezone.utc)))
    return out


def _utc_day(ts: Optional[datetime]) -> Optional[str]:
    return ts.date().isoformat() if ts else None


# ----------------------------- regras externas ----------------------------

def _daily_trailing_drawdown(trades: List[_Trade], *, capital: float,
                             daily_limit_usd: float) -> Dict[str, Any]:
    """DD diario TRAILING pelo pico de equity intradiario (reset UTC).

    Equity = capital + PnL realizado acumulado. O pico reinicia a cada dia
    UTC pelo valor de abertura do dia; viola se em algum fechamento de trade
    (pico_intradia - equity) >= daily_limit_usd. NOTA: usa equity REALIZADA
    (marcacao por fechamento de trade); unrealized intraday e aproximado
    (flag) — exato exigiria equity por candle."""
    equity = capital
    cur_day: Optional[str] = None
    day_peak = capital
    worst = 0.0
    breached = False
    breach_day = None
    by_day_dd: Dict[str, float] = {}
    for t in trades:
        day = _utc_day(t.exit_time)
        if day != cur_day:
            cur_day = day
            day_peak = equity            # abre o dia no equity corrente
        equity += t.pnl_usd
        day_peak = max(day_peak, equity)
        drop = day_peak - equity
        if day is not None:
            by_day_dd[day] = max(by_day_dd.get(day, 0.0), drop)
        if drop > worst:
            worst = drop
        if drop >= daily_limit_usd and not breached:
            breached = True
            breach_day = day
    return {
        "limit_usd": round(daily_limit_usd, 2),
        "worst_daily_drawdown_usd": round(worst, 2),
        "breached": breached,
        "breach_day": breach_day,
        "by_day_max_dd_usd": {k: round(v, 2) for k, v in by_day_dd.items()},
        "unrealized_intraday_approximated": True,
    }


def _total_loss(trades: List[_Trade], *, capital: float,
                min_equity_usd: float) -> Dict[str, Any]:
    equity = capital
    min_equity = capital
    breached = False
    for t in trades:
        equity += t.pnl_usd
        min_equity = min(min_equity, equity)
        if equity <= min_equity_usd:
            breached = True
    return {
        "min_equity_floor_usd": round(min_equity_usd, 2),
        "min_equity_reached_usd": round(min_equity, 2),
        "breached": breached,
    }


def _daily_nets(trades: List[_Trade]) -> Dict[str, float]:
    by_day: Dict[str, float] = {}
    for t in trades:
        day = _utc_day(t.exit_time)
        if day is None:
            continue
        by_day[day] = by_day.get(day, 0.0) + t.pnl_usd
    return by_day


def _concentration(trades: List[_Trade], *, max_pct: float) -> Dict[str, Any]:
    by_day = _daily_nets(trades)
    profit_days = {d: v for d, v in by_day.items() if v > 0}
    total_profit = sum(profit_days.values())
    if total_profit <= 0:
        return {"max_pct": max_pct, "max_day_share": None,
                "breached": False, "reason": "sem lucro liquido positivo"}
    top_day, top_val = max(profit_days.items(), key=lambda kv: kv[1])
    share = top_val / total_profit
    return {
        "max_pct": max_pct,
        "max_day": top_day,
        "max_day_share": round(share, 4),
        "breached": share > max_pct,
    }


# ----------------------------- controles internos --------------------------

def _consecutive_losses_cooldown(
    trades: List[_Trade], *, threshold: int, cooldown_minutes: int,
) -> Dict[str, Any]:
    """Simula: ao atingir `threshold` perdas consecutivas, bloqueia novas
    entradas por `cooldown_minutes`. Conta trades que SERIAM bloqueados."""
    streak = 0
    cooldown_until: Optional[datetime] = None
    blocked = 0
    for t in trades:
        if cooldown_until is not None and t.entry_time is not None \
                and t.entry_time < cooldown_until:
            blocked += 1
            continue
        if t.pnl_usd < 0:
            streak += 1
            if streak >= threshold and t.exit_time is not None:
                cooldown_until = t.exit_time + timedelta(
                    minutes=cooldown_minutes)
                streak = 0
        else:
            streak = 0
    return {"status": "simulated", "threshold": threshold,
            "cooldown_minutes": cooldown_minutes,
            "would_be_blocked_trades": blocked}


def _session_loss(trades: List[_Trade], *, capital: float,
                  pct: float) -> Dict[str, Any]:
    """Simula perda maxima por SESSAO. Sem conceito nativo de sessao no
    backtest, usamos o DIA UTC como proxy de sessao (documentado): ao
    acumular perda >= pct*capital no dia, bloqueia o resto do dia."""
    limit = pct * capital
    cur_day: Optional[str] = None
    day_pnl = 0.0
    tripped = False
    blocked = 0
    days_tripped = set()
    for t in trades:
        day = _utc_day(t.exit_time)
        if day != cur_day:
            cur_day = day
            day_pnl = 0.0
            tripped = False
        if tripped:
            blocked += 1
            continue
        day_pnl += t.pnl_usd
        if -day_pnl >= limit:
            tripped = True
            if day is not None:
                days_tripped.add(day)
    return {"status": "simulated", "pct": pct, "limit_usd": round(limit, 2),
            "session_proxy": "utc_day",
            "would_be_blocked_trades": blocked,
            "sessions_tripped": sorted(days_tripped)}


def _kill_switch(trades: List[_Trade], *, limit_usd: float) -> Dict[str, Any]:
    """Simula kill switch por dia UTC: ao acumular perda >= limit_usd no dia,
    bloqueia o resto do dia. Conta trades bloqueados."""
    cur_day: Optional[str] = None
    day_loss = 0.0
    tripped = False
    blocked = 0
    days_tripped = set()
    for t in trades:
        day = _utc_day(t.exit_time)
        if day != cur_day:
            cur_day = day
            day_loss = 0.0
            tripped = False
        if tripped:
            blocked += 1
            continue
        day_loss += t.pnl_usd
        if -day_loss >= limit_usd:
            tripped = True
            if day is not None:
                days_tripped.add(day)
    return {"status": "simulated", "limit_usd": limit_usd,
            "would_be_blocked_trades": blocked,
            "days_tripped": sorted(days_tripped)}


# ----------------------------- avaliacao ----------------------------------

@dataclass(frozen=True)
class HyroTraderReport:
    schema: str
    capital: float
    external_rules: Mapping[str, Any]
    internal_controls: Mapping[str, Any]
    challenge_verdict: str
    enforcement_map: Mapping[str, str]

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "capital": self.capital,
            "external_rules": dict(self.external_rules),
            "internal_controls": dict(self.internal_controls),
            "challenge_verdict": self.challenge_verdict,
            "enforcement_map": dict(self.enforcement_map),
            "note": ("Overlay de relatorio; nao enforce no engine. RiskEngine "
                     "soberano (0,5%) intacto. 'passaria' so se todas as "
                     "regras passarem E nenhum controle interno estiver "
                     "not_supported."),
        }


def evaluate_hyrotrader_challenge(
    trades: Sequence, *, capital: float = 5000.0,
    daily_drawdown_pct: float = 0.04,
    total_loss_pct: float = 0.06,
    min_equity_usd: Optional[float] = None,
    concentration_max_pct: float = 0.40,
    min_days: int = 5,
    internal_controls: Optional[Mapping[str, Any]] = None,
    require_mandatory_stop: bool = True,
    profit_target_pct: float = 0.10,
) -> HyroTraderReport:
    """Avalia se a sequencia de trades 'passaria no desafio' HyroTrader.

    `internal_controls`: dict opcional {consecutive_losses, cooldown_minutes,
    session_loss_pct, kill_switch_usd} (origem effective_config). session_loss
    e marcado `not_supported` (sem conceito de sessao no backtest).
    """
    tr = _normalize(trades)
    daily_limit = daily_drawdown_pct * capital
    if min_equity_usd is None:
        min_equity_usd = capital * (1.0 - total_loss_pct)

    dd = _daily_trailing_drawdown(tr, capital=capital,
                                  daily_limit_usd=daily_limit)
    tl = _total_loss(tr, capital=capital, min_equity_usd=min_equity_usd)
    conc = _concentration(tr, max_pct=concentration_max_pct)
    days = sorted({d for d in (_utc_day(t.exit_time) for t in tr) if d})
    n_days = len(days)
    min_days_ok = n_days >= min_days
    # meta de lucro (net incl. funding — os trades ja vem com funding aplicado
    # quando chamado pelo standard_report): so 'passaria' se ATINGIR a meta.
    net_total = round(sum(t.pnl_usd for t in tr), 4)
    target_usd = round(profit_target_pct * capital, 2)
    target_reached = net_total >= target_usd
    # stop obrigatorio: se nenhum trade carrega stop, nao da p/ comprovar
    n_with_stop = sum(1 for t in tr if t.has_stop)
    if not tr:
        stop_status = "no_trades"
    elif n_with_stop == len(tr):
        stop_status = "all_trades_have_stop"
    elif n_with_stop == 0:
        stop_status = "unverifiable_no_stop_field"
    else:
        stop_status = "partial"

    external = {
        "daily_drawdown_trailing": dd,
        "total_loss": tl,
        "concentration": conc,
        "min_days": {"required": min_days, "observed": n_days,
                     "ok": min_days_ok},
        "mandatory_stop": {"required": require_mandatory_stop,
                           "status": stop_status},
        "profit_target": {"required_usd": target_usd,
                          "net_pnl_usd_incl_funding": net_total,
                          "reached": target_reached,
                          "note": "passar no desafio EXIGE atingir a meta "
                                  "(net apos fees+spread+slippage+funding)"},
    }

    # controles internos
    ic_cfg = dict(internal_controls or {})

    def _ival(key, default):
        v = ic_cfg.get(key)
        if isinstance(v, Mapping):
            v = v.get("value")
        return v if v is not None else default

    cons = int(_ival("consecutive_losses", 2))
    cd = int(_ival("cooldown_minutes", 15))
    ks = float(_ival("kill_switch_usd", 50.0))
    sess_pct = float(_ival("session_loss_pct", 0.01))

    internal = {
        "consecutive_losses_cooldown": _consecutive_losses_cooldown(
            tr, threshold=cons, cooldown_minutes=cd),
        "kill_switch": _kill_switch(tr, limit_usd=ks),
        "session_loss": _session_loss(tr, capital=capital, pct=sess_pct),
    }

    enforcement_map = {
        "max_risk_per_trade_0.5pct": "enforced_by_riskengine",
        "max_daily_loss / max_total_loss": "enforced_by_riskengine",
        "max_leverage / max_open_positions": "enforced_by_riskengine",
        "min_stop_loss_0.5pct": "enforced_by_riskengine",
        "daily_drawdown_trailing_intraday": "simulated_overlay",
        "total_loss_min_equity": "simulated_overlay",
        "concentration_40pct_day": "simulated_overlay",
        "min_5_days": "simulated_overlay",
        "consecutive_losses_cooldown": "simulated_overlay",
        "kill_switch_usd": "simulated_overlay",
        "session_loss_1pct": "simulated_overlay",
    }

    # verdict do desafio: SOBREVIVE as regras de risco?
    survives = (not dd["breached"] and not tl["breached"]
                and not conc["breached"] and min_days_ok
                and (not require_mandatory_stop
                     or stop_status in ("all_trades_have_stop",)))
    # PASSAR no desafio = sobreviver E ATINGIR a meta de lucro.
    hard_pass = survives and target_reached
    not_supported = [k for k in internal
                     if internal[k].get("status") == "not_supported"]
    if not tr:
        verdict = "sem_trades"
    elif not_supported:
        verdict = "incompleto_controles_internos_ausentes"
    elif hard_pass:
        verdict = "passaria_no_desafio"
    elif survives and not target_reached:
        # nao foi eliminado, mas NAO bateu a meta => nao passa o desafio
        verdict = "reprovaria_no_desafio_meta_nao_atingida"
    else:
        verdict = "reprovaria_no_desafio"

    return HyroTraderReport(
        schema="hyrotrader_challenge_v1", capital=capital,
        external_rules=external, internal_controls=internal,
        challenge_verdict=verdict, enforcement_map=enforcement_map,
    )


__all__ = ["HyroTraderReport", "evaluate_hyrotrader_challenge"]
