"""
Detectores das hipoteses NORMAIS (FASE 53 re-escopo). Dados: OHLCV + volume +
open interest + calendario. Params FIXOS (sem grid; sem tuning na VAL). Causal/
anti-lookahead. Reusa Setup + _mk_setup; executados por PerpSetupStrategy com
saida por TEMPO (max_holding_candles) + stop estrutural ATR (piso/RiskEngine
soberanos). Stop dentro de [min_stop, max_stop] (senao o setup e descartado).

H1 seasonality_session_bias: vies causal por bucket de hora UTC (expanding mean
   de retornos ja realizados; direcao = sinal do bucket).
H2 volume_climax_reversal: z-score de volume extremo (climax) => reversao do
   movimento do candle de climax.
H3 oi_divergence_exhaustion: preco estendido + OI CAINDO (cobertura) => fade.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.mtf_setups import Setup, _f

_PISO = 0.005
_MIN_STOP, _MAX_STOP = 0.005, 0.05


def _mk_setup(candles, i, direction, entry, stop, rr, atr_i, interval, tag):
    if direction == "long":
        dist = entry - stop
        target = entry + rr * dist
    else:
        dist = stop - entry
        target = entry - rr * dist
    if dist <= 0 or entry <= 0:
        return None
    dist_pct = dist / entry
    if dist_pct < _MIN_STOP or dist_pct > _MAX_STOP:
        return None
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i,
                 setup_id=f"{tag}_{i}")


def _atr(candles) -> List[float]:
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    return [_f(x) for x in FeatureEngine().compute(list(candles))["atr_14"]]


# ----------------------------- H1 ------------------------------------------
def detect_seasonality_session_bias(
    candles: Sequence, *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"hold_bars": 6, "min_samples": 30, "stop_atr": 3.0, "rr": 1.5,
         **(params or {})}
    hold = int(p["hold_bars"]); min_s = int(p["min_samples"])
    katr = float(p["stop_atr"]); rr = float(p["rr"])
    closes = [float(c.close) for c in candles]
    atr = _atr(candles)
    n = len(closes)
    sums: Dict[int, float] = {}
    cnts: Dict[int, int] = {}
    retired = 0                                   # entradas ja "fechadas"
    out: List[Setup] = []
    for i in range(n):
        # retira entradas cujo hold ja fechou (<= i) => bucket causal
        while retired + hold <= i:
            j = retired
            if closes[j] > 0 and closes[j + hold] > 0:
                h = candles[j].timestamp.hour
                sums[h] = sums.get(h, 0.0) + (closes[j + hold] / closes[j] - 1.0)
                cnts[h] = cnts.get(h, 0) + 1
            retired += 1
        a = atr[i]
        if i < 55 or math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        h = candles[i].timestamp.hour
        if cnts.get(h, 0) < min_s:
            continue
        mean = sums[h] / cnts[h]
        if mean == 0:
            continue
        direction = "long" if mean > 0 else "short"
        c = closes[i]
        stop = c - katr * a if direction == "long" else c + katr * a
        s = _mk_setup(candles, i, direction, c, stop, rr, a, interval_minutes,
                      "H1season")
        if s is not None:
            out.append(s)
    return out


# ----------------------------- H2 ------------------------------------------
def detect_volume_climax_reversal(
    candles: Sequence, *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"vol_z_window": 50, "vol_z_trigger": 3.0, "stop_atr": 1.5, "rr": 1.5,
         **(params or {})}
    win = int(p["vol_z_window"]); trig = float(p["vol_z_trigger"])
    katr = float(p["stop_atr"]); rr = float(p["rr"])
    closes = [float(c.close) for c in candles]
    opens = [float(c.open) for c in candles]
    vols = [float(c.volume) for c in candles]
    atr = _atr(candles)
    n = len(closes)
    out: List[Setup] = []
    for i in range(max(win, 55), n):
        w = vols[i - win:i]                        # janela PASSADA (causal)
        mu = sum(w) / win
        sd = math.sqrt(sum((x - mu) ** 2 for x in w) / win)
        a = atr[i]
        if sd <= 0 or math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        z = (vols[i] - mu) / sd
        if z < trig:
            continue
        # climax de alta => fade SHORT; climax de baixa => fade LONG
        direction = "short" if closes[i] >= opens[i] else "long"
        c = closes[i]
        stop = c - katr * a if direction == "long" else c + katr * a
        s = _mk_setup(candles, i, direction, c, stop, rr, a, interval_minutes,
                      "H2vclimax")
        if s is not None:
            out.append(s)
    return out


# ----------------------------- H3 ------------------------------------------
def detect_oi_divergence_exhaustion(
    candles: Sequence, oi_change: Sequence[Optional[float]], *,
    interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"ext_lookback": 50, "ext_hi": 0.8, "ext_lo": 0.2, "stop_atr": 2.0,
         "rr": 1.5, "divergence_min": 0.0, **(params or {})}
    lb = int(p["ext_lookback"]); ehi = float(p["ext_hi"]); elo = float(p["ext_lo"])
    katr = float(p["stop_atr"]); rr = float(p["rr"]); dmin = float(p["divergence_min"])
    closes = [float(c.close) for c in candles]
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    atr = _atr(candles)
    n = len(closes)
    out: List[Setup] = []
    for i in range(max(lb, 55), n):
        oc = oi_change[i] if i < len(oi_change) else None
        a = atr[i]
        if oc is None or math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        hi = max(highs[i - lb:i + 1]); lo = min(lows[i - lb:i + 1])
        if hi <= lo:
            continue
        rpos = (closes[i] - lo) / (hi - lo)
        c = closes[i]
        direction = None
        # OI CAINDO (cobertura, sem dinheiro novo) + preco estendido => fade
        if oc < -dmin and rpos >= ehi:
            direction = "short"
            stop = c + katr * a
        elif oc < -dmin and rpos <= elo:
            direction = "long"
            stop = c - katr * a
        else:
            continue
        s = _mk_setup(candles, i, direction, c, stop, rr, a, interval_minutes,
                      "H3oidiv")
        if s is not None:
            out.append(s)
    return out


DETECTORS = {
    "seasonality_session_bias": detect_seasonality_session_bias,
    "volume_climax_reversal": detect_volume_climax_reversal,
    "oi_divergence_exhaustion": detect_oi_divergence_exhaustion,
}
HOLD_BARS = {"seasonality_session_bias": 6, "volume_climax_reversal": 8,
             "oi_divergence_exhaustion": 12}

__all__ = ["DETECTORS", "HOLD_BARS", "detect_seasonality_session_bias",
           "detect_volume_climax_reversal", "detect_oi_divergence_exhaustion"]
