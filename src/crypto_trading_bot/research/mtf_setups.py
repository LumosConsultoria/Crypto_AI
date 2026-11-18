"""
Multi-timeframe setups (FASE 45) — deteccao de SETUP no 15m + SL/TP
ESTRUTURAL. Componente minimo (nao framework). Determinístico, params
FIXOS, anti-lookahead: o setup no candle i usa SOMENTE features ate i.

H1 — breakout/momentum: expansao de bb_bandwidth + rompimento de swing.
H2 — pullback de continuacao: recuo a uma EMA + retomada na direcao.

O STOP nasce da ESTRUTURA do 15m (swing +/- folga ATR). NUNCA e ampliado
artificialmente p/ superar o piso: se stop_dist_pct < piso, o setup e
emitido mesmo assim com a flag `below_floor=True` e a ESTRATEGIA/RiskEngine
decide (HOLD/BLOCK). Aqui so registramos a estrutura real.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

# Params FIXOS por hipotese (sem grid).
H1_PARAMS = {"lookback": 20, "expansion_factor": 1.3, "swing_lookback": 20,
             "atr_buffer": 0.5, "risk_reward": 1.5}
H2_PARAMS = {"ema_key": "ema_20", "pullback_window": 6, "atr_buffer": 0.5,
             "risk_reward": 1.5, "trend_lookback": 20}
_PISO = 0.005   # piso 0,5% (so p/ marcar below_floor; RiskEngine e soberano)


@dataclass(frozen=True)
class Setup:
    idx: int
    open_ts: Any
    close_ts: Any
    direction: str          # "long" | "short"
    entry_ref: float        # close do candle de setup (referencia)
    stop: float             # stop ESTRUTURAL (15m)
    target: float
    stop_dist_pct: float
    below_floor: bool       # stop_dist_pct < piso 0,5%
    atr: float
    setup_id: str

    def to_dict(self) -> dict:
        return {"idx": self.idx, "open_ts": _iso(self.open_ts),
                "close_ts": _iso(self.close_ts), "direction": self.direction,
                "entry_ref": self.entry_ref, "stop": self.stop,
                "target": self.target, "stop_dist_pct": self.stop_dist_pct,
                "below_floor": self.below_floor, "setup_id": self.setup_id}


def _iso(ts):
    try:
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:  # noqa: BLE001
        return str(ts)


def _f(v) -> float:
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return float("nan")


def detect_setups(candles_15m: Sequence, *, hypothesis: str,
                  interval_minutes: int = 15,
                  params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    """Lista de setups (causal) no 15m p/ a hipotese. Usa FeatureEngine
    UMA vez (O(n)). H1='H1_trend_vol_expansion'/'breakout';
    H2='H2_pullback_continuation'/'pullback'."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    if not candles_15m:
        return []
    feats = FeatureEngine().compute(list(candles_15m))
    closes = [_f(x) for x in feats["closes"]]
    highs = [_f(x) for x in feats["highs"]]
    lows = [_f(x) for x in feats["lows"]]
    atr = [_f(x) for x in feats[f"atr_14"]]
    n = len(closes)
    hl = hypothesis.lower()
    if "h1" in hl or "breakout" in hl or "vol" in hl:
        return _detect_h1(candles_15m, closes, highs, lows, atr, n,
                          interval_minutes, {**H1_PARAMS, **(params or {})})
    if "h2" in hl or "pullback" in hl:
        ema = [_f(x) for x in feats[(params or H2_PARAMS).get(
            "ema_key", "ema_20")]]
        return _detect_h2(candles_15m, closes, highs, lows, atr, ema, n,
                          interval_minutes, {**H2_PARAMS, **(params or {})})
    raise ValueError(f"hipotese desconhecida: {hypothesis}")


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
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i,
                 setup_id=f"{tag}_{i}")


def _detect_h1(candles, closes, highs, lows, atr, n, interval, p) -> List[Setup]:
    L = int(p["lookback"]); sw = int(p["swing_lookback"])
    ef = float(p["expansion_factor"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"])
    # Expansao de volatilidade via ATR atual vs media da janela anterior
    # (proxy causal de squeeze->expansao; ATR ja disponivel no FeatureEngine).
    start = max(L, sw, 55)
    out: List[Setup] = []
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        # expansao de volatilidade: ATR atual vs media da janela anterior.
        prior_atr = [x for x in atr[i - L:i] if not math.isnan(x) and x > 0]
        if not prior_atr:
            continue
        mean_prior = sum(prior_atr) / len(prior_atr)
        expansion = a > ef * mean_prior
        if not expansion:
            continue
        swing_high = max(highs[i - sw:i])
        swing_low = min(lows[i - sw:i])
        c = closes[i]
        if c > swing_high:          # breakout up => long
            stop = swing_low - buf * a
            s = _mk_setup(candles, i, "long", c, stop, rr, a, interval, "H1")
        elif c < swing_low:         # breakdown => short
            stop = swing_high + buf * a
            s = _mk_setup(candles, i, "short", c, stop, rr, a, interval, "H1")
        else:
            continue
        if s is not None:
            out.append(s)
    return out


def _detect_h2(candles, closes, highs, lows, atr, ema, n, interval, p) -> List[Setup]:
    pw = int(p["pullback_window"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"]); tl = int(p["trend_lookback"])
    start = max(pw, tl, 55)
    out: List[Setup] = []
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0 or math.isnan(ema[i]):
            continue
        c, cp = closes[i], closes[i - 1]
        # tendencia local de 15m (proxy; o 1h e o filtro macro na estrategia)
        up = ema[i] > ema[i - tl] and c > ema[i]
        down = ema[i] < ema[i - tl] and c < ema[i]
        # pullback: nas ultimas pw barras tocou a EMA do lado oposto.
        if up:
            touched = any(lows[j] <= ema[j] for j in range(i - pw, i)
                          if not math.isnan(ema[j]))
            if touched and c > ema[i] and c > cp:   # retomada de alta
                stop = min(lows[i - pw:i + 1]) - buf * a
                s = _mk_setup(candles, i, "long", c, stop, rr, a, interval,
                              "H2")
                if s is not None:
                    out.append(s)
        elif down:
            touched = any(highs[j] >= ema[j] for j in range(i - pw, i)
                          if not math.isnan(ema[j]))
            if touched and c < ema[i] and c < cp:
                stop = max(highs[i - pw:i + 1]) + buf * a
                s = _mk_setup(candles, i, "short", c, stop, rr, a, interval,
                              "H2")
                if s is not None:
                    out.append(s)
    return out


__all__ = ["H1_PARAMS", "H2_PARAMS", "Setup", "detect_setups"]
