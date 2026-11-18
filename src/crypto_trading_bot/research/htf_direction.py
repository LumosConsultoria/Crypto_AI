"""
HTF direction por SLOPE de EMA (FASE 46). Componente minimo.

Direcao de fundo no 1h via inclinacao de uma EMA de periodo FIXO:
  slope[i] = (ema[i] - ema[i-k]) / ema[i-k]
  long  se slope >= +threshold ; short se slope <= -threshold ; senao None.

Reusa o VOCABULARIO de regime ("trend_up"/"trend_down") para encaixar sem
mudanca no gating de `mtf_strategy._regime_ok` (long->trend_up,
short->trend_down). Substitui `classify_regimes` como fonte de direcao
(que raramente rotula trend => pouca amostra), SEM afrouxar criterio (regra
unica e pre-definida; sem grid).

Anti-lookahead: ema[i] usa closes <= i; slope usa i e i-k (passado). A
direcao do candle 1h i e conhecida no FECHAMENTO de i; o alinhamento ao TF
de execucao usa close_time (select_htf_index_by_close).
"""

from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence

# Params FIXOS (documentados; sem grid).
DEFAULT_EMA_PERIOD = 50
DEFAULT_SLOPE_K = 6
DEFAULT_THRESHOLD = 0.001   # 0,1% sobre k barras 1h


def ema_slope_direction(
    candles_1h: Sequence, *, ema_period: int = DEFAULT_EMA_PERIOD,
    slope_k: int = DEFAULT_SLOPE_K, threshold: float = DEFAULT_THRESHOLD,
) -> List[Optional[str]]:
    """Direcao por indice do 1h: 'trend_up'|'trend_down'|None (warmup/flat).
    Lista alinhada a candles_1h (len == len(candles_1h))."""
    n = len(candles_1h)
    out: List[Optional[str]] = [None] * n
    if n == 0:
        return out
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    feats = FeatureEngine().compute(list(candles_1h))
    key = f"ema_{ema_period}"
    if key not in feats:
        raise ValueError(f"EMA {ema_period} indisponivel no FeatureEngine")
    ema = [float(x) for x in feats[key]]
    for i in range(n):
        if i < slope_k:
            continue
        e_i, e_prev = ema[i], ema[i - slope_k]
        if math.isnan(e_i) or math.isnan(e_prev) or e_prev <= 0:
            continue
        slope = (e_i - e_prev) / e_prev
        if slope >= threshold:
            out[i] = "trend_up"
        elif slope <= -threshold:
            out[i] = "trend_down"
        # senao: None (sem direcao)
    return out


def align_direction_to_exec(
    candles_exec: Sequence, candles_1h: Sequence,
    dir_by_idx_1h: List[Optional[str]], *,
    low_interval_minutes: int, high_interval_minutes: int = 60,
) -> dict:
    """{ts_key(open_exec) -> direcao 1h (causal por close_time)}. Reusa
    select_htf_index_by_close (anti off-by-one ja testado)."""
    from crypto_trading_bot.research.htf_regime_filter import (
        select_htf_index_by_close,
        _ts_key,
    )
    idxs = select_htf_index_by_close(
        candles_exec, candles_1h,
        low_interval_minutes=low_interval_minutes,
        high_interval_minutes=high_interval_minutes)
    out = {}
    for c, j in zip(candles_exec, idxs):
        out[_ts_key(c.timestamp)] = dir_by_idx_1h[j] if j >= 0 else None
    return out


__all__ = [
    "DEFAULT_EMA_PERIOD",
    "DEFAULT_SLOPE_K",
    "DEFAULT_THRESHOLD",
    "align_direction_to_exec",
    "ema_slope_direction",
]
