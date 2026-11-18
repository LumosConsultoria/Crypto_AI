"""
Edge Research FASE 49 — Directional Signal Diagnostic Lab.
==========================================================
Mede o poder preditivo das features (feature_library) contra retornos futuros
(signal_diagnostics) em multiplos horizontes, no Bybit linear. NAO monta
estrategia. Roda em DEV+VAL (candles ja fatiados) => OOS preservado.

Saidas: relatorio por feature x horizonte (IC, quantis, net apos custo,
estabilidade mensal/regime, amostra) + diagnostico consolidado + (se houver
sinal claramente promissor) proposta de no maximo 1 hipotese p/ a proxima
fase. Sem ordem/demo/live; RiskEngine/ModeGuard/piso intactos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# horizontes em BARRAS de 1h
HORIZONS_1H = {"4h": 4, "12h": 12, "24h": 24, "3d": 72, "7d": 168}
REALISTIC_COST_PCT = 0.0026   # round-trip Bybit linear (26 bps)


@dataclass(frozen=True)
class SignalLabReport:
    schema: str
    symbol: str
    generated_at: str
    window: Mapping[str, Any]
    horizons: Mapping[str, int]
    features: Tuple[Mapping[str, Any], ...]
    diagnosis: Mapping[str, Any]
    proposal: Mapping[str, Any]
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at, "window": dict(self.window),
                "horizons": dict(self.horizons),
                "features": [dict(f) for f in self.features],
                "diagnosis": dict(self.diagnosis),
                "proposal": dict(self.proposal),
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def _best_horizon(per_h: Mapping[str, Mapping[str, Any]]) -> Tuple[str, float]:
    best_h, best_ic = "", 0.0
    for h, d in per_h.items():
        ic = d.get("ic_spearman")
        if ic is not None and abs(ic) > abs(best_ic):
            best_ic, best_h = ic, h
    return best_h, best_ic


def run_signal_lab(
    candles_base: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    base_minutes: int = 60, horizons: Optional[Mapping[str, int]] = None,
    cost_pct: float = REALISTIC_COST_PCT,
    window_label: str = "DEV+VAL", progress=None) -> SignalLabReport:
    from crypto_trading_bot.research.feature_library import (
        build_feature_library)
    from crypto_trading_bot.research.signal_diagnostics import (
        diagnose_feature, forward_returns)

    def _cb(m):
        if progress:
            progress(m)

    hz = dict(horizons or HORIZONS_1H)
    _cb("construindo feature library (causal)")
    feats, regime_by_idx, closes = build_feature_library(
        candles_base, funding_points=list(funding_points),
        oi_points=list(oi_points), base_minutes=base_minutes)
    timestamps = [c.timestamp for c in candles_base]
    fwd_by_h = {h: forward_returns(closes, bars) for h, bars in hz.items()}

    feature_reports: List[Dict[str, Any]] = []
    for name, series in feats.items():
        _cb(f"diagnostico: {name}")
        per_h: Dict[str, Any] = {}
        for h in hz:
            per_h[h] = diagnose_feature(
                name, series, fwd_by_h[h], timestamps=timestamps,
                regime_by_idx=regime_by_idx, cost_pct=cost_pct)
        bh, bic = _best_horizon(per_h)
        verdicts = [d["verdict"] for d in per_h.values()]
        real_h = [h for h, d in per_h.items() if d["verdict"]
                  == "real_relation"]
        feature_reports.append({
            "feature": name, "best_horizon": bh, "best_ic": round(bic, 4),
            "verdict_by_horizon": {h: per_h[h]["verdict"] for h in hz},
            "real_relation_horizons": real_h,
            "by_horizon": per_h,
        })

    # diagnostico consolidado
    def _bucket(pred):
        return [fr["feature"] for fr in feature_reports if pred(fr)]
    promising = [fr for fr in feature_reports
                 if len(fr["real_relation_horizons"]) >= 2
                 or (abs(fr["best_ic"]) >= 0.07
                     and fr["real_relation_horizons"])]
    diagnosis = {
        "real_relation": _bucket(lambda fr: fr["real_relation_horizons"]),
        "noise": _bucket(lambda fr: all(v == "noise" for v in
                                        fr["verdict_by_horizon"].values())),
        "regime_specific": _bucket(lambda fr: any(
            v == "regime_specific" for v in fr["verdict_by_horizon"].values())
            and not fr["real_relation_horizons"]),
        "dies_after_cost": _bucket(lambda fr: any(
            v == "dies_after_cost" for v in fr["verdict_by_horizon"].values())
            and not fr["real_relation_horizons"]),
        "insufficient_sample": _bucket(lambda fr: all(
            v == "insufficient_sample"
            for v in fr["verdict_by_horizon"].values())),
        "promising": [fr["feature"] for fr in promising],
    }

    # proposta (no maximo 1 hipotese) SO se houver sinal claramente promissor
    if promising:
        top = max(promising, key=lambda fr: abs(fr["best_ic"]))
        # padrao dominante: sinais promissores tem IC negativo em 3-7d =>
        # mean-reversion de extremos a MULTI-DIA.
        long_h = top["best_horizon"] in ("3d", "7d")
        proposal = {
            "has_signal": True,
            "dominant_pattern": ("multi-day mean-reversion de EXTENSAO: "
                                 "funding/trend/preco extremos REVERTEM em "
                                 "3-7d (IC negativo no longo horizonte; ruido "
                                 "no curto)"),
            "feature": top["feature"],
            "best_horizon": top["best_horizon"],
            "best_ic": top["best_ic"],
            "hypothesis": ("SWING mean-reversion multi-dia (hold 3-7d): entrar "
                           "CONTRA a extensao quando funding extremo + preco "
                           "estendido coincidem; stop largo (4h) e alvo na "
                           "media; DEV/VAL/OOS protegido."),
            "why_different": ("Difere de F1 funding-fade (INTRADAY 15m, stop "
                              "estrutural) e de mean-reversion simples "
                              "(intraday/range) pelo HORIZONTE (swing 3-7d, "
                              "onde o lab realmente mede edge) e pela "
                              "COMBINACAO funding+extensao; sinal medido ANTES "
                              "de montar estrategia."),
            "caveats": [
                ("JANELAS SOBREPOSTAS: em 3-7d com passo 1h, observacoes "
                 "vizinhas se sobrepoem ~167/168 => amostra efetiva ~N/168 "
                 "(~54 janelas 7d). IC/estabilidade SUPERESTIMADOS; VALIDAR "
                 "com janelas NAO-sobrepostas antes de montar estrategia."),
                ("ADJACENTE a familias rejeitadas (funding-fade/mean-reversion);"
                 " so se justifica pela mudanca de horizonte (swing) + "
                 "combinacao de sinais."),
                ("net apos custo FINO (~0,5-1,1% por trade de 7d); hold de 7d "
                 "cruza ~21 eventos de funding e exige stop largo => modelar "
                 "custo/funding/risco e teto 5% com cuidado."),
                ("funding_rate ~ funding_pctile (mesmo fator); trend/range/ema "
                 "sao extensao correlacionada => essencialmente 1 sinal."),
            ],
            "note": ("Proxima fase: NO MAXIMO 1 hipotese; primeiro VALIDAR o "
                     "efeito 3-7d com janelas nao-sobrepostas; OOS intocado."),
        }
        if not long_h:
            proposal["note"] += " (Atencao: melhor IC fora de 3-7d.)"
    else:
        proposal = {
            "has_signal": False,
            "conclusion": ("Com os dados atuais (Bybit linear 1h + funding/OI, "
                           "DEV+VAL), nenhuma feature mostra edge direcional "
                           "suficiente (IC fraco/ruido/morre apos custo/regime/"
                           "amostra). BTCUSDT direcional NAO mostra edge."),
            "recommendation": ("Mudar abordagem (nao-direcional / execucao / "
                               "carry), dados (microestrutura/orderbook/L2, "
                               "on-chain) ou universo (outros ativos/regimes). "
                               "Nao insistir em variacoes ja exauridas."),
        }

    return SignalLabReport(
        schema="signal_diagnostic_lab_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        window={"label": window_label, "n_candles": len(candles_base),
                "first": str(timestamps[0]) if timestamps else None,
                "last": str(timestamps[-1]) if timestamps else None},
        horizons=hz, features=tuple(feature_reports), diagnosis=diagnosis,
        proposal=proposal,
        notes=("Lab de diagnostico (feature x retorno futuro); NENHUMA "
               "estrategia montada. net apos custo 26bps. OOS preservado "
               "(forward returns fora da janela descartados).",
               "Hyro 5k = perfil operacional; demo/live bloqueados.",))


__all__ = ["HORIZONS_1H", "SignalLabReport", "run_signal_lab"]
