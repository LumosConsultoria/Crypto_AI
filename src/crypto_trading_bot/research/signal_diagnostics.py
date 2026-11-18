"""
Signal Diagnostics (FASE 49) — poder preditivo de features vs retorno futuro.
=============================================================================
Mede se uma feature (causal, conhecida em t) tem relacao estatistica com o
RETORNO FUTURO em varios horizontes, SEM montar estrategia. Puro/offline.

Por feature x horizonte:
  - IC (Spearman rank) + Pearson;
  - analise por QUANTIL: nº, retorno medio futuro, hit rate, mediana;
  - retorno LIQUIDO estimado apos custo (top long / bottom short / spread);
  - estabilidade MENSAL (IC por mes + sign_consistency);
  - estabilidade por REGIME (IC por rotulo de regime);
  - tamanho de amostra por bucket;
  - verdict: real_relation | noise | regime_specific | dies_after_cost |
    insufficient_sample.

Anti-lookahead: a feature em t usa so dados <= t; o retorno futuro t->t+H e o
ALVO (medido, nao negociado). Pares cujo t+H sai da janela sao descartados =>
nao toca OOS (rode com candles ja fatiados em DEV+VAL).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# limiares (heuristicos, documentados)
IC_NOISE = 0.03           # |IC| abaixo disso ~ ruido
IC_REAL = 0.05            # |IC| acima disso + estavel => relacao real
SIGN_CONSISTENCY_MIN = 0.60
MIN_PAIRS = 200           # amostra minima total
MIN_BUCKET = 20           # amostra minima por quantil


def forward_returns(closes: Sequence[float], horizon: int) -> List[Optional[float]]:
    """Retorno futuro close[i+h]/close[i]-1 (None onde i+h fora do range)."""
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    for i in range(n):
        j = i + horizon
        if j < n and closes[i] and closes[i] > 0:
            out[i] = closes[j] / closes[i] - 1.0
        # senao None (alvo fora da janela => descartado; NAO toca OOS)
    return out


def _pairs(feature: Sequence[Optional[float]],
           fwd: Sequence[Optional[float]]) -> Tuple[List[float], List[float],
                                                    List[int]]:
    fx, fy, idx = [], [], []
    for i, (a, b) in enumerate(zip(feature, fwd)):
        if a is None or b is None:
            continue
        if isinstance(a, float) and math.isnan(a):
            continue
        if isinstance(b, float) and math.isnan(b):
            continue
        fx.append(float(a)); fy.append(float(b)); idx.append(i)
    return fx, fy, idx


def _rank(xs: Sequence[float]) -> List[float]:
    order = sorted(range(len(xs)), key=lambda k: xs[k])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 3:
        return None
    ma = sum(a) / n; mb = sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da == 0 or db == 0:
        return None
    return num / (da * db)


def spearman(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    if len(a) < 3:
        return None
    return _pearson(_rank(a), _rank(b))


def quantile_analysis(fx: Sequence[float], fy: Sequence[float], *,
                      n_quantiles: int = 5,
                      cost_pct: float = 0.0026) -> Dict[str, Any]:
    """Estatisticas por quantil da feature + retorno liquido apos custo."""
    n = len(fx)
    if n < n_quantiles * MIN_BUCKET:
        return {"buckets": [], "insufficient": True, "n": n}
    pairs = sorted(zip(fx, fy), key=lambda p: p[0])
    size = n // n_quantiles
    buckets = []
    for q in range(n_quantiles):
        lo = q * size
        hi = (q + 1) * size if q < n_quantiles - 1 else n
        seg = pairs[lo:hi]
        ys = [y for _, y in seg]
        m = sum(ys) / len(ys)
        hit = sum(1 for y in ys if y > 0) / len(ys)
        buckets.append({
            "quantile": q + 1, "n": len(seg),
            "feature_range": [round(seg[0][0], 6), round(seg[-1][0], 6)],
            "mean_fwd_ret": round(m, 6),
            "hit_rate": round(hit, 4),
        })
    top = buckets[-1]["mean_fwd_ret"]; bot = buckets[0]["mean_fwd_ret"]
    # net DIRECAO-AGNOSTICO: no quantil extremo, negocia-se o SINAL previsto
    # (long se mean>0, short se mean<0) => captura |mean|. Assim funciona p/
    # IC positivo E negativo (ex.: funding alto => retorno futuro negativo =>
    # operar short). net = |mean_extremo| - custo.
    net_top = abs(top) - cost_pct
    net_bottom = abs(bot) - cost_pct
    return {
        "buckets": buckets, "insufficient": False, "n": n,
        "top_minus_bottom": round(top - bot, 6),
        "net_top_extreme_after_cost": round(net_top, 6),
        "net_bottom_extreme_after_cost": round(net_bottom, 6),
        "net_long_short_spread_after_cost": round(abs(top - bot)
                                                  - 2 * cost_pct, 6),
        "best_single_side_net_after_cost": round(max(net_top, net_bottom), 6),
        "cost_pct": cost_pct,
    }


def _month_key(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return f"{ts.year}-{ts.month:02d}"


def monthly_stability(fx, fy, idx, timestamps) -> Dict[str, Any]:
    """IC por mes-calendario + sign_consistency (fracao com IC do mesmo sinal
    do IC global)."""
    overall = spearman(fx, fy)
    by_month: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, i in zip(fx, fy, idx):
        k = _month_key(timestamps[i])
        by_month.setdefault(k, []).append((x, y))
    month_ic = {}
    for k, seg in sorted(by_month.items()):
        if len(seg) >= 3:
            month_ic[k] = spearman([p[0] for p in seg], [p[1] for p in seg])
    valid = [v for v in month_ic.values() if v is not None]
    if not valid or overall is None or overall == 0:
        sign_consistency = None
    else:
        sgn = 1 if overall > 0 else -1
        same = sum(1 for v in valid if (v > 0) == (sgn > 0))
        sign_consistency = round(same / len(valid), 4)
    return {"overall_ic": round(overall, 4) if overall is not None else None,
            "n_months": len(valid),
            "sign_consistency": sign_consistency,
            "month_ic": {k: (round(v, 4) if v is not None else None)
                         for k, v in month_ic.items()}}


def regime_stability(fx, fy, idx, regime_by_idx) -> Dict[str, Any]:
    """IC por rotulo de regime (regime_by_idx: {idx -> label})."""
    by_reg: Dict[str, List[Tuple[float, float]]] = {}
    for x, y, i in zip(fx, fy, idx):
        r = regime_by_idx.get(i)
        if r is None:
            continue
        by_reg.setdefault(str(r), []).append((x, y))
    out = {}
    for r, seg in by_reg.items():
        ic = spearman([p[0] for p in seg], [p[1] for p in seg]) \
            if len(seg) >= 10 else None
        out[r] = {"n": len(seg), "ic": round(ic, 4) if ic is not None
                  else None}
    return out


def diagnose_feature(name: str, feature: Sequence[Optional[float]],
                     fwd: Sequence[Optional[float]], *, timestamps,
                     regime_by_idx: Optional[Mapping[int, Any]] = None,
                     n_quantiles: int = 5,
                     cost_pct: float = 0.0026) -> Dict[str, Any]:
    """Diagnostico consolidado de uma feature contra um horizonte."""
    fx, fy, idx = _pairs(feature, fwd)
    n = len(fx)
    if n < MIN_PAIRS:
        return {"feature": name, "n_pairs": n, "verdict": "insufficient_sample",
                "ic": None}
    ic = spearman(fx, fy)
    pear = _pearson(fx, fy)
    q = quantile_analysis(fx, fy, n_quantiles=n_quantiles, cost_pct=cost_pct)
    mon = monthly_stability(fx, fy, idx, timestamps)
    reg = regime_stability(fx, fy, idx, regime_by_idx or {})
    abs_ic = abs(ic) if ic is not None else 0.0
    sc = mon.get("sign_consistency")
    # melhor lado (negocia o sinal previsto no quantil extremo) apos custo
    net_best = None
    if not q.get("insufficient"):
        net_best = q["best_single_side_net_after_cost"]
    # regime-specific: algum regime com |IC| forte enquanto global fraco
    regime_strong = any(
        (v["ic"] is not None and abs(v["ic"]) >= IC_REAL and v["n"] >= 30)
        for v in reg.values())
    # verdict
    if q.get("insufficient"):
        verdict = "insufficient_sample"
    elif abs_ic < IC_NOISE and (sc is None or abs(sc - 0.5) < 0.15):
        verdict = "noise"
    elif (abs_ic >= IC_REAL and sc is not None and sc >= SIGN_CONSISTENCY_MIN
          and net_best is not None and net_best > 0):
        verdict = "real_relation"
    elif net_best is not None and net_best <= 0 and abs_ic >= IC_NOISE:
        verdict = "dies_after_cost"
    elif regime_strong and abs_ic < IC_REAL:
        verdict = "regime_specific"
    else:
        verdict = "weak_or_inconclusive"
    return {
        "feature": name, "n_pairs": n,
        "ic_spearman": round(ic, 4) if ic is not None else None,
        "pearson": round(pear, 4) if pear is not None else None,
        "quantiles": q, "monthly": mon, "regime": reg,
        "net_best_after_cost": net_best,
        "verdict": verdict,
    }


__all__ = [
    "forward_returns", "spearman", "quantile_analysis", "monthly_stability",
    "regime_stability", "diagnose_feature", "IC_NOISE", "IC_REAL", "MIN_PAIRS",
]
