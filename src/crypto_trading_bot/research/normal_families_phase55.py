"""
Detectores FASE 55 — hipoteses NORMAIS CONDICIONADAS (regime + filtro de vol +
confirmacao OI/funding), baixo turnover. Causal/anti-lookahead. Params FIXOS.
Reusa Setup + PerpSetupStrategy (saida por tempo via max_holding_candles; stop
estrutural; piso/RiskEngine soberanos).
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.mtf_setups import Setup, _f
from crypto_trading_bot.research.normal_families import _atr
from crypto_trading_bot.research.perp_signals import causal_percentile_rank

_PISO = 0.005
_MIN_STOP, _MAX_STOP = 0.005, 0.05


def _ema(series: Sequence[float], period: int) -> List[float]:
    out: List[float] = []
    k = 2.0 / (period + 1)
    prev: Optional[float] = None
    for v in series:
        prev = v if prev is None else (v - prev) * k + prev
        out.append(prev)
    return out


def _mk(candles, i, direction, entry, stop, target, atr_i, interval, tag):
    """Setup com stop+target EXPLICITOS (valida dist no piso/cap)."""
    dist = (entry - stop) if direction == "long" else (stop - entry)
    if dist <= 0 or entry <= 0:
        return None
    # alvo deve estar do lado certo
    if direction == "long" and target <= entry:
        return None
    if direction == "short" and target >= entry:
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
                 below_floor=dist_pct < _PISO, atr=atr_i, setup_id=f"{tag}_{i}")


def _common(candles):
    closes = [float(c.close) for c in candles]
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    opens = [float(c.open) for c in candles]
    atr = _atr(candles)
    atr_pct = [(atr[i] / closes[i]) if (not math.isnan(atr[i]) and closes[i] > 0)
               else None for i in range(len(closes))]
    vol_pct = causal_percentile_rank(atr_pct, window=200)
    return closes, highs, lows, opens, atr, vol_pct


# ----------------------------- H1 ------------------------------------------
def detect_trend_pullback_regime_gated(
    candles: Sequence, *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"ema_fast": 20, "ema_slow": 50, "slope_k": 12, "vol_lo": 0.20,
         "vol_hi": 0.70, "pullback_atr": 0.6, "swing_lookback": 20, "rr": 2.0,
         **(params or {})}
    closes, highs, lows, opens, atr, vol_pct = _common(candles)
    ef = _ema(closes, int(p["ema_fast"]))
    es = _ema(closes, int(p["ema_slow"]))
    k = int(p["slope_k"]); pb = float(p["pullback_atr"])
    sw = int(p["swing_lookback"]); rr = float(p["rr"])
    vlo, vhi = float(p["vol_lo"]), float(p["vol_hi"])
    out: List[Setup] = []
    for i in range(max(210, sw + k), len(closes)):
        a = atr[i]
        vp = vol_pct[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0 or vp is None:
            continue
        if not (vlo <= vp <= vhi):                 # filtro de volatilidade
            continue
        slope = (es[i] - es[i - k]) / es[i - k] if es[i - k] else 0.0
        c = closes[i]
        up = ef[i] > es[i] and slope > 0
        dn = ef[i] < es[i] and slope < 0
        s = None
        if up and abs(c - ef[i]) <= pb * a and c >= ef[i] and c > opens[i]:
            stop = min(lows[i - sw:i + 1]) - 0.25 * a
            s = _mk(candles, i, "long", c, stop, c + rr * (c - stop), a,
                    interval_minutes, "H1tpr")
        elif dn and abs(c - ef[i]) <= pb * a and c <= ef[i] and c < opens[i]:
            stop = max(highs[i - sw:i + 1]) + 0.25 * a
            s = _mk(candles, i, "short", c, stop, c - rr * (stop - c), a,
                    interval_minutes, "H1tpr")
        if s is not None:
            out.append(s)
    return out


# ----------------------------- H2 ------------------------------------------
def detect_range_reversion_regime_gated(
    candles: Sequence, *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"ema_fast": 20, "ema_slow": 50, "flat_thr": 0.0035, "vol_max": 0.40,
         "ch_lookback": 24, "hi": 0.85, "lo": 0.15, **(params or {})}
    closes, highs, lows, opens, atr, vol_pct = _common(candles)
    ef = _ema(closes, int(p["ema_fast"]))
    es = _ema(closes, int(p["ema_slow"]))
    flat = float(p["flat_thr"]); vmax = float(p["vol_max"])
    lb = int(p["ch_lookback"]); hi_t, lo_t = float(p["hi"]), float(p["lo"])
    out: List[Setup] = []
    for i in range(max(210, lb), len(closes)):
        a = atr[i]
        vp = vol_pct[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0 or vp is None:
            continue
        if vp > vmax:                              # so vol comprimida
            continue
        if closes[i] == 0 or abs(ef[i] - es[i]) / closes[i] >= flat:
            continue                               # so regime de range (flat)
        hc = max(highs[i - lb:i + 1]); lc = min(lows[i - lb:i + 1])
        if hc <= lc:
            continue
        mid = (hc + lc) / 2.0
        rpos = (closes[i] - lc) / (hc - lc)
        c = closes[i]
        s = None
        if rpos >= hi_t and mid < c:               # topo do range => short p/ mid
            s = _mk(candles, i, "short", c, hc + 0.25 * a, mid, a,
                    interval_minutes, "H2rrr")
        elif rpos <= lo_t and mid > c:             # fundo => long p/ mid
            s = _mk(candles, i, "long", c, lc - 0.25 * a, mid, a,
                    interval_minutes, "H2rrr")
        if s is not None:
            out.append(s)
    return out


# ----------------------------- H3 ------------------------------------------
def detect_breakout_oi_funding_confirmed(
    candles: Sequence, oi_change: Sequence[Optional[float]],
    funding_pctile: Sequence[Optional[float]], *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {"width_lookback": 50, "squeeze_pct": 0.30, "donch": 20,
         "fund_hi": 0.85, "fund_lo": 0.15, "rr": 2.5, **(params or {})}
    closes, highs, lows, opens, atr, _ = _common(candles)
    dn = int(p["donch"]); sq = float(p["squeeze_pct"]); rr = float(p["rr"])
    fhi, flo = float(p["fund_hi"]), float(p["fund_lo"])
    n = len(closes)
    width = [None] * n                             # largura do canal / preco
    for i in range(dn, n):
        hc = max(highs[i - dn:i]); lc = min(lows[i - dn:i])
        width[i] = (hc - lc) / closes[i] if closes[i] > 0 else None
    width_pct = causal_percentile_rank(width, window=int(p["width_lookback"]))
    out: List[Setup] = []
    for i in range(max(210, dn + 1), n):
        a = atr[i]
        wp = width_pct[i]
        oc = oi_change[i] if i < len(oi_change) else None
        fp = funding_pctile[i] if i < len(funding_pctile) else None
        if (math.isnan(a) or a <= 0 or closes[i] <= 0 or wp is None
                or oc is None or fp is None):
            continue
        if wp > sq:                                # so apos compressao (squeeze)
            continue
        if oc <= 0:                                # exige expansao de OI
            continue
        hc = max(highs[i - dn:i]); lc = min(lows[i - dn:i])
        c = closes[i]
        s = None
        if c > hc and fp < fhi:                    # rompe topo + long nao lotado
            stop = lc - 0.25 * a
            s = _mk(candles, i, "long", c, stop, c + rr * (c - stop), a,
                    interval_minutes, "H3boc")
        elif c < lc and fp > flo:                  # rompe fundo + short nao lotado
            stop = hc + 0.25 * a
            s = _mk(candles, i, "short", c, stop, c - rr * (stop - c), a,
                    interval_minutes, "H3boc")
        if s is not None:
            out.append(s)
    return out


DETECTORS_55 = {
    "trend_pullback_regime_gated": detect_trend_pullback_regime_gated,
    "range_reversion_regime_gated": detect_range_reversion_regime_gated,
    "breakout_oi_funding_confirmed": detect_breakout_oi_funding_confirmed,
}
HOLD_BARS_55 = {"trend_pullback_regime_gated": 48,
                "range_reversion_regime_gated": 24,
                "breakout_oi_funding_confirmed": 48}

__all__ = ["DETECTORS_55", "HOLD_BARS_55",
           "detect_trend_pullback_regime_gated",
           "detect_range_reversion_regime_gated",
           "detect_breakout_oi_funding_confirmed"]
