"""
Variance-Ratio Regime Switch (FASE 62) — H1, BTCUSDT 1h. Params PRE-FIXADOS.
============================================================================
Condiciona a regra pela AUTOCORRELACAO dos retornos, medida pelo VARIANCE RATIO
(VR). VR>1 => retornos com autocorrelacao POSITIVA (regime de MOMENTUM); VR<1 =>
autocorrelacao NEGATIVA (regime de MEAN-REVERSION); zona neutra => nao opera.

FORMULA EXPLICITA (causal; so candles FECHADOS <= i):
  r1[t] = close[t]/close[t-1] - 1                    (retorno de 1 periodo)
  rq[t] = close[t]/close[t-q] - 1                    (retorno de q periodos)
  sobre a janela W = VR_window candles terminando em i:
  VR = Var(rq) / (q * Var(r1))            com q = 2 (Lo-MacKinlay simplificado)
Direcao de momentum = sinal do retorno na janela W: sign(close[i]/close[i-W]-1).
  - MOMENTUM (VR >= VR_hi): opera NA direcao (long se subiu, short se caiu).
  - MEAN-REVERSION (VR <= VR_lo): opera CONTRA (fade).
  - NEUTRO (VR_lo < VR < VR_hi): NAO opera.
ENTRADA sempre no PROXIMO candle (e=i+1); decisao usa so dados <= i. Stop
estrutural 2xATR (piso 0,5% soberano; setup < piso DESCARTADO, nunca alargado);
alvo R-multiplo; saida por tempo (orquestrador).
"""

from __future__ import annotations

import math
import statistics
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.mtf_setups import Setup, _f
from crypto_trading_bot.research.normal_families import _atr

_PISO = 0.005
_MIN_STOP, _MAX_STOP = 0.005, 0.05

# PARAMS PRE-FIXADOS (operador; antes do DEV; sem grid)
H1_PARAMS = {"VR_window": 24, "VR_hi": 1.10, "VR_lo": 0.90, "q": 2,
             "stop_atr": 2.0, "rr": 1.5}
H1_HOLD_BARS = 12               # saida por tempo (12 candles 1h)


def variance_ratio(closes: Sequence[float], i: int, W: int, q: int = 2
                   ) -> Optional[float]:
    """VR causal usando SO closes[<= i]. Ver formula no modulo."""
    start = i - W + 1
    if start - q < 0:
        return None
    r1, rq = [], []
    for t in range(start, i + 1):
        if closes[t - 1] <= 0 or closes[t - q] <= 0 or closes[t] <= 0:
            return None
        r1.append(closes[t] / closes[t - 1] - 1.0)
        rq.append(closes[t] / closes[t - q] - 1.0)
    if len(r1) < 4:
        return None
    var1 = statistics.pvariance(r1)
    if var1 <= 0:
        return None
    return statistics.pvariance(rq) / (q * var1)


def _mk(candles, e, direction, entry, stop, rr, atr_e, interval, tag):
    dist = (entry - stop) if direction == "long" else (stop - entry)
    if dist <= 0 or entry <= 0:
        return None
    target = entry + rr * dist if direction == "long" else entry - rr * dist
    dpct = dist / entry
    if dpct < _MIN_STOP or dpct > _MAX_STOP:        # piso/cap (sem alargar)
        return None
    ots = candles[e].timestamp
    return Setup(idx=e, open_ts=ots, close_ts=ots + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dpct, 6), below_floor=dpct < _PISO,
                 atr=atr_e, setup_id=f"{tag}_{e}")


def detect_variance_ratio_regime_switch(
    candles_1h: Sequence, *, interval_minutes: int = 60,
    params: Optional[Dict[str, Any]] = None) -> List[Setup]:
    p = {**H1_PARAMS, **(params or {})}
    W = int(p["VR_window"]); q = int(p["q"])
    hi, lo = float(p["VR_hi"]), float(p["VR_lo"])
    katr = float(p["stop_atr"]); rr = float(p["rr"])
    closes = [float(c.close) for c in candles_1h]
    atr = _atr(candles_1h)
    n = len(closes)
    out: List[Setup] = []
    for i in range(max(W + q, 20), n - 1):          # i = sinal; e = i+1 = entrada
        if closes[i - W] <= 0:
            continue
        vr = variance_ratio(closes, i, W, q)
        if vr is None:
            continue
        mom = closes[i] / closes[i - W] - 1.0        # direcao da janela
        if mom == 0:
            continue
        if vr >= hi:                                 # MOMENTUM: segue
            direction = "long" if mom > 0 else "short"
        elif vr <= lo:                               # MEAN-REVERSION: fade
            direction = "long" if mom < 0 else "short"
        else:
            continue                                 # zona NEUTRA: nao opera
        e = i + 1                                     # ENTRADA no proximo candle
        a = atr[e]
        c = closes[e]
        if math.isnan(a) or a <= 0 or c <= 0:
            continue
        stop = c - katr * a if direction == "long" else c + katr * a
        s = _mk(candles_1h, e, direction, c, stop, rr, a, interval_minutes,
                "H1vr")
        if s is not None:
            out.append(s)
    return out


__all__ = ["H1_PARAMS", "H1_HOLD_BARS", "variance_ratio",
           "detect_variance_ratio_regime_switch"]
