"""
Edge Research FASE 51 — F5 Funding-Swing MR + avaliacao DUAL-PROFILE.
====================================================================
Monta a UNICA hipotese sobrevivente da FASE 50 (funding-swing mean-reversion,
4h, hold 3-7d) e a avalia nos DOIS perfis (HyroTrader Challenge + Trader
Padrao) via standard_report. Risco 0,5% PRIMARIO + analise 1% SEPARADA.
DEV(+VAL); OOS preservado. Funding REAL no net. Sem ordem/demo/live.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase44 import (
    _early_stop, _metrics, _slice_by_date)
from crypto_trading_bot.research.edge_research_phase47 import (
    BYBIT_COST_BPS, _cost_cfg, _funding_adjust)
from crypto_trading_bot.research.effective_config import (
    build_effective_config, dynamic_position_size)

# saida por tempo: ate ~7d em barras de 4h (horizonte sobrevivente FASE 50)
MAX_HOLD_4H = 42


def _run(setups, candles, *, seg_dates, risk_config, risk_base_pct,
         funding_events, cost_kind, wf_folds, min_candles, segment_label,
         eff):
    from crypto_trading_bot.research.funding_swing_family import F5_PARAMS  # noqa
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
        return PerpSetupStrategy(setups=setups, family_id="F5",
                                 size_by_id=size_by_id)
    spec = StrategySpec(name=f"f51_{cost_kind}_{int(risk_base_pct*1000)}",
                        factory=_factory, description="F5", default_config={})
    res = evaluate_strategy(
        spec, list(seg_c), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=_cost_cfg(cost_kind),
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2
                              else None),
        precompute_features=True, risk_config=risk_config,
        max_holding_candles=MAX_HOLD_4H)
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
    return rep, m


def _final_classification(dev_class, val_class, val_present,
                          early_stop) -> str:
    """Classificacao FINAL da familia (DEV+VAL). O `classification` por
    SEGMENTO continua sendo fato (dev_classification/val_classification);
    este reflete a combinacao. Nomenclatura consistente com v2."""
    if early_stop is not None:
        return "sem_edge_operacional"          # DEV nem completou
    if not val_present:
        return dev_class                       # sem VAL nao da p/ confirmar
    if dev_class == "candidata_paper":
        return ("candidata_paper" if val_class == "candidata_paper"
                else "dev_candidate_val_failed")
    if dev_class == "edge_possivel_incompativel_com_challenge":
        return ("edge_possivel_incompativel_com_challenge"
                if val_class in ("candidata_paper",
                                 "edge_possivel_incompativel_com_challenge")
                else "sem_edge_operacional")
    return "sem_edge_operacional"


def _decision(dev_verdict, dev_class, val_verdict, val_class,
              early_stop) -> str:
    """Decisao exige DEV **E** VAL (DEV sozinho NAO promove). PROMOVER = so
    elegivel a OOS/paper; OOS continua a trava final intocada aqui."""
    if early_stop is not None:
        return "REJEITAR"
    dev_edge = dev_verdict.get("edge_estatistico")
    if val_verdict is None:
        return "REFINAR" if dev_edge == "aprovado" else "REJEITAR"
    val_edge = val_verdict.get("edge_estatistico")
    val_robust = val_verdict.get("robustez_temporal")
    val_ok = (val_edge == "aprovado" and val_robust == "aprovado")
    if (dev_class == "candidata_paper" and val_class == "candidata_paper"
            and val_ok):
        return "PROMOVER"          # elegivel a OOS (trava final)
    if dev_edge == "aprovado" and not val_ok:
        return "REJEITAR"          # edge do DEV NAO robusto na VAL
    return "REFINAR"


@dataclass(frozen=True)
class EdgeResearch51Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    family: Mapping[str, Any]
    decision: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments), "family": dict(self.family),
                "decision": self.decision,
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def run_edge_research51(
    candles_1h: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-05-31"),
    operator_store=None, wf_folds: int = 5, run_val: bool = True,
    progress=None) -> EdgeResearch51Report:
    from crypto_trading_bot.research.funding_swing_family import (
        detect_f5_funding_swing)
    from crypto_trading_bot.research.perp_signals import build_perp_features
    from crypto_trading_bot.research.timeframe_resample import resample

    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store)
    rc05 = eff.risk_config
    rc1 = rc05.model_copy(update={"max_risk_per_trade_pct": 0.01})
    _cb("resample 1h -> 4h (causal)")
    c4h = resample(candles_1h, factor_minutes=240, base_minutes=60,
                   symbol=symbol)
    feats = build_perp_features(c4h, interval_minutes=240,
                                funding_points=list(funding_points),
                                oi_points=list(oi_points))
    funding_events = feats.funding_events
    setups = detect_f5_funding_swing(c4h, feats.funding_pctile)
    _cb(f"F5: {len(setups)} setups 4h")
    seg = {"dev": dev, "val": val, "oos": oos}
    mc = 60

    # 0,5% PRIMARIO (dual-profile completo)
    dev_rep, dev_m = _run(setups, c4h, seg_dates=dev, risk_config=rc05,
                          risk_base_pct=0.005, funding_events=funding_events,
                          cost_kind="realistic", wf_folds=wf_folds,
                          min_candles=mc, segment_label="DEV", eff=eff)
    stop = _early_stop(dev_m)
    block: Dict[str, Any] = {"n_setups": len(setups), "early_stop": stop,
                             "dev_05pct": dev_m}
    if stop is None and run_val:
        _, block["val_05pct"] = _run(
            setups, c4h, seg_dates=val, risk_config=rc05, risk_base_pct=0.005,
            funding_events=funding_events, cost_kind="realistic",
            wf_folds=wf_folds, min_candles=mc, segment_label="VAL", eff=eff)
    # 1% ANALISE SEPARADA (Trader Padrao); challenge segue 0,5%
    _, dev_1pct = _run(setups, c4h, seg_dates=dev, risk_config=rc1,
                       risk_base_pct=0.01, funding_events=funding_events,
                       cost_kind="realistic", wf_folds=None, min_candles=mc,
                       segment_label="DEV", eff=eff)
    sr05 = dev_m["standard_report"]
    block["standard_trader_1pct_analysis"] = \
        dev_1pct["standard_report"]["standard_trader_evaluation"]
    verdict = sr05["verdict"]
    classification = sr05["classification"]
    # VAL (confirmacao): DEV sozinho NAO promove. OOS intocado.
    val_verdict = val_class = None
    if "val_05pct" in block:
        val_sr = block["val_05pct"]["standard_report"]
        val_verdict = val_sr["verdict"]
        val_class = val_sr["classification"]
        block["val_verdict"] = val_verdict
        block["val_classification"] = val_class
    decision = _decision(verdict, classification, val_verdict, val_class, stop)
    final_class = _final_classification(
        classification, val_class, val_class is not None, stop)
    block["dev_verdict"] = verdict
    block["dev_classification"] = classification    # fato do DEV
    block["val_classification"] = val_class         # fato da VAL (ou None)
    block["final_classification"] = final_class     # DEV+VAL (familia)
    block["verdict"] = verdict                       # compat: DEV
    block["decision"] = decision
    block["oos_consulted"] = False

    return EdgeResearch51Report(
        schema="edge_research_phase51_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos,
                  "market": "bybit_linear_perp_4h", "max_hold_4h": MAX_HOLD_4H,
                  "effective_config": eff.to_dict(),
                  "cost_bps": BYBIT_COST_BPS,
                  "note": "OOS travado (so DEV+VAL aqui)."},
        family={"family": "F5_funding_swing_mr", **block},
        decision=decision,
        notes=("F5 funding-swing MR (sobrevivente FASE 50, sem sobreposicao). "
               "Avaliacao DUAL-PROFILE: hyro_challenge + standard_trader; "
               "classification cruza os dois. Risco 0,5% primario + 1% "
               "analise separada (NAO muda challenge).",
               "net inclui funding; OOS preservado; demo/live bloqueados; "
               "Trader Padrao NAO libera execucao.",))


__all__ = ["EdgeResearch51Report", "run_edge_research51", "MAX_HOLD_4H"]
