"""
Shadow executor (FASE 63) — SIMULA entrada/saida (fill/spread/slippage/PnL).
NUNCA envia ordem (orders_emitted=0); nenhum endpoint privado/de ordem. Risco:
0,5%/5k, 1 posicao, 1x, hard_stop SOBERANO min 0,5% (nunca alargado), soft_exit
por fluxo/tempo, cooldown apos loss, max trades/hora. Walk causal nos ticks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.microstructure import features as F
from crypto_trading_bot.microstructure.models import (
    RiskParams, ShadowTrade, Tick)
from crypto_trading_bot.microstructure.signal_engine import (
    ScalperConfig, SignalEngine, calibrate)


@dataclass(frozen=True)
class ShadowConfig:
    max_hold_seconds: float = 120.0
    cooldown_after_loss_seconds: float = 60.0
    max_trades_per_hour: int = 30
    tp_spread_mult: float = 4.0          # TP = mult * spread (curto)
    tp_min_pct: float = 0.0008           # piso de TP 8 bps


def _bid_ask(book):
    b, a = book.best_bid(), book.best_ask()
    return (b[0] if b else None, a[0] if a else None)


def run_shadow(ticks: Sequence[Tick], *, scfg: Optional[ScalperConfig] = None,
               shcfg: Optional[ShadowConfig] = None,
               risk: Optional[RiskParams] = None) -> Dict[str, Any]:
    """Roda o shadow: calibra no warmup, gera sinais, simula. orders_emitted=0."""
    scfg = scfg or ScalperConfig()
    shcfg = shcfg or ShadowConfig()
    risk = risk or RiskParams()
    ticks = sorted(ticks, key=lambda t: t.ts)
    if len(ticks) < 5:
        return {"status": "insufficient_data", "n_ticks": len(ticks),
                "orders_emitted": 0, "trades": [], "signals": _empty_sig(),
                "warmup_seconds_collected": 0.0}
    t0 = ticks[0].ts
    warm_end = t0 + scfg.warmup_seconds
    warm = [t for t in ticks if t.ts <= warm_end]
    live = [t for t in ticks if t.ts > warm_end]
    collected = ticks[-1].ts - t0
    cfg = calibrate(warm, scfg) if len(warm) >= 5 else scfg

    eng = SignalEngine(cfg)
    for t in warm:
        eng.ingest(t)                                # so para warmup do buffer

    sig = {"long": 0, "short": 0, "approved_long": 0, "approved_short": 0,
           "veto_spread": 0, "veto_slippage": 0, "veto_depth": 0,
           "veto_micro_vol": 0, "veto_risk": 0}
    trades: List[ShadowTrade] = []
    entries_ts: List[float] = []
    last_loss_ts: Optional[float] = None
    pos = None                                       # posicao aberta (dict)
    risk_base = risk.risk_pct * risk.capital_usd

    for t in live:
        eng.ingest(t)
        bid, ask = _bid_ask(t.book)
        mid = t.book.mid()
        if mid is None or bid is None or ask is None:
            continue
        # ---- gestao da posicao aberta (saidas) ----
        if pos is not None:
            d = pos["dir"]
            hold = t.ts - pos["entry_ts"]
            ofi10 = F.window_ofi(eng._snaps, t.ts, 10.0)
            ar = F.aggression_ratio(eng._trades, t.ts, 10.0)
            aggr = ar["aggression_ratio"] if ar else None
            reason = None
            # hard_stop SOBERANO (intrabar pelo bid/ask)
            if d == "long" and bid <= pos["stop"]:
                reason, fill = "hard_stop", pos["stop"]
            elif d == "short" and ask >= pos["stop"]:
                reason, fill = "hard_stop", pos["stop"]
            elif d == "long" and bid >= pos["tp"]:
                reason, fill = "tp", bid
            elif d == "short" and ask <= pos["tp"]:
                reason, fill = "tp", ask
            elif ofi10 is not None and ((d == "long" and ofi10 < 0)
                                        or (d == "short" and ofi10 > 0)):
                reason, fill = "soft_ofi", (bid if d == "long" else ask)
            elif aggr is not None and ((d == "long"
                                        and aggr < cfg.aggression_threshold)
                                       or (d == "short" and aggr
                                           > 1 - cfg.aggression_threshold)):
                reason, fill = "soft_aggr", (bid if d == "long" else ask)
            elif hold >= shcfg.max_hold_seconds:
                reason, fill = "soft_time", (bid if d == "long" else ask)
            if reason is not None:
                trades.append(_close(pos, t.ts, fill, reason, risk))
                if trades[-1].net_pnl_usd < 0:
                    last_loss_ts = t.ts
                pos = None
            continue                                  # 1 posicao: nao reentra no msm tick

        # ---- avaliacao de novo sinal (flat) ----
        s = eng.evaluate(t.ts)
        if s is None:
            continue
        sig["long" if s.direction == "long" else "short"] += 1
        for v in s.vetoes:
            sig[f"veto_{v}"] = sig.get(f"veto_{v}", 0) + 1
        if not s.approved:
            continue
        # vetos de RISCO
        entries_ts = [e for e in entries_ts if e > t.ts - 3600]
        if (last_loss_ts is not None
                and t.ts - last_loss_ts < shcfg.cooldown_after_loss_seconds) \
                or len(entries_ts) >= shcfg.max_trades_per_hour:
            sig["veto_risk"] += 1
            continue
        sig["approved_long" if s.direction == "long" else "approved_short"] += 1
        # abre posicao (SHADOW; orders_emitted=0)
        stop_dist = risk.min_hard_stop_pct           # piso soberano 0,5%
        entry_fill = ask if s.direction == "long" else bid   # taker cruza spread
        notional = min(risk_base / stop_dist, risk.capital_usd)  # 1x
        spr_pct = (t.book.spread() or 0.0) / mid if mid else 0.0
        tp_dist = max(shcfg.tp_spread_mult * spr_pct, shcfg.tp_min_pct)
        if s.direction == "long":
            stop = entry_fill * (1 - stop_dist)
            tp = entry_fill * (1 + tp_dist)
        else:
            stop = entry_fill * (1 + stop_dist)
            tp = entry_fill * (1 - tp_dist)
        slip = (s.features.get("slippage_bps") or 0.0)
        pos = {"dir": s.direction, "entry_ts": t.ts, "entry_fill": entry_fill,
               "stop": stop, "tp": tp, "notional": notional, "slip_bps": slip}
        entries_ts.append(t.ts)

    return {"status": "ok", "orders_emitted": 0, "config_calibrated": {
        "imbalance_threshold": cfg.imbalance_threshold,
        "max_spread_bps": cfg.max_spread_bps,
        "aggression_threshold": cfg.aggression_threshold},
        "warmup_seconds_collected": round(collected, 1),
        "n_ticks": len(ticks), "n_live_ticks": len(live),
        "signals": sig, "trades": [tr.to_dict() for tr in trades]}


def _close(pos, exit_ts, exit_fill, reason, risk: RiskParams) -> ShadowTrade:
    d = pos["dir"]
    notional = pos["notional"]
    sign = 1.0 if d == "long" else -1.0
    gross = sign * (exit_fill / pos["entry_fill"] - 1.0) * notional
    fees = 2.0 * (risk.taker_fee_bps / 1e4) * notional       # entrada+saida taker
    slip_usd = (pos.get("slip_bps") or 0.0) / 1e4 * notional
    net = gross - fees - slip_usd
    return ShadowTrade(
        entry_ts=pos["entry_ts"], exit_ts=exit_ts, direction=d,
        entry_fill=round(pos["entry_fill"], 2), exit_fill=round(exit_fill, 2),
        notional_usd=round(notional, 2), stop_price=round(pos["stop"], 2),
        gross_pnl_usd=round(gross, 4), fees_usd=round(fees, 4),
        slippage_usd=round(slip_usd, 4), net_pnl_usd=round(net, 4),
        exit_reason=reason, hold_seconds=round(exit_ts - pos["entry_ts"], 2))


def _empty_sig():
    return {"long": 0, "short": 0, "approved_long": 0, "approved_short": 0,
            "veto_spread": 0, "veto_slippage": 0, "veto_depth": 0,
            "veto_micro_vol": 0, "veto_risk": 0}


__all__ = ["ShadowConfig", "run_shadow"]
