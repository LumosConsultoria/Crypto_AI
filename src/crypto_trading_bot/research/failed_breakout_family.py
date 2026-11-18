"""
Failed-Breakout Fade (FASE 59) — H1, 5m BTCUSDT. Params PRE-FIXADOS (sem grid).
==============================================================================
Fade de rompimento FALHO (stop-run / liquidity grab): no 5m, quando o preco
ROMPE o canal Donchian recente intrabar mas FECHA de volta DENTRO (rejeicao),
opera CONTRA o rompimento falho (fade). Causal: usa so a barra i (high/low/
close) + o canal anterior + ATR. Gate de CONTEXTO 1h (EMA slope) para nao fazer
fade A FAVOR de tendencia forte oposta. Saida por TEMPO (max_holding_candles).

Difere de breakout_trend (NAO segue o rompimento) e de mean_reversion generico
(exige o EVENTO de fakeout). Stop ESTRUTURAL acima/abaixo do pavio rejeitado
(piso 0.005 soberano: setups < piso sao descartados, NUNCA alargados de proposito).
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.mtf_setups import Setup, _f
from crypto_trading_bot.research.normal_families import _atr

_PISO = 0.005
_MIN_STOP, _MAX_STOP = 0.005, 0.05

# PARAMS PRE-FIXADOS (antes do DEV; sem grid)
H1_PARAMS = {"donch_lookback": 20, "atr_buffer": 0.3, "rr": 1.5,
             "regime_block_slope": 0.003}
H1_HOLD_BARS = 24                      # ~2h no 5m (saida por tempo)


def _mk(candles, i, direction, entry, stop, target, atr_i, interval, tag):
    dist = (entry - stop) if direction == "long" else (stop - entry)
    if dist <= 0 or entry <= 0:
        return None
    if direction == "long" and target <= entry:
        return None
    if direction == "short" and target >= entry:
        return None
    dist_pct = dist / entry
    if dist_pct < _MIN_STOP or dist_pct > _MAX_STOP:
        return None                    # piso/cap soberanos (sem alargar)
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i, setup_id=f"{tag}_{i}")


def detect_failed_breakout_fade(
    candles_5m: Sequence, *, regime_slope_1h: Optional[Sequence] = None,
    interval_minutes: int = 5, params: Optional[Dict[str, Any]] = None
) -> List[Setup]:
    p = {**H1_PARAMS, **(params or {})}
    lb = int(p["donch_lookback"]); buf = float(p["atr_buffer"])
    rr = float(p["rr"]); rthr = float(p["regime_block_slope"])
    closes = [float(c.close) for c in candles_5m]
    highs = [float(c.high) for c in candles_5m]
    lows = [float(c.low) for c in candles_5m]
    atr = _atr(candles_5m)
    n = len(closes)
    out: List[Setup] = []
    for i in range(max(lb, 20), n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        dh = max(highs[i - lb:i])       # canal ANTERIOR (exclui i) => causal
        dl = min(lows[i - lb:i])
        slope = (regime_slope_1h[i] if (regime_slope_1h is not None
                                        and i < len(regime_slope_1h)) else None)
        c = closes[i]
        s = None
        # rompimento FALHO p/ CIMA: pavio acima do canal mas fecha DENTRO => SHORT
        if highs[i] > dh and c < dh:
            # nao fazer fade SHORT contra tendencia de ALTA forte (1h)
            if slope is None or slope < rthr:
                stop = highs[i] + buf * a
                s = _mk(candles_5m, i, "short", c, stop, c - rr * (stop - c), a,
                        interval_minutes, "H1fbf")
        # rompimento FALHO p/ BAIXO: pavio abaixo mas fecha DENTRO => LONG
        elif lows[i] < dl and c > dl:
            if slope is None or slope > -rthr:
                stop = lows[i] - buf * a
                s = _mk(candles_5m, i, "long", c, stop, c + rr * (c - stop), a,
                        interval_minutes, "H1fbf")
        if s is not None:
            out.append(s)
    return out


def build_regime_slope_1h(candles_5m: Sequence) -> List[Optional[float]]:
    """EMA50-slope do 1h (resample causal de 5m) alinhado a cada barra 5m
    (asof por close_time). Contexto de tendencia (nao gera sinal sozinho)."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.research.feature_library import _align_htf_numeric
    from crypto_trading_bot.research.timeframe_resample import resample
    c1h = resample(candles_5m, factor_minutes=60, base_minutes=5)
    if len(c1h) <= 60:
        return [None] * len(candles_5m)
    fe = FeatureEngine().compute(list(c1h))
    ema = [_f(x) for x in fe.get("ema_50", [float("nan")] * len(c1h))]
    slope = []
    k = 6
    for i in range(len(ema)):
        if i >= k and not math.isnan(ema[i]) and not math.isnan(ema[i - k]) \
                and ema[i - k] != 0:
            slope.append((ema[i] - ema[i - k]) / ema[i - k])
        else:
            slope.append(float("nan"))
    return _align_htf_numeric(candles_5m, c1h, slope, low_min=5, high_min=60)


__all__ = ["H1_PARAMS", "H1_HOLD_BARS", "detect_failed_breakout_fade",
           "build_regime_slope_1h"]
