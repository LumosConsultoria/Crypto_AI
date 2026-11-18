"""
Edge Research FASE 62 — H1 variance_ratio_regime_switch_1h (BTCUSDT 1h).
========================================================================
ULTIMA tentativa preditiva BTCUSDT-only. Params PRE-FIXADOS; sem grid; sem
tuning corretivo. Custos reais Bybit + funding no net; dual-profile
(hyro_challenge_attempts + standard_trader_monthly_close); gate dos 8 criterios
(FASE 59) por segmento. DEV primeiro; VAL SO se DEV passar TODOS; OOS intocado.
0,5% primario + 1% sensibilidade separada. IA/Polymarket/MI so shadow/veto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase47 import BYBIT_COST_BPS
from crypto_trading_bot.research.edge_research_phase53 import _run53
from crypto_trading_bot.research.edge_research_phase59 import _gate, _reason
from crypto_trading_bot.research.effective_config import build_effective_config

_VR_FORMULA = ("VR = Var(rq)/(q*Var(r1)) sobre janela W=24 candles 1h fechados; "
               "r1[t]=close[t]/close[t-1]-1; rq[t]=close[t]/close[t-q]-1; q=2. "
               "VR>=1,10 momentum (segue); VR<=0,90 mean-reversion (fade); "
               "0,90<VR<1,10 NEUTRO (nao opera). Entrada no candle SEGUINTE.")


def _spec():
    from crypto_trading_bot.research.research_loop import HypothesisSpec
    from crypto_trading_bot.research.variance_ratio_family import H1_PARAMS
    return HypothesisSpec(
        name="variance_ratio_regime_switch_1h",
        economic_rationale=("BTC alterna regimes momentum (VR>1) e mean-reversion "
                            "(VR<1); aplicar a regra compativel ao regime medido "
                            "pode capturar onde cada base falhou isolada."),
        why_different=("condiciona pela AUTOCORRELACAO (variance ratio), eixo "
                       "estatistico nunca usado (antes so vol-percentil); decide "
                       "QUAL regra simples aplicar."),
        data_used=["ohlcv"], fixed_params=dict(H1_PARAMS),
        accept_criteria=("DEV->VAL: net>0/PF>=1,15/exp>0/>=100tr/sc>=0,60/"
                         ">=3meses/Hyro attempts>=3/class!=sem_edge/CI ok"),
        expected_reason_to_work="regime-matching evita momentum em chop e MR em "
                                "tendencia.",
        family="statistical_regime_switch", variants=1)


@dataclass(frozen=True)
class EdgeResearch62Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    loop: Mapping[str, Any]
    hypothesis: Mapping[str, Any]
    decision: str
    reason: str
    confirmations: Mapping[str, Any]
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments), "loop": dict(self.loop),
                "hypothesis": dict(self.hypothesis), "decision": self.decision,
                "reason": self.reason, "confirmations": dict(self.confirmations),
                "real_execution_allowed": False, "orders_emitted": 0,
                "demo_blocked": True, "live_blocked": True,
                "strategy_promoted": False, "notes": list(self.notes)}


def run_edge_research62(
    candles_1h: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    operator_store=None, wf_folds: int = 5, progress=None
) -> EdgeResearch62Report:
    from crypto_trading_bot.research.perp_signals import build_perp_features
    from crypto_trading_bot.research.research_loop import run_research_loop
    from crypto_trading_bot.research.variance_ratio_family import (
        H1_HOLD_BARS, detect_variance_ratio_regime_switch)

    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store)
    rc05 = eff.risk_config
    rc1 = rc05.model_copy(update={"max_risk_per_trade_pct": 0.01})
    pf = build_perp_features(candles_1h, interval_minutes=60,
                             funding_points=list(funding_points),
                             oi_points=list(oi_points))
    funding_events = pf.funding_events
    setups = detect_variance_ratio_regime_switch(candles_1h)
    _cb(f"H1 VR: {len(setups)} setups 1h")
    mc = 60

    reports: Dict[str, Dict[str, Any]] = {}

    def evaluator(spec, segment):
        seg_dates = dev if segment == "DEV" else val
        m = _run53(setups, candles_1h, seg_dates=seg_dates, risk_config=rc05,
                   risk_base_pct=0.005, funding_events=funding_events,
                   wf_folds=wf_folds, min_candles=mc, segment_label=segment,
                   eff=eff, family_id=spec.name, max_holding=H1_HOLD_BARS)
        base = m["standard_report"]
        gate = _gate(base)
        ret = dict(base)
        v = dict(base.get("verdict", {}) or {})
        v["edge_estatistico"] = "aprovado" if gate["passed"] else "rejeitado"
        ret["verdict"] = v
        ret["phase59_gate"] = gate
        reports.setdefault(spec.name, {})[segment] = ret
        return ret

    _cb("research loop (DEV; VAL so se DEV passar; OOS intocado)")
    loop = run_research_loop([_spec()], evaluator, progress=progress)

    name = "variance_ratio_regime_switch_1h"
    dev_sr = reports.get(name, {}).get("DEV", {})
    val_sr = reports.get(name, {}).get("VAL")
    m1 = _run53(setups, candles_1h, seg_dates=dev, risk_config=rc1,
                risk_base_pct=0.01, funding_events=funding_events,
                wf_folds=None, min_candles=mc, segment_label="DEV", eff=eff,
                family_id=name, max_holding=H1_HOLD_BARS)
    dsm = dev_sr.get("strategy_metrics", {}) or {}
    hyp = {
        "name": name, "n_setups": len(setups),
        "variance_ratio_formula": _VR_FORMULA,
        "params_prefixed": dict(_spec().fixed_params),
        "dev": {"classification": dev_sr.get("classification"),
                "verdict": dev_sr.get("verdict"),
                "gate": dev_sr.get("phase59_gate"),
                "strategy_metrics": dsm,
                "temporal_breakdown": dev_sr.get("temporal_breakdown"),
                "hyro_challenge_attempts": dev_sr.get("hyro_challenge_attempts"),
                "standard_trader_monthly_close": dev_sr.get(
                    "standard_trader_monthly_close")},
        "sensitivity_1pct_separate": {
            "note": "risco 1% — sensibilidade SEPARADA, fora da decisao (0,5%)",
            "trader_padrao_dev": m1["standard_report"].get(
                "standard_trader_evaluation")},
    }
    if val_sr is not None:
        hyp["val"] = {"classification": val_sr.get("classification"),
                      "verdict": val_sr.get("verdict"),
                      "gate": val_sr.get("phase59_gate"),
                      "strategy_metrics": val_sr.get("strategy_metrics"),
                      "standard_trader_monthly_close": val_sr.get(
                          "standard_trader_monthly_close")}

    ld = loop.to_dict()
    if ld["candidate"]:
        decision = "CANDIDATA_PENDENTE_APROVACAO_OOS"
        reason = ("DEV E VAL atenderam TODOS os criterios. Candidata, NAO "
                  "validada; pedir aprovacao antes do OOS.")
    elif val_sr is None:
        decision = "REJEITAR"
        reason = "DEV reprovado (VAL nao consultado, sem tuning). " + _reason(dev_sr)
    else:
        decision = "REJEITAR"
        reason = ("DEV passou mas VAL reprovou (sem tuning corretivo). "
                  + _reason(val_sr))

    confirmations = {
        "val_consulted": val_sr is not None,
        "val_not_consulted_because_dev_failed": (val_sr is None
                                                 and not ld["candidate"]),
        "oos_consulted": False, "oos_untouched": True,
        "demo_blocked": True, "live_blocked": True, "orders_emitted": 0,
        "ranking_decision_uses_only_0_5pct": True,
        "one_pct_is_sensitivity_only": True,
        "ai_polymarket_role": "shadow/veto/decision_trace apenas; nunca "
                              "compra/venda/sizing/risco",
    }
    return EdgeResearch62Report(
        schema="edge_research_phase62_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "market": "bybit_linear_perp_1h",
                  "cost_bps": BYBIT_COST_BPS,
                  "dev_val_criteria": {"min_trades": 100, "pf_min": 1.15,
                                       "sign_consistency_min": 0.60,
                                       "min_active_months": 3,
                                       "min_hyro_attempts": 3},
                  "effective_config": eff.to_dict(),
                  "note": "OOS travado (so DEV+VAL; loop nunca avalia OOS)."},
        loop=ld, hypothesis=hyp, decision=decision, reason=reason,
        confirmations=confirmations,
        notes=("H1 VR-regime-switch 1h: params PRE-FIXADOS, sem grid; VR causal "
               "(so candles fechados); entrada no candle seguinte; custos reais "
               "+ funding; dual-profile; gate 8 criterios por segmento; VAL so "
               "apos DEV; OOS intocado; 1% separado; sem tuning corretivo.",
               _VR_FORMULA,))


__all__ = ["EdgeResearch62Report", "run_edge_research62"]
