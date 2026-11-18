"""
Non-Overlapping Validation (FASE 50) — valida o sinal de mean-reversion
multi-dia da FASE 49 SEM sobreposicao de janelas.
========================================================================
A FASE 49 mediu retornos futuros 3-7d em passo 1h => janelas SOBREPOSTAS
(~167/168) => amostra efetiva pequena, IC/estabilidade superestimados. Aqui
amostramos janelas DISJUNTAS (indices {offset, offset+H, offset+2H, ...}) e
medimos se o sinal sobrevive, em VARIOS offsets (media + dispersao).

Direcao FIXA da hipotese (pre-especificada, FASE 49): MEAN-REVERSION =>
no extremo ALTO da feature opera SHORT; no extremo BAIXO opera LONG. Mede o
net REALIZADO por trade (apos custo) em janelas disjuntas. Puro/offline.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.signal_diagnostics import spearman


def nonoverlap_indices(n: int, horizon: int, offset: int) -> List[int]:
    """Indices de inicio de janelas DISJUNTAS: offset, offset+H, ... com
    i+H < n (alvo dentro da janela => nao toca OOS quando ja fatiado)."""
    out = []
    i = offset
    while i + horizon < n:
        out.append(i)
        i += horizon
    return out


def _pairs_at(feature, fwd, idxs):
    fx, fy, ix = [], [], []
    for i in idxs:
        a = feature[i] if i < len(feature) else None
        b = fwd[i] if i < len(fwd) else None
        if a is None or b is None:
            continue
        if isinstance(a, float) and math.isnan(a):
            continue
        if isinstance(b, float) and math.isnan(b):
            continue
        fx.append(float(a)); fy.append(float(b)); ix.append(i)
    return fx, fy, ix


def realized_mean_reversion(fx: Sequence[float], fy: Sequence[float], *,
                            tercile: float = 1.0 / 3.0,
                            cost_pct: float = 0.0026) -> Dict[str, Any]:
    """Net realizado da hipotese MEAN-REVERSION (direcao FIXA) numa amostra
    disjunta: dispara nos EXTREMOS (top/bottom tercil) da feature; short no
    top (extensao alta), long no bottom; net = mean(pos*fwd) - custo."""
    n = len(fx)
    if n < 6:
        return {"n_pairs": n, "n_fired": 0, "net_after_cost": None,
                "hit_rate": None, "ic": None}
    order = sorted(range(n), key=lambda k: fx[k])
    k = max(1, int(n * tercile))
    bottom = set(order[:k])           # feature baixa => LONG (+1)
    top = set(order[-k:])             # feature alta  => SHORT (-1)
    realized = []
    for j in range(n):
        if j in top:
            realized.append(-fy[j])   # short
        elif j in bottom:
            realized.append(+fy[j])   # long
    if not realized:
        return {"n_pairs": n, "n_fired": 0, "net_after_cost": None,
                "hit_rate": None, "ic": spearman(fx, fy)}
    gross = sum(realized) / len(realized)
    hit = sum(1 for r in realized if r > 0) / len(realized)
    return {
        "n_pairs": n, "n_fired": len(realized),
        "gross_mean_realized": round(gross, 6),
        "net_after_cost": round(gross - cost_pct, 6),
        "hit_rate": round(hit, 4),
        "ic": round(spearman(fx, fy), 4) if spearman(fx, fy) is not None
        else None,
    }


def _month_key(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return f"{ts.year}-{ts.month:02d}"


def validate_signal(feature: Sequence[Optional[float]],
                    fwd: Sequence[Optional[float]], *, n: int, horizon: int,
                    offsets: Sequence[int], timestamps: Sequence,
                    cost_pct: float = 0.0026,
                    tercile: float = 1.0 / 3.0) -> Dict[str, Any]:
    """Roda a validacao em varios offsets DISJUNTOS e agrega media/dispersao.
    Tambem checa estabilidade MENSAL no pool de trades disparados."""
    per_offset = []
    pooled_realized: List[Tuple[str, float]] = []   # (mes, realized)
    for off in offsets:
        idxs = nonoverlap_indices(n, horizon, off)
        fx, fy, ix = _pairs_at(feature, fwd, idxs)
        r = realized_mean_reversion(fx, fy, tercile=tercile, cost_pct=cost_pct)
        r["offset"] = off
        r["n_windows"] = len(idxs)
        per_offset.append(r)
        # pool mensal (recomputa extremos p/ marcar mes do trade)
        if len(fx) >= 6:
            order = sorted(range(len(fx)), key=lambda k: fx[k])
            k = max(1, int(len(fx) * tercile))
            bottom = set(order[:k]); top = set(order[-k:])
            for j in range(len(fx)):
                if j in top:
                    pooled_realized.append((_month_key(timestamps[ix[j]]),
                                            -fy[j]))
                elif j in bottom:
                    pooled_realized.append((_month_key(timestamps[ix[j]]),
                                            fy[j]))
    nets = [r["net_after_cost"] for r in per_offset
            if r["net_after_cost"] is not None]
    ics = [r["ic"] for r in per_offset if r["ic"] is not None]
    total_fired = sum(r["n_fired"] for r in per_offset)
    frac_pos = (sum(1 for x in nets if x > 0) / len(nets)) if nets else None
    # estabilidade mensal (sinal do realizado medio por mes)
    by_month: Dict[str, List[float]] = {}
    for m, r in pooled_realized:
        by_month.setdefault(m, []).append(r)
    month_means = {m: statistics.mean(v) for m, v in by_month.items()
                   if len(v) >= 2}
    months_pos = sum(1 for v in month_means.values() if v > 0)
    monthly_sign_consistency = (round(months_pos / len(month_means), 4)
                                if month_means else None)
    return {
        "horizon_bars": horizon,
        "offsets_tested": list(offsets),
        "per_offset": per_offset,
        "mean_net_after_cost": round(statistics.mean(nets), 6) if nets
        else None,
        "std_net_after_cost": round(statistics.pstdev(nets), 6)
        if len(nets) > 1 else 0.0,
        "frac_offsets_net_positive": round(frac_pos, 4)
        if frac_pos is not None else None,
        "mean_ic": round(statistics.mean(ics), 4) if ics else None,
        "std_ic": round(statistics.pstdev(ics), 4) if len(ics) > 1 else 0.0,
        "total_nonoverlap_fired": total_fired,
        "windows_per_offset": per_offset[0]["n_windows"] if per_offset else 0,
        "monthly_sign_consistency": monthly_sign_consistency,
        "n_months": len(month_means),
    }


# ---- criterio de sobrevivencia TRAVADO (definido ANTES de ver resultado) ----
SURVIVE = {
    "min_mean_net": 0.0,          # net medio apos custo > 0
    "min_frac_offsets_pos": 0.60,  # estavel em >60% dos offsets
    "min_monthly_consistency": 0.60,  # nao depende de 1 mes
    "min_total_fired": 30,        # amostra honesta
}


def survival_verdict(agg: Mapping[str, Any]) -> Tuple[str, Dict[str, bool]]:
    net = agg.get("mean_net_after_cost")
    frac = agg.get("frac_offsets_net_positive")
    msc = agg.get("monthly_sign_consistency")
    fired = agg.get("total_nonoverlap_fired") or 0
    checks = {
        "net_positive": net is not None and net > SURVIVE["min_mean_net"],
        "stable_across_offsets": frac is not None
        and frac >= SURVIVE["min_frac_offsets_pos"],
        "not_one_month": msc is not None
        and msc >= SURVIVE["min_monthly_consistency"],
        "sample_ok": fired >= SURVIVE["min_total_fired"],
    }
    if not checks["sample_ok"]:
        return "insufficient_sample", checks
    if all(checks.values()):
        return "survived", checks
    if not checks["net_positive"]:
        return "artifact_of_overlap", checks
    return "weak_unstable", checks


__all__ = [
    "nonoverlap_indices", "realized_mean_reversion", "validate_signal",
    "survival_verdict", "SURVIVE",
]
