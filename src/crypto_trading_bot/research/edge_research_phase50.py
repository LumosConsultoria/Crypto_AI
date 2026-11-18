"""
Edge Research FASE 50 — validacao NAO-SOBREPOSTA do sinal de mean-reversion
multi-dia (FASE 49). Bybit linear, DEV+VAL, OOS preservado.
==========================================================================
Foca SO nos sinais promissores da FASE 49 (funding_rate, funding_pctile,
trend_4h_slope, dist_from_ema_atr, range_pos_50) + 1 combinacao simples
(funding + extensao alinhada). Para 3d/5d/7d, amostra janelas DISJUNTAS em
varios offsets e mede se o net (apos custo) SOBREVIVE. Side-by-side vs o
resultado SOBREPOSTO (FASE 49). NAO monta estrategia (salvo proposta p/ 51 se
sobreviver). Criterio de sobrevivencia TRAVADO (nonoverlap_validation.SURVIVE).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.nonoverlap_validation import (
    realized_mean_reversion,
    survival_verdict,
    validate_signal,
)
from crypto_trading_bot.research.signal_diagnostics import forward_returns

# horizontes em barras de 1h
HORIZONS = {"3d": 72, "5d": 120, "7d": 168}
CANDIDATE_SIGNALS = ("funding_rate", "funding_pctile", "trend_4h_slope",
                     "dist_from_ema_atr", "range_pos_50",
                     "funding_plus_extension")
REALISTIC_COST = 0.0026


def _offsets(horizon: int, step: int = 24) -> List[int]:
    return list(range(0, horizon, step))


def _overlapping_net(feature, fwd, *, cost_pct):
    """Net da hipotese mean-reversion usando TODOS os indices (sobreposto,
    estilo FASE 49) — p/ comparacao lado a lado."""
    fx, fy = [], []
    for a, b in zip(feature, fwd):
        if a is None or b is None:
            continue
        try:
            if a != a or b != b:   # NaN
                continue
        except TypeError:
            continue
        fx.append(float(a)); fy.append(float(b))
    return realized_mean_reversion(fx, fy, cost_pct=cost_pct)


@dataclass(frozen=True)
class NonOverlapReport:
    schema: str
    symbol: str
    generated_at: str
    window: Mapping[str, Any]
    signals: Tuple[Mapping[str, Any], ...]
    diagnosis: Mapping[str, Any]
    decision: Mapping[str, Any]
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at, "window": dict(self.window),
                "survival_criterion": _criterion_dict(),
                "signals": [dict(s) for s in self.signals],
                "diagnosis": dict(self.diagnosis),
                "decision": dict(self.decision),
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def _criterion_dict():
    from crypto_trading_bot.research.nonoverlap_validation import SURVIVE
    return dict(SURVIVE)


def _build_combination(feats, n):
    """funding + extensao ALINHADA (causal): funding_pctile (0..1) +
    range_pos_50 (0..1) => alto quando ambos estendidos p/ cima."""
    fp = feats.get("funding_pctile") or [None] * n
    rp = feats.get("range_pos_50") or [None] * n
    out = []
    for i in range(n):
        a, b = fp[i], rp[i]
        out.append((a + b) if (a is not None and b is not None) else None)
    return out


def run_nonoverlap_validation(
    candles_base: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    base_minutes: int = 60, cost_pct: float = REALISTIC_COST,
    window_label: str = "DEV+VAL", progress=None) -> NonOverlapReport:
    from crypto_trading_bot.research.feature_library import (
        build_feature_library)

    def _cb(m):
        if progress:
            progress(m)

    _cb("feature library (causal)")
    feats, _regime, closes = build_feature_library(
        candles_base, funding_points=list(funding_points),
        oi_points=list(oi_points), base_minutes=base_minutes)
    n = len(candles_base)
    timestamps = [c.timestamp for c in candles_base]
    feats["funding_plus_extension"] = _build_combination(feats, n)
    fwd_by_h = {h: forward_returns(closes, bars) for h, bars in HORIZONS.items()}

    signal_reports: List[Dict[str, Any]] = []
    for sig in CANDIDATE_SIGNALS:
        series = feats.get(sig)
        if series is None:
            continue
        _cb(f"validando {sig}")
        per_h = {}
        survived_horizons = []
        for h, bars in HORIZONS.items():
            agg = validate_signal(
                series, fwd_by_h[h], n=n, horizon=bars,
                offsets=_offsets(bars), timestamps=timestamps,
                cost_pct=cost_pct)
            verdict, checks = survival_verdict(agg)
            ov = _overlapping_net(series, fwd_by_h[h], cost_pct=cost_pct)
            per_h[h] = {
                "nonoverlap": agg, "survival": verdict, "checks": checks,
                "overlapping_fase49": {
                    "net_after_cost": ov.get("net_after_cost"),
                    "ic": ov.get("ic"), "n_fired": ov.get("n_fired")},
                "side_by_side": {
                    "overlapping_net": ov.get("net_after_cost"),
                    "nonoverlap_mean_net": agg.get("mean_net_after_cost"),
                    "overlapping_ic": ov.get("ic"),
                    "nonoverlap_mean_ic": agg.get("mean_ic")},
            }
            if verdict == "survived":
                survived_horizons.append(h)
        signal_reports.append({
            "signal": sig, "survived_horizons": survived_horizons,
            "by_horizon": per_h})

    survivors = [s["signal"] for s in signal_reports if s["survived_horizons"]]
    diagnosis = {
        "survivors": survivors,
        "artifact_of_overlap": [
            s["signal"] for s in signal_reports
            if not s["survived_horizons"] and any(
                v["survival"] == "artifact_of_overlap"
                for v in s["by_horizon"].values())],
        "weak_unstable": [
            s["signal"] for s in signal_reports
            if not s["survived_horizons"] and any(
                v["survival"] == "weak_unstable"
                for v in s["by_horizon"].values())],
        "insufficient_sample": [
            s["signal"] for s in signal_reports
            if all(v["survival"] == "insufficient_sample"
                   for v in s["by_horizon"].values())],
        "conclusion": ("sinal SOBREVIVEU sem sobreposicao"
                       if survivors else
                       "sinal NAO sobreviveu => era artefato de sobreposicao "
                       "(ou fraco/instavel)"),
    }

    if survivors:
        decision = {
            "verdict": "PROPOR_HIPOTESE_FASE51",
            "survivors": survivors,
            "hypothesis": ("SWING mean-reversion multi-dia (hold ~o horizonte "
                           "sobrevivente) contra EXTENSAO (funding extremo "
                           "[+ preco estendido]); stop largo (<=5%), alvo na "
                           "media; DEV/VAL/OOS protegido; standard_report + "
                           "net incl funding + verdict Hyro."),
            "why_different": ("Horizonte SWING 3-7d validado SEM sobreposicao; "
                              "difere de F1 funding-fade (intraday) e de "
                              "mean-reversion simples (intraday/range)."),
            "note": "FASE 51: no maximo 1 hipotese; OOS intocado ate DEV+VAL.",
        }
    else:
        decision = {
            "verdict": "REJEITAR",
            "conclusion": ("O sinal multi-dia da FASE 49 NAO sobrevive a "
                           "validacao nao-sobreposta => era em grande parte "
                           "ARTEFATO de janelas sobrepostas. Com os dados "
                           "atuais, BTCUSDT direcional NAO mostra edge "
                           "suficiente."),
            "recommendation": ("Mudar ABORDAGEM (nao-direcional / execucao / "
                               "carry/market-making), DADOS (microestrutura/"
                               "orderbook L2, on-chain, liquidacoes) ou "
                               "UNIVERSO (outros ativos). Nao insistir em "
                               "direcional BTC com OHLCV+funding+OI."),
        }

    return NonOverlapReport(
        schema="nonoverlap_validation_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        window={"label": window_label, "n_candles": n,
                "first": str(timestamps[0]) if timestamps else None,
                "last": str(timestamps[-1]) if timestamps else None},
        signals=tuple(signal_reports), diagnosis=diagnosis, decision=decision,
        notes=("Validacao NAO-sobreposta (janelas disjuntas, multiplos "
               "offsets); direcao FIXA da hipotese (mean-reversion). Criterio "
               "de sobrevivencia TRAVADO antes do resultado.",
               "OOS preservado; sem ordem/demo/live; Hyro 5k = perfil.",))


__all__ = ["HORIZONS", "CANDIDATE_SIGNALS", "NonOverlapReport",
           "run_nonoverlap_validation"]
