"""
Edge Research FASE 59 — H1 failed_breakout_fade_5m (BTCUSDT 5m).
================================================================
UNICA hipotese aprovada (H1). Params PRE-FIXADOS; sem grid; sem tuning corretivo.
Dual-profile via standard_report (hyro_challenge_attempts +
standard_trader_monthly_close); custos reais Bybit (fee+slippage+spread) +
FUNDING no net. DEV primeiro; VAL SO se DEV passar TODOS os criterios; OOS
intocado. 0,5% primario + 1% separado.

CRITERIO DEV->VAL (operador, EXPLICITO; aplicado a CADA segmento via _gate):
net>0, PF>=1,15, expectancy>0, >=100 trades, sign_consistency mensal>=0,60,
>=3 meses ativos, Hyro attempts>=3, classification != sem_edge_operacional, e
CI/bootstrap nao invalida o edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase47 import BYBIT_COST_BPS
from crypto_trading_bot.research.edge_research_phase53 import _run53
from crypto_trading_bot.research.effective_config import build_effective_config

# criterios EXPLICITOS DEV->VAL (operador)
MIN_TRADES = 100
MIN_ACTIVE_MONTHS = 3
MIN_HYRO_ATTEMPTS = 3
PF_MIN = 1.15
SIGN_CONSISTENCY_MIN = 0.60


def _gate(sr: Mapping[str, Any]) -> Dict[str, Any]:
    """Aplica os 8 criterios DEV->VAL ao standard_report (base). Retorna
    {passed, checks}. CI: usa o edge_estatistico BASE (que ja exige
    net>0/PF/expectancy E CI bootstrap inferior>=0)."""
    v = sr.get("verdict", {}) or {}
    sm = sr.get("strategy_metrics", {}) or {}
    tb = sr.get("temporal_breakdown", {}) or {}
    att = sr.get("hyro_challenge_attempts", {}) or {}
    pf = sm.get("profit_factor_net")
    checks = {
        "net_positive": (sm.get("net_pnl_usd") or 0) > 0,
        "pf_ge_1_15": pf is not None and pf >= PF_MIN,
        "expectancy_positive": (sm.get("expectancy_net_usd") or 0) > 0,
        "trades_ge_100": (sm.get("num_trades") or 0) >= MIN_TRADES,
        "sign_consistency_ge_060": (tb.get("sign_consistency") or 0)
        >= SIGN_CONSISTENCY_MIN,
        "active_months_ge_3": (tb.get("months_total") or 0) >= MIN_ACTIVE_MONTHS,
        "hyro_attempts_ge_3": (att.get("total_attempts") or 0)
        >= MIN_HYRO_ATTEMPTS,
        "ci_not_invalidating": v.get("edge_estatistico") == "aprovado",
        "classification_not_sem_edge": sr.get("classification")
        != "sem_edge_operacional",
    }
    return {"passed": all(checks.values()), "checks": checks}


def _reason(sr: Mapping[str, Any]) -> str:
    g = sr.get("phase59_gate") or {}
    failed = [k for k, ok in (g.get("checks") or {}).items() if not ok]
    sm = sr.get("strategy_metrics", {}) or {}
    return (f"criterios NAO atendidos: {failed} (trades="
            f"{sm.get('num_trades')} PF={sm.get('profit_factor_net')} "
            f"net={sm.get('net_pnl_usd')})") if failed else "ok"


def _spec():
    from crypto_trading_bot.research.failed_breakout_family import H1_PARAMS
    from crypto_trading_bot.research.research_loop import HypothesisSpec
    return HypothesisSpec(
        name="failed_breakout_fade_5m",
        economic_rationale=("rompimentos FALHOS (stop-run) revertem: quem "
                            "entrou no breakout e estopado e vira combustivel."),
        why_different=("NAO segue o breakout (!=breakout_trend) e NAO e MR "
                       "generico (!=mean_reversion): exige o EVENTO de fakeout."),
        data_used=["ohlcv"], fixed_params=dict(H1_PARAMS),
        accept_criteria=("DEV->VAL: net>0/PF>=1,15/expectancy>0/>=100tr/"
                         "sc>=0,60/>=3meses/Hyro attempts>=3/class!=sem_edge/CI ok"),
        expected_reason_to_work=("absorcao do overshoot pos-liquidez forcada; "
                                 "gate de regime 1h evita fade contra tendencia."),
        family="failed_breakout_reversal", variants=1)


@dataclass(frozen=True)
class EdgeResearch59Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    loop: Mapping[str, Any]
    hypothesis: Mapping[str, Any]
    decision: str
    reason: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments), "loop": dict(self.loop),
                "hypothesis": dict(self.hypothesis), "decision": self.decision,
                "reason": self.reason, "real_execution_allowed": False,
                "demo_blocked": True, "live_blocked": True,
                "strategy_promoted": False, "notes": list(self.notes)}


def run_edge_research59(
    candles_5m: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    operator_store=None, wf_folds: int = 5, progress=None
) -> EdgeResearch59Report:
    from crypto_trading_bot.research.failed_breakout_family import (
        H1_HOLD_BARS, build_regime_slope_1h, detect_failed_breakout_fade)
    from crypto_trading_bot.research.perp_signals import build_perp_features
    from crypto_trading_bot.research.research_loop import run_research_loop

    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store)
    rc05 = eff.risk_config
    rc1 = rc05.model_copy(update={"max_risk_per_trade_pct": 0.01})
    pf = build_perp_features(candles_5m, interval_minutes=5,
                             funding_points=list(funding_points),
                             oi_points=list(oi_points))
    funding_events = pf.funding_events
    _cb("regime 1h (contexto, causal)")
    slope = build_regime_slope_1h(candles_5m)
    setups = detect_failed_breakout_fade(candles_5m, regime_slope_1h=slope)
    _cb(f"H1: {len(setups)} setups 5m")
    mc = 200

    reports: Dict[str, Dict[str, Any]] = {}

    def evaluator(spec, segment):
        seg_dates = dev if segment == "DEV" else val
        m = _run53(setups, candles_5m, seg_dates=seg_dates, risk_config=rc05,
                   risk_base_pct=0.005, funding_events=funding_events,
                   wf_folds=wf_folds, min_candles=mc, segment_label=segment,
                   eff=eff, family_id=spec.name, max_holding=H1_HOLD_BARS)
        base = m["standard_report"]
        gate = _gate(base)
        ret = dict(base)
        v = dict(base.get("verdict", {}) or {})
        # "DEV passa" <=> TODOS os 8 criterios; edge reflete o gate
        v["edge_estatistico"] = "aprovado" if gate["passed"] else "rejeitado"
        ret["verdict"] = v
        ret["phase59_gate"] = gate
        reports.setdefault(spec.name, {})[segment] = ret
        return ret

    _cb("research loop (DEV; VAL so se DEV passar; OOS intocado)")
    loop = run_research_loop([_spec()], evaluator, progress=progress)

    name = "failed_breakout_fade_5m"
    dev_sr = reports.get(name, {}).get("DEV", {})
    val_sr = reports.get(name, {}).get("VAL")
    m1 = _run53(setups, candles_5m, seg_dates=dev, risk_config=rc1,
                risk_base_pct=0.01, funding_events=funding_events,
                wf_folds=None, min_candles=mc, segment_label="DEV", eff=eff,
                family_id=name, max_holding=H1_HOLD_BARS)
    hyp = {
        "name": name, "n_setups": len(setups),
        "params_prefixed": dict(_spec().fixed_params),
        "dev": {"classification": dev_sr.get("classification"),
                "verdict": dev_sr.get("verdict"),
                "gate": dev_sr.get("phase59_gate"),
                "strategy_metrics": dev_sr.get("strategy_metrics"),
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
        reason = ("DEV E VAL atenderam TODOS os criterios (dual-profile). "
                  "Candidata, NAO validada; pedir aprovacao antes do OOS.")
    elif val_sr is None:
        decision = "REJEITAR"
        reason = "DEV reprovado (VAL nao consultado, sem tuning). " + _reason(dev_sr)
    else:
        decision = "REJEITAR"
        reason = ("DEV passou mas VAL reprovou (sem tuning corretivo). "
                  + _reason(val_sr))

    return EdgeResearch59Report(
        schema="edge_research_phase59_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "market": "bybit_linear_perp_5m",
                  "cost_bps": BYBIT_COST_BPS,
                  "dev_val_criteria": {"min_trades": MIN_TRADES,
                                       "pf_min": PF_MIN,
                                       "sign_consistency_min": SIGN_CONSISTENCY_MIN,
                                       "min_active_months": MIN_ACTIVE_MONTHS,
                                       "min_hyro_attempts": MIN_HYRO_ATTEMPTS},
                  "effective_config": eff.to_dict(),
                  "note": "OOS travado (so DEV+VAL; loop nunca avalia OOS)."},
        loop=ld, hypothesis=hyp, decision=decision, reason=reason,
        notes=("H1 5m: params PRE-FIXADOS, sem grid; custos reais Bybit + "
               "funding no net; dual-profile; gate dos 8 criterios por "
               "segmento; VAL so apos DEV; OOS intocado; 1% separado; sem "
               "tuning corretivo.",
               "Candidata DEV+VAL => pede aprovacao antes do OOS; demo/live "
               "bloqueados; nada promovido.",))


__all__ = ["EdgeResearch59Report", "run_edge_research59", "_gate", "MIN_TRADES"]
