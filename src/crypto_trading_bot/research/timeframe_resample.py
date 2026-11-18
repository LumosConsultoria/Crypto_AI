"""
Causal timeframe resampler (FASE 48) — agrega candles de baixo TF p/ alto TF.
=============================================================================
Reamostra candles (ex.: 1h -> 4h ou 1h -> 1d) agrupando por bucket UTC
alinhado (floor por `factor_minutes`). Cada candle agregado: open=primeiro,
high=max, low=min, close=ultimo, volume=soma; timestamp = inicio do bucket
(open time, consistente com os candles existentes). So buckets COMPLETOS
entram (descarta bucket parcial no fim) => anti-lookahead (um candle 4h so
"existe" quando suas 4 barras 1h fecharam).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Sequence

from crypto_trading_bot.exchange.base_exchange import Candle


def _bucket_start(ts: datetime, factor_minutes: int) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    epoch_min = int(ts.timestamp() // 60)
    floored = (epoch_min // factor_minutes) * factor_minutes
    return datetime.fromtimestamp(floored * 60, tz=timezone.utc)


def resample(candles: Sequence[Candle], *, factor_minutes: int,
             base_minutes: int, symbol: str = "BTCUSDT",
             label: str = "") -> List[Candle]:
    """Agrega candles de `base_minutes` em barras de `factor_minutes`.

    Requer factor_minutes multiplo de base_minutes. So buckets COMPLETOS
    (factor/base barras) sao emitidos (causal)."""
    if factor_minutes % base_minutes != 0:
        raise ValueError("factor_minutes deve ser multiplo de base_minutes")
    per_bucket = factor_minutes // base_minutes
    tf_label = label or (f"{factor_minutes // 60}h" if factor_minutes >= 60
                         and factor_minutes % 60 == 0
                         else f"{factor_minutes}m")
    groups: dict = {}
    order: List[datetime] = []
    for c in candles:
        b = _bucket_start(c.timestamp, factor_minutes)
        if b not in groups:
            groups[b] = []
            order.append(b)
        groups[b].append(c)
    out: List[Candle] = []
    for b in sorted(order):
        g = groups[b]
        if len(g) != per_bucket:
            continue                 # bucket incompleto => descarta (causal)
        g = sorted(g, key=lambda x: x.timestamp)
        out.append(Candle(
            symbol=symbol, timeframe=tf_label, timestamp=b,
            open=float(g[0].open),
            high=max(float(x.high) for x in g),
            low=min(float(x.low) for x in g),
            close=float(g[-1].close),
            volume=sum(float(x.volume) for x in g)))
    return out


__all__ = ["resample"]
