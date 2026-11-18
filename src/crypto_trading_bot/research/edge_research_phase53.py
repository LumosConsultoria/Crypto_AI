"""
Edge Research FASE 53 (re-escopo) — roda a AGENDA de hipoteses NORMAIS pelo
research loop controlado, com avaliador REAL via standard_report dual-profile
(Hyro Challenge 5k + Trader Padrao 5k). Risco 0,5% primario + 1% analise
separada. DEV; VAL so se DEV passar; **OOS NUNCA avaliado** (o loop nao recebe
OOS). Sem ordem/demo/live. Reusa o motor/standard_report/effective_config
existentes (NAO altera core).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase44 import (
    _metrics, _slice_by_date)
from crypto_trading_bot.research.edge_research_phase47 import (
    BYBIT_COST_BPS, _cost_cfg, _funding_adjust)
from crypto_trading_bot.research.effective_config import (
    build_effective_config, dynamic_position_size)


def _run53(setups, candles, *, seg_dates, risk_config, risk_base_pct,
           funding_events, wf_folds, min_candles, segment_label, eff,
           family_id, max_holding):
    from crypto_trading_bot.research.perp_families import PerpSetupStrategy
    from crypto_trading_bot.research.standard_report import (
        build_standard_report)
    from crypto_trading_bot.research.strategy_research import (
        StrategySpec, evaluate_strategy)
    capital = float(risk_config.account_size_usd)
    ext = eff.external_ceilings
    size_by_id = {
        s.setup_id: dynamic_position_size(
            capital=capital, stop_dist_pct=s.stop_dist_pct,
            risk_base_pct=risk_base_pct,
            external_risk_ceiling_pct=ext["max_risk_per_trade_pct"],
            hyro_max_notional_usd=eff.sizing_policy["caps"].get(
                "hyro_max_notional_usd"))["position_size_usd"]
        for s in setups}
    seg_c = _slice_by_date(candles, *seg_dates)

    def _factory(_c):
        return PerpSetupStrategy(setups=setups, family_id=family_id,
                                 size_by_id=size_by_id)
    spec = StrategySpec(name=f"p53_{family_id}_{int(risk_base_pct*1000)}",
                        factory=_factory, description=family_id,
                        default_config={})
    res = evaluate_strategy(
        spec, list(seg_c), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=_cost_cfg("realistic"),
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2 else None),
        precompute_features=True, risk_config=risk_config,
        max_holding_candles=max_holding)
    rep = res.single_report
    m = _metrics(rep, seg_c, capital=capital, regime_ts_map={})
    fa = _funding_adjust(rep, funding_events)
    m["funding"] = {k: v for k, v in fa.items() if k != "adj_pnls"}
    if fa["profit_factor_net_funded"] is not None:
        m["profit_factor_net"] = fa["profit_factor_net_funded"]
    m["expectancy_net_usd"] = fa["expectancy_net_usd_funded"]
    m["total_pnl_usd"] = fa["total_pnl_usd_funded"]
    m["standard_report"] = build_standard_report(
        rep, capital=capital, funding_events=funding_events,
        segment_label=segment_label,
        hyro_internal_controls=eff.internal_controls,
        hyro_daily_drawdown_pct=ext["daily_drawdown_pct"],
        hyro_total_loss_pct=ext["total_loss_pct"],
        expectancy_ci=m.get("expectancy_ci"), prospective_pending=True,
        risk_base_pct=risk_base_pct)
    return m


@dataclass(frozen=True)
class EdgeResearch53Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    loop: Mapping[str, Any]
    per_hypothesis: Mapping[str, Any]
    decision: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments), "loop": dict(self.loop),
                "per_hypothesis": dict(self.per_hypothesis),
                "decision": self.decision, "real_execution_allowed": False,
                "demo_blocked": True, "live_blocked": True,
                "strategy_promoted": False, "notes": list(self.notes)}


def run_edge_research53(
    candles_1h: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    operator_store=None, wf_folds: int = 5, progress=None
) -> EdgeResearch53Report:
    from crypto_trading_bot.research.normal_families import (
        DETECTORS, HOLD_BARS)
    from crypto_trading_bot.research.normal_hypotheses import (
        proposed_hypotheses)
    from crypto_trading_bot.research.perp_signals import build_perp_features
    from crypto_trading_bot.research.research_loop import run_research_loop

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
    mc = 60

    # setups por hipotese (UMA vez, sobre todo o DEV+VAL; causal)
    setups_by: Dict[str, list] = {}
    for h in proposed_hypotheses():
        det = DETECTORS[h.name]
        if h.name == "oi_divergence_exhaustion":
            setups_by[h.name] = det(candles_1h, pf.oi_change,
                                    params=dict(h.fixed_params))
        else:
            setups_by[h.name] = det(candles_1h, params=dict(h.fixed_params))
        _cb(f"{h.name}: {len(setups_by[h.name])} setups")

    reports: Dict[str, Dict[str, Any]] = {}

    def evaluator(spec, segment):
        seg_dates = dev if segment == "DEV" else val
        m = _run53(setups_by[spec.name], candles_1h, seg_dates=seg_dates,
                   risk_config=rc05, risk_base_pct=0.005,
                   funding_events=funding_events, wf_folds=wf_folds,
                   min_candles=mc, segment_label=segment, eff=eff,
                   family_id=spec.name, max_holding=HOLD_BARS[spec.name])
        reports.setdefault(spec.name, {})[segment] = m
        return m["standard_report"]

    _cb("rodando research loop (DEV; VAL so se DEV passar; OOS intocado)")
    loop = run_research_loop(proposed_hypotheses(), evaluator,
                             progress=progress)

    # 1% analise SEPARADA (Trader Padrao) p/ hipoteses testadas no DEV
    per_hyp: Dict[str, Any] = {}
    for name, segs in reports.items():
        dev_sr = segs.get("DEV", {}).get("standard_report", {})
        block = {
            "n_setups": len(setups_by.get(name, [])),
            "dev_classification": dev_sr.get("classification"),
            "dev_verdict": dev_sr.get("verdict"),
            "dev_strategy_metrics": dev_sr.get("strategy_metrics"),
            "dev_monthly": dev_sr.get("temporal_breakdown"),
        }
        if "VAL" in segs:
            val_sr = segs["VAL"].get("standard_report", {})
            block["val_classification"] = val_sr.get("classification")
            block["val_verdict"] = val_sr.get("verdict")
            block["val_strategy_metrics"] = val_sr.get("strategy_metrics")
        m1 = _run53(setups_by[name], candles_1h, seg_dates=dev,
                    risk_config=rc1, risk_base_pct=0.01,
                    funding_events=funding_events, wf_folds=None,
                    min_candles=mc, segment_label="DEV", eff=eff,
                    family_id=name, max_holding=HOLD_BARS[name])
        block["trader_padrao_1pct_dev"] = \
            m1["standard_report"].get("standard_trader_evaluation")
        per_hyp[name] = block

    ld = loop.to_dict()
    decision = ("CANDIDATA_PENDENTE_APROVACAO_OOS" if ld["candidate"]
                else "NENHUMA_CANDIDATA_DEV_VAL")

    return EdgeResearch53Report(
        schema="edge_research_phase53_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "market": "bybit_linear_perp_1h",
                  "cost_bps": BYBIT_COST_BPS,
                  "effective_config": eff.to_dict(),
                  "note": "OOS travado (so DEV+VAL; loop nunca avalia OOS)."},
        loop=ld, per_hypothesis=per_hyp, decision=decision,
        notes=("Agenda NORMAL via research loop; dual-profile (Hyro 5k + Trader "
               "Padrao 5k) por standard_report; 0,5% primario + 1% analise "
               "separada. VAL so apos DEV; OOS intocado; nada promovido.",
               "Candidata DEV+VAL => pede aprovacao antes do OOS; demo/live "
               "bloqueados.",))


__all__ = ["EdgeResearch53Report", "run_edge_research53", "_run53"]
