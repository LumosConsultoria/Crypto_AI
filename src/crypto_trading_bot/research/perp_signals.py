"""
Perp-native signals (FASE 47) — funding + open interest, alinhados CAUSAL.
==========================================================================
Carrega series de funding (8h) e open interest, alinha-as ao TF de execucao
por CLOSE_TIME (valor em t usa SO pontos com timestamp <= decision_time) e
deriva features causais (percentil de funding p/ F1; variacao de OI p/ F2).
Tambem expoe os EVENTOS de funding p/ aplicar funding ao PnL REALISTIC quando
um trade atravessa o evento (00/08/16 UTC).

Anti-lookahead: asof-join causal (ultimo ponto <= close_time); percentil e
variacao usam SO janela passada. Sem rede aqui (consome series ja coletadas).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Sequence, Tuple


# ----------------------------- modelos ------------------------------------

@dataclass(frozen=True)
class TimePoint:
    ts: datetime
    value: float


def _as_utc(ts) -> datetime:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def load_points(rows: Sequence[Mapping[str, Any]], *, ts_key: str,
                value_key: str) -> List[TimePoint]:
    """Carrega e ORDENA por timestamp ascendente. Ignora linhas invalidas."""
    out: List[TimePoint] = []
    for r in rows or []:
        try:
            ts = _as_utc(r[ts_key])
            val = float(r[value_key])
        except (KeyError, TypeError, ValueError):
            continue
        out.append(TimePoint(ts=ts, value=val))
    out.sort(key=lambda p: p.ts)
    return out


def load_funding(rows: Sequence[Mapping[str, Any]]) -> List[TimePoint]:
    return load_points(rows, ts_key="timestamp", value_key="funding_rate")


def load_open_interest(rows: Sequence[Mapping[str, Any]]) -> List[TimePoint]:
    return load_points(rows, ts_key="timestamp", value_key="open_interest")


# ----------------------------- alinhamento causal --------------------------

def _close_time(candle, interval_minutes: int) -> datetime:
    from datetime import timedelta
    ts = candle.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts + timedelta(minutes=interval_minutes)


def align_asof(candles: Sequence, points: Sequence[TimePoint], *,
               interval_minutes: int) -> List[Optional[float]]:
    """Para cada candle de execucao, o ultimo ponto com ts <= close_time
    (asof causal). Pontos devem estar ordenados asc. O(n+m)."""
    out: List[Optional[float]] = []
    j = 0
    m = len(points)
    last: Optional[float] = None
    # candles assumidos em ordem ascendente
    for c in candles:
        ct = _close_time(c, interval_minutes)
        while j < m and points[j].ts <= ct:
            last = points[j].value
            j += 1
        out.append(last)
    return out


# ----------------------------- features causais ----------------------------

def causal_percentile_rank(series: Sequence[Optional[float]], *,
                           window: int) -> List[Optional[float]]:
    """Rank percentil (0..1) de cada valor vs a janela PASSADA (inclui o
    proprio; exclui futuro). None enquanto warmup < window/2 ou valor None."""
    out: List[Optional[float]] = []
    buf: List[float] = []
    min_n = max(2, window // 2)
    for v in series:
        if v is None:
            out.append(None)
            continue
        # rank vs janela passada (antes de inserir o atual)
        win = buf[-window:]
        if len(win) < min_n:
            rank = None
        else:
            le = sum(1 for x in win if x <= v)
            rank = round(le / len(win), 4)
        out.append(rank)
        buf.append(v)
    return out


def causal_pct_change(series: Sequence[Optional[float]], *,
                      k: int) -> List[Optional[float]]:
    """Variacao percentual causal sobre k passos: (v[i]-v[i-k])/v[i-k]."""
    out: List[Optional[float]] = []
    n = len(series)
    for i in range(n):
        v = series[i]
        prev = series[i - k] if i - k >= 0 else None
        if v is None or prev is None or prev == 0:
            out.append(None)
        else:
            out.append((v - prev) / abs(prev))
    return out


# ----------------------------- funding no PnL ------------------------------

def funding_pnl_adjustment(
    entry_time, exit_time, *, notional_usd: float, side: str,
    funding_events: Sequence[TimePoint],
) -> float:
    """Ajuste de PnL (USD) por funding quando o trade atravessa eventos.

    Convencao perp: rate>0 => LONG paga, SHORT recebe. Aplica em cada evento
    com entry_time < ts_evento <= exit_time. Retorna ajuste (negativo = custo).
    """
    if not funding_events or entry_time is None or exit_time is None:
        return 0.0
    ein = _as_utc(entry_time) if not isinstance(entry_time, datetime) \
        or entry_time.tzinfo is None else entry_time
    exo = _as_utc(exit_time) if not isinstance(exit_time, datetime) \
        or exit_time.tzinfo is None else exit_time
    sign = -1.0 if str(side).lower() in ("buy", "long") else 1.0
    total = 0.0
    for ev in funding_events:
        if ein < ev.ts <= exo:
            total += sign * ev.value * notional_usd
    return round(total, 6)


@dataclass(frozen=True)
class PerpFeatures:
    """Features perp alinhadas a uma serie de candles de execucao."""
    funding: List[Optional[float]]            # taxa de funding asof
    funding_pctile: List[Optional[float]]     # percentil causal (F1)
    oi: List[Optional[float]]                 # open interest asof
    oi_change: List[Optional[float]]          # variacao causal de OI (F2)
    funding_events: List[TimePoint]           # eventos p/ PnL realistic

    def coverage(self) -> dict:
        def _cov(xs):
            n = len(xs)
            present = sum(1 for x in xs if x is not None)
            return {"n": n, "present": present,
                    "coverage": round(present / n, 4) if n else 0.0}
        return {"funding": _cov(self.funding), "oi": _cov(self.oi),
                "funding_events": len(self.funding_events)}


def build_perp_features(
    candles: Sequence, *, interval_minutes: int,
    funding_points: Sequence[TimePoint] = (),
    oi_points: Sequence[TimePoint] = (),
    funding_pctile_window: int = 90,
    oi_change_k: int = 4,
) -> PerpFeatures:
    """Constroi as features perp causais alinhadas aos candles de execucao."""
    funding = align_asof(candles, funding_points,
                         interval_minutes=interval_minutes)
    oi = align_asof(candles, oi_points, interval_minutes=interval_minutes)
    return PerpFeatures(
        funding=funding,
        funding_pctile=causal_percentile_rank(funding,
                                              window=funding_pctile_window),
        oi=oi,
        oi_change=causal_pct_change(oi, k=oi_change_k),
        funding_events=list(funding_points),
    )


__all__ = [
    "TimePoint", "PerpFeatures",
    "load_points", "load_funding", "load_open_interest",
    "align_asof", "causal_percentile_rank", "causal_pct_change",
    "funding_pnl_adjustment", "build_perp_features",
]
