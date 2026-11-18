"""
Funding-Swing Mean-Reversion family (FASE 51) — F5. A UNICA hipotese
sobrevivente da validacao nao-sobreposta (FASE 50).
=====================================================================
F5: no 4h, quando o **funding esta em EXTREMO** (percentil causal alto/baixo),
opera MEAN-REVERSION contra a extensao: funding ALTO => SHORT; funding BAIXO
=> LONG. Stop ESTRUTURAL largo (swing +/- ATR, dentro do teto 5%); alvo
R-multiplo (a saida por TEMPO ~3-7d, no orquestrador via max_holding_candles,
fecha o swing). Reforco OPCIONAL por preco estendido (combinacao que sobreviveu
3d/5d). Baixo turnover.

Difere de F1 funding-fade (INTRADAY 15m): horizonte SWING 3-7d validado SEM
sobreposicao; o que sobrevive e o FUNDING. Determinístico, params FIXOS,
anti-lookahead. Reusa Setup + PerpSetupStrategy + piso/RiskEngine soberanos.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.mtf_setups import Setup, _f

_PISO = 0.005

F5_PARAMS = {"hi_pctile": 0.85, "lo_pctile": 0.15, "swing_lookback": 20,
             "atr_buffer": 0.5, "risk_reward": 1.5, "min_stop_dist": 0.015,
             "max_stop_dist": 0.05, "require_extension": False,
             "ext_hi": 0.80, "ext_lo": 0.20}


def _mk_setup(candles, i, direction, entry, stop, rr, atr_i, interval, tag,
              min_stop_dist, max_stop_dist):
    if direction == "long":
        dist = entry - stop
        target = entry + rr * dist
    else:
        dist = stop - entry
        target = entry - rr * dist
    if dist <= 0 or entry <= 0:
        return None
    dist_pct = dist / entry
    if dist_pct < min_stop_dist or dist_pct > max_stop_dist:
        return None
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i,
                 setup_id=f"{tag}_{i}")


def detect_f5_funding_swing(
    candles_4h: Sequence, funding_pctile: Sequence[Optional[float]], *,
    range_pos: Optional[Sequence[Optional[float]]] = None,
    interval_minutes: int = 240,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    """F5: funding extremo => mean-reversion contra a extensao (causal).
    funding alto (>=hi) => SHORT (stop acima do swing); funding baixo (<=lo)
    => LONG (stop abaixo do swing). Reforco opcional por range_pos."""
    if not candles_4h:
        return []
    p = {**F5_PARAMS, **(params or {})}
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    fe = FeatureEngine().compute(list(candles_4h))
    closes = [_f(x) for x in fe["closes"]]
    highs = [_f(x) for x in fe["highs"]]
    lows = [_f(x) for x in fe["lows"]]
    atr = [_f(x) for x in fe["atr_14"]]
    n = len(closes)
    sw = int(p["swing_lookback"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"]); msd = float(p["min_stop_dist"])
    xsd = float(p["max_stop_dist"])
    hi, lo = float(p["hi_pctile"]), float(p["lo_pctile"])
    req_ext = bool(p["require_extension"])
    ext_hi, ext_lo = float(p["ext_hi"]), float(p["ext_lo"])
    out: List[Setup] = []
    start = max(sw, 55)
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        fp = funding_pctile[i] if i < len(funding_pctile) else None
        if fp is None:
            continue
        c = closes[i]
        # extensao de preco opcional (reforco)
        rpos = (range_pos[i] if (range_pos is not None and i < len(range_pos))
                else None)
        short_ext_ok = (not req_ext) or (rpos is not None and rpos >= ext_hi)
        long_ext_ok = (not req_ext) or (rpos is not None and rpos <= ext_lo)
        if fp >= hi and short_ext_ok:
            # funding alto (crowded long) => SHORT; stop acima do swing recente
            stop = max(highs[i - sw:i + 1]) + buf * a
            s = _mk_setup(candles_4h, i, "short", c, stop, rr, a,
                          interval_minutes, "F5", msd, xsd)
        elif fp <= lo and long_ext_ok:
            # funding baixo (crowded short) => LONG
            stop = min(lows[i - sw:i + 1]) - buf * a
            s = _mk_setup(candles_4h, i, "long", c, stop, rr, a,
                          interval_minutes, "F5", msd, xsd)
        else:
            continue
        if s is not None:
            out.append(s)
    return out


__all__ = ["F5_PARAMS", "detect_f5_funding_swing"]
