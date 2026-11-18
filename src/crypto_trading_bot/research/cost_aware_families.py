"""
Cost-aware families (FASE 48) — horizonte 4h, baixo turnover, stops largos +
alvos grandes (R alto), p/ que o custo (26 bps round-trip) seja fracao pequena
do risco (cost_in_R = 26bps/stop_dist). DIFERENTES das rejeitadas (38-47):
horizonte 4h/diario, alvo >=2,5-3R, gate de regime FORTE, e filtro de
viabilidade (min_stop_dist) que descarta setups de stop apertado (caros).

F3 — HTF Trend Continuation: em tendencia 4h FORTE (EMA-slope), rompimento de
   canal (Donchian) na direcao da tendencia; stop estrutural LARGO; alvo 3R.
   ("continuation em regime forte com alvo maior").
F4 — Volatility Expansion Continuation multi-TF: squeeze de bb_bandwidth no 4h
   -> expansao + rompimento, CONFIRMADO pela tendencia DIARIA (multi-TF); alvo
   2,5R; stop estrutural largo. ("volatility expansion com confirmacao MTF").

Determinístico, params FIXOS, anti-lookahead (setup em i usa so <=i; direcao
diaria alinhada causal por close_time). Execucao reusa PerpSetupStrategy. Piso
0,5% e RiskEngine soberanos (below_floor so marca).
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.htf_regime_filter import _ts_key
from crypto_trading_bot.research.mtf_setups import Setup, _f

_PISO = 0.005

# Geometria calibrada ao SWEET SPOT de custo: stop em [min_stop_dist,
# max_stop_dist] = [1,5%, 5%] (5% = teto max_stop_loss_pct do RiskEngine;
# acima disso o RiskEngine bloqueia). Donchian/ATR menores p/ caber no teto.
F3_PARAMS = {"ema_period": 50, "slope_k": 6, "slope_threshold": 0.004,
             "donchian": 10, "atr_buffer": 0.5, "risk_reward": 3.0,
             "min_stop_dist": 0.015, "max_stop_dist": 0.05}
F4_PARAMS = {"bw_window": 60, "squeeze_pctile": 0.25, "expansion_factor": 1.2,
             "swing_lookback": 10, "atr_buffer": 0.5, "risk_reward": 2.5,
             "min_stop_dist": 0.015, "max_stop_dist": 0.05}


def _mk_setup(candles, i, direction, entry, stop, rr, atr_i, interval, tag,
              min_stop_dist, max_stop_dist=0.05):
    if direction == "long":
        dist = entry - stop
        target = entry + rr * dist
    else:
        dist = stop - entry
        target = entry - rr * dist
    if dist <= 0 or entry <= 0:
        return None
    dist_pct = dist / entry
    if dist_pct < min_stop_dist:
        return None                  # cost-aware: descarta stop apertado (caro)
    if dist_pct > max_stop_dist:
        return None                  # acima do teto 5% => RiskEngine bloqueia
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i,
                 setup_id=f"{tag}_{i}")


def _feats(candles):
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    f = FeatureEngine().compute(list(candles))
    return ([_f(x) for x in f["closes"]], [_f(x) for x in f["highs"]],
            [_f(x) for x in f["lows"]], [_f(x) for x in f["atr_14"]], f)


def detect_f3_htf_trend_continuation(
    candles_4h: Sequence, *, interval_minutes: int = 240,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    """F3: tendencia 4h forte (EMA-slope) + rompimento de canal Donchian na
    direcao; stop largo; alvo 3R. Baixo turnover."""
    from crypto_trading_bot.research.htf_direction import ema_slope_direction
    if not candles_4h:
        return []
    p = {**F3_PARAMS, **(params or {})}
    closes, highs, lows, atr, _f0 = _feats(candles_4h)
    n = len(closes)
    direction = ema_slope_direction(
        candles_4h, ema_period=int(p["ema_period"]), slope_k=int(p["slope_k"]),
        threshold=float(p["slope_threshold"]))
    dc = int(p["donchian"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"]); msd = float(p["min_stop_dist"])
    xsd = float(p["max_stop_dist"])
    out: List[Setup] = []
    start = max(dc, int(p["ema_period"]) + int(p["slope_k"]), 55)
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        d = direction[i]
        if d is None:
            continue
        hi_ch = max(highs[i - dc:i]); lo_ch = min(lows[i - dc:i])
        c = closes[i]
        if d == "trend_up" and c > hi_ch:
            stop = lo_ch - buf * a
            s = _mk_setup(candles_4h, i, "long", c, stop, rr, a,
                          interval_minutes, "F3", msd, xsd)
        elif d == "trend_down" and c < lo_ch:
            stop = hi_ch + buf * a
            s = _mk_setup(candles_4h, i, "short", c, stop, rr, a,
                          interval_minutes, "F3", msd, xsd)
        else:
            continue
        if s is not None:
            out.append(s)
    return out


def detect_f4_vol_expansion_continuation(
    candles_4h: Sequence, daily_direction_map: Optional[Dict[Any, Any]] = None,
    *, interval_minutes: int = 240,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    """F4: squeeze de bb_bandwidth (percentil baixo) -> expansao + rompimento
    de swing, CONFIRMADO pela tendencia DIARIA (multi-TF). Alvo 2,5R; stop
    largo. daily_direction_map: {ts_key(open_4h) -> 'trend_up'|'trend_down'|
    None} (causal). Se None, sem filtro MTF (usado em teste)."""
    from crypto_trading_bot.research.perp_signals import (
        causal_percentile_rank)
    if not candles_4h:
        return []
    p = {**F4_PARAMS, **(params or {})}
    closes, highs, lows, atr, feats = _feats(candles_4h)
    n = len(closes)
    bw_raw = feats.get("bb_bandwidth")
    if bw_raw is None:
        return []
    bw = [_f(x) for x in bw_raw]
    bw_pctile = causal_percentile_rank(
        [None if math.isnan(x) else x for x in bw],
        window=int(p["bw_window"]))
    sw = int(p["swing_lookback"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"]); ef = float(p["expansion_factor"])
    sq = float(p["squeeze_pctile"]); msd = float(p["min_stop_dist"])
    xsd = float(p["max_stop_dist"])
    out: List[Setup] = []
    start = max(sw, int(p["bw_window"]), 55)
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        if math.isnan(bw[i]) or math.isnan(bw[i - 1]):
            continue
        # squeeze recente (percentil baixo) + expansao agora
        recent_squeeze = any(
            (bw_pctile[j] is not None and bw_pctile[j] <= sq)
            for j in range(max(0, i - 5), i))
        expanding = bw[i] > ef * bw[i - 1]
        if not (recent_squeeze and expanding):
            continue
        d_daily = (daily_direction_map.get(_ts_key(candles_4h[i].timestamp))
                   if daily_direction_map is not None else None)
        hi_ch = max(highs[i - sw:i]); lo_ch = min(lows[i - sw:i])
        c = closes[i]
        long_ok = c > hi_ch and (daily_direction_map is None
                                 or d_daily == "trend_up")
        short_ok = c < lo_ch and (daily_direction_map is None
                                  or d_daily == "trend_down")
        if long_ok:
            stop = lo_ch - buf * a
            s = _mk_setup(candles_4h, i, "long", c, stop, rr, a,
                          interval_minutes, "F4", msd, xsd)
        elif short_ok:
            stop = hi_ch + buf * a
            s = _mk_setup(candles_4h, i, "short", c, stop, rr, a,
                          interval_minutes, "F4", msd, xsd)
        else:
            continue
        if s is not None:
            out.append(s)
    return out


__all__ = ["F3_PARAMS", "F4_PARAMS",
           "detect_f3_htf_trend_continuation",
           "detect_f4_vol_expansion_continuation"]
