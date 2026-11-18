"""
Edge Research FASE 52 — Funding-MR Robustness-by-Regime Diagnostic (BTC only).
==============================================================================
Perpetual-ONLY (sem spot/basis). NAO monta estrategia. Investiga POR QUE o
funding-MR (F5) passou DEV e falhou VAL: o edge se CONCENTRA num regime
PRE-ESPECIFICADO de volatilidade (taxonomia ja existente: lowvol/midvol/
highvol) de forma ROBUSTA (DEV **e** VAL, janelas NAO-sobrepostas)? Ou e
instabilidade temporal (sorte do DEV)?

Metodo (sem tuning na VAL): features causais sobre DEV+VAL; o regime e uma
taxonomia FIXA; mede-se o net da hipotese mean-reversion (direcao FIXA) em
janelas DISJUNTAS, OVERALL e POR REGIME, no DEV e no VAL separadamente. O
regime "vencedor" e identificado NO DEV e apenas VALIDADO no VAL. OOS intocado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.nonoverlap_validation import (
    survival_verdict, validate_signal)
from crypto_trading_bot.research.signal_diagnostics import forward_returns

HORIZONS = {"3d": 72, "7d": 168}
SIGNALS = ("funding_rate", "funding_pctile")
REGIMES = ("lowvol", "midvol", "highvol")
REALISTIC_COST = 0.0026


def _parse(d: str) -> datetime:
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _utc(ts):
    return ts.replace(tzinfo=timezone.utc) if getattr(ts, "tzinfo", None) \
        is None else ts


def _masked(feature, timestamps, regime_by_idx, seg, regime):
    lo, hi = _parse(seg[0]), _parse(seg[1])
    out = []
    for i, ts in enumerate(timestamps):
        t = _utc(ts)
        in_seg = lo <= t < hi
        in_reg = (regime is None) or (regime_by_idx.get(i) == regime)
        out.append(feature[i] if (in_seg and in_reg
                                  and feature[i] is not None) else None)
    return out


def _validate(feature, fwd, *, n, horizon, timestamps, regime_by_idx, seg,
              regime, cost):
    masked = _masked(feature, timestamps, regime_by_idx, seg, regime)
    offsets = list(range(0, horizon, 24))
    agg = validate_signal(masked, fwd, n=n, horizon=horizon, offsets=offsets,
                          timestamps=timestamps, cost_pct=cost)
    verdict, checks = survival_verdict(agg)
    return {"survival": verdict, "checks": checks,
            "mean_net_after_cost": agg.get("mean_net_after_cost"),
            "frac_offsets_net_positive": agg.get("frac_offsets_net_positive"),
            "monthly_sign_consistency": agg.get("monthly_sign_consistency"),
            "total_fired": agg.get("total_nonoverlap_fired"),
            "mean_ic": agg.get("mean_ic")}


@dataclass(frozen=True)
class RegimeDiagnosticReport:
    schema: str
    symbol: str
    generated_at: str
    window: Mapping[str, Any]
    signals: Tuple[Mapping[str, Any], ...]
    gate: Mapping[str, Any]
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at, "window": dict(self.window),
                "signals": [dict(s) for s in self.signals],
                "gate": dict(self.gate),
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def run_regime_diagnostic(
    candles_dev_val: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    cost_pct: float = REALISTIC_COST, progress=None) -> RegimeDiagnosticReport:
    from crypto_trading_bot.research.feature_library import (
        build_feature_library)

    def _cb(m):
        if progress:
            progress(m)

    _cb("feature library (causal, perp-native)")
    feats, regime_by_idx, closes = build_feature_library(
        candles_dev_val, funding_points=list(funding_points),
        oi_points=list(oi_points), base_minutes=60)
    n = len(candles_dev_val)
    timestamps = [c.timestamp for c in candles_dev_val]
    fwd_by_h = {h: forward_returns(closes, bars) for h, bars in HORIZONS.items()}

    sig_reports: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []
    for sig in SIGNALS:
        feature = feats.get(sig)
        if feature is None:
            continue
        _cb(f"diagnostico regime: {sig}")
        per_h: Dict[str, Any] = {}
        for h, bars in HORIZONS.items():
            overall_dev = _validate(feature, fwd_by_h[h], n=n, horizon=bars,
                                    timestamps=timestamps,
                                    regime_by_idx=regime_by_idx, seg=dev,
                                    regime=None, cost=cost_pct)
            overall_val = _validate(feature, fwd_by_h[h], n=n, horizon=bars,
                                    timestamps=timestamps,
                                    regime_by_idx=regime_by_idx, seg=val,
                                    regime=None, cost=cost_pct)
            by_regime = {}
            for reg in REGIMES:
                dev_r = _validate(feature, fwd_by_h[h], n=n, horizon=bars,
                                  timestamps=timestamps,
                                  regime_by_idx=regime_by_idx, seg=dev,
                                  regime=reg, cost=cost_pct)
                val_r = _validate(feature, fwd_by_h[h], n=n, horizon=bars,
                                  timestamps=timestamps,
                                  regime_by_idx=regime_by_idx, seg=val,
                                  regime=reg, cost=cost_pct)
                robust = (dev_r["survival"] == "survived"
                          and val_r["survival"] == "survived")
                by_regime[reg] = {"dev": dev_r, "val": val_r,
                                  "robust_dev_and_val": robust}
                if robust:
                    survivors.append({"signal": sig, "horizon": h,
                                      "regime": reg,
                                      "dev_net": dev_r["mean_net_after_cost"],
                                      "val_net": val_r["mean_net_after_cost"]})
            per_h[h] = {"overall_dev": overall_dev, "overall_val": overall_val,
                        "by_regime": by_regime}
        sig_reports.append({"signal": sig, "by_horizon": per_h})

    if survivors:
        gate = {
            "verdict": "SOBREVIVE",
            "survivors": survivors,
            "decision": "PROPOR_HIPOTESE_FASE53",
            "hypothesis": ("Funding-MR GATED por regime de volatilidade "
                           "PRE-especificado (so opera no regime onde o edge e "
                           "robusto em DEV E VAL nao-sobreposto), hold no "
                           "horizonte sobrevivente. Estruturalmente diferente: "
                           "CONDICIONADA a regime medido antes, nao funding/"
                           "preco sozinho."),
            "note": "FASE 53: 1 hipotese; OOS intocado ate DEV+VAL.",
        }
    else:
        gate = {
            "verdict": "NAO_SOBREVIVE",
            "decision": "ENCERRAR_LINHA_BTC_DIRECIONAL_FUNDING",
            "conclusion": ("O edge funding-MR NAO e robustamente concentrado em "
                           "nenhum regime pre-especificado (falha em DEV e/ou "
                           "VAL nao-sobreposto, ou amostra insuficiente). "
                           "Confirma: instabilidade temporal, nao regime "
                           "explorvel. F5/funding-swing => hipotese REJEITADA."),
            "recommendation": ("Encerrar a linha BTCUSDT direcional/funding-"
                               "swing por ora; manter IA/Polymarket shadow; "
                               "FASE 53 = coleta PROSPECTIVA de liquidacoes/"
                               "orderbook (perp-native, sem historico publico) "
                               "antes de nova estrategia."),
        }

    return RegimeDiagnosticReport(
        schema="funding_mr_regime_diagnostic_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        window={"dev": dev, "val": val, "n_candles": n,
                "first": str(timestamps[0]) if timestamps else None,
                "last": str(timestamps[-1]) if timestamps else None,
                "perpetual_only": True, "spot_used": False},
        signals=tuple(sig_reports), gate=gate,
        notes=("Perp-only (sem spot/basis). Regime = taxonomia FIXA de vol; "
               "regime vencedor identificado no DEV e VALIDADO no VAL (sem "
               "tuning na VAL). Janelas nao-sobrepostas (FASE 50). OOS "
               "intocado. NENHUMA estrategia montada.",
               "Liquidacoes/orderbook: sem historico publico => prospectivo. "
               "premium index: redundante com funding => fora. Demo/live "
               "bloqueados.",))


__all__ = ["HORIZONS", "SIGNALS", "REGIMES", "RegimeDiagnosticReport",
           "run_regime_diagnostic"]
