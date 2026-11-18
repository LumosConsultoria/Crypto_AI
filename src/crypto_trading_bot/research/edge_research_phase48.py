"""
Edge Research FASE 48 — Cost-Aware Strategy Research (Bybit linear).
=====================================================================
Famílias de BAIXO turnover / horizonte 4h / stops largos / alvos grandes
(F3 HTF trend continuation; F4 vol-expansion continuation multi-TF), pensadas
a partir do DIAGNOSTICO DE CUSTO (cost_viability): cost_in_R = 26bps/stop_dist.

Reusa: effective_config (RiskConfig Hyro 5k SOBERANO), standard_report (3
secoes + verdict 4 eixos + tabela mensal + net incl. funding), hyrotrader_eval
(via standard_report), segmentos/early-stop (FASE 44). OOS preservado (so
DEV+VAL aqui). Funding REAL no PnL realistic. Sem ordem/demo/live; RiskEngine/
ModeGuard/piso 0.005 intactos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase44 import (
    _early_stop,
    _metrics,
    _slice_by_date,
)
from crypto_trading_bot.research.edge_research_phase47 import (
    BYBIT_COST_BPS,
    _cost_cfg,
    _funding_adjust,
)
from crypto_trading_bot.research.effective_config import (
    build_effective_config,
    dynamic_position_size,
)

FAMILIES = ("F3_htf_trend_continuation", "F4_vol_expansion_mtf")


def _decision_from_verdict(v: Mapping[str, str]) -> str:
    """PROMOVER | REFINAR | REJEITAR a partir do verdict de 4 eixos.
    PROMOVER exige edge + robustez (paper); REFINAR se edge ok mas robustez
    nao; senao REJEITAR."""
    edge = v.get("edge_estatistico")
    robust = v.get("robustez_temporal")
    if edge == "aprovado" and robust == "aprovado":
        return "PROMOVER"
    if edge == "aprovado":
        return "REFINAR"
    return "REJEITAR"


def _sizing(capital, stop_dist_pct, eff):
    ext = eff.external_ceilings
    return dynamic_position_size(
        capital=capital, stop_dist_pct=stop_dist_pct,
        risk_base_pct=float(eff.risk_config.max_risk_per_trade_pct),
        external_risk_ceiling_pct=ext["max_risk_per_trade_pct"],
        hyro_max_notional_usd=eff.sizing_policy["caps"].get(
            "hyro_max_notional_usd"))["position_size_usd"]


def _run_segment(setups, candles, *, family, seg_dates, cost_kind, eff,
                 funding_events, wf_folds, min_candles, segment_label,
                 max_holding_candles=42):
    from crypto_trading_bot.research.perp_families import PerpSetupStrategy
    from crypto_trading_bot.research.standard_report import (
        build_standard_report)
    from crypto_trading_bot.research.strategy_research import (
        StrategySpec, evaluate_strategy)
    capital = float(eff.risk_config.account_size_usd)
    size_by_id = {s.setup_id: _sizing(capital, s.stop_dist_pct, eff)
                  for s in setups}
    seg_c = _slice_by_date(candles, *seg_dates)

    def _factory(_cfg):
        return PerpSetupStrategy(setups=setups, family_id=family,
                                 size_by_id=size_by_id)
    spec = StrategySpec(name=f"f48_{family}_{cost_kind}", factory=_factory,
                        description=family, default_config={})
    res = evaluate_strategy(
        spec, list(seg_c), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=_cost_cfg(cost_kind),
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2
                              else None),
        precompute_features=True, risk_config=eff.risk_config,
        max_holding_candles=max_holding_candles)
    rep = res.single_report
    m = _metrics(rep, seg_c, capital=capital, regime_ts_map={})
    fa = _funding_adjust(rep, funding_events)
    m["funding"] = {k: v for k, v in fa.items() if k != "adj_pnls"}
    if fa["profit_factor_net_funded"] is not None:
        m["profit_factor_net"] = fa["profit_factor_net_funded"]
    m["expectancy_net_usd"] = fa["expectancy_net_usd_funded"]
    m["total_pnl_usd"] = fa["total_pnl_usd_funded"]
    m["cost_scenario"] = cost_kind
    wf = getattr(res, "wf_summary", None)
    if wf:
        m["walk_forward"] = dict(wf)
    m["standard_report"] = build_standard_report(
        rep, capital=capital, funding_events=funding_events,
        segment_label=segment_label,
        hyro_internal_controls=eff.internal_controls,
        hyro_daily_drawdown_pct=eff.external_ceilings["daily_drawdown_pct"],
        hyro_total_loss_pct=eff.external_ceilings["total_loss_pct"],
        expectancy_ci=m.get("expectancy_ci"), prospective_pending=True)
    return rep, m


@dataclass(frozen=True)
class EdgeResearch48Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    cost_diagnosis: Mapping[str, Any]
    families: Tuple[Mapping[str, Any], ...]
    overall_decision: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments),
                "cost_diagnosis": dict(self.cost_diagnosis),
                "families": [dict(f) for f in self.families],
                "overall_decision": self.overall_decision,
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def run_edge_research48(
    candles_1h: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-05-31"),
    operator_store=None, wf_folds: int = 5, run_val: bool = True,
    progress=None) -> EdgeResearch48Report:
    """Orquestra DEV(+VAL) p/ F3/F4 no 4h (resample do 1h). OOS preservado."""
    from crypto_trading_bot.research.cost_aware_families import (
        detect_f3_htf_trend_continuation, detect_f4_vol_expansion_continuation)
    from crypto_trading_bot.research.cost_viability import build_cost_diagnosis
    from crypto_trading_bot.research.htf_direction import (
        align_direction_to_exec, ema_slope_direction)
    from crypto_trading_bot.research.perp_signals import build_perp_features
    from crypto_trading_bot.research.timeframe_resample import resample

    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store)
    capital = float(eff.risk_config.account_size_usd)
    f, s, sp = BYBIT_COST_BPS["realistic"]
    cost_diag = build_cost_diagnosis(
        taker_fee_pct=f / 10000.0, slippage_pct=s / 10000.0,
        spread_pct=sp / 10000.0,
        risk_base_usd=float(eff.risk_config.max_risk_per_trade_pct) * capital,
        daily_loss_limit_usd=eff.external_ceilings["daily_drawdown_pct"]
        * capital)

    _cb("resample 1h -> 4h e 1d (causal)")
    c4h = resample(candles_1h, factor_minutes=240, base_minutes=60,
                   symbol=symbol)
    c1d = resample(candles_1h, factor_minutes=1440, base_minutes=60,
                   symbol=symbol)
    # direcao diaria (EMA-slope) alinhada causal aos candles 4h (multi-TF F4)
    daily_dir = ema_slope_direction(c1d, ema_period=50, slope_k=6,
                                    threshold=0.001)
    daily_map = align_direction_to_exec(c4h, c1d, daily_dir,
                                        low_interval_minutes=240,
                                        high_interval_minutes=1440)
    # funding/OI alinhados ao 4h (funding p/ PnL realistic; OI disponivel)
    feats = build_perp_features(c4h, interval_minutes=240,
                                funding_points=list(funding_points),
                                oi_points=list(oi_points))
    funding_events = feats.funding_events
    min_candles = 60

    setups_by_fam = {
        "F3_htf_trend_continuation": detect_f3_htf_trend_continuation(c4h),
        "F4_vol_expansion_mtf": detect_f4_vol_expansion_continuation(
            c4h, daily_direction_map=daily_map),
    }

    fam_reports: List[Dict[str, Any]] = []
    order = {"PROMOVER": 2, "REFINAR": 1, "REJEITAR": 0}
    for family, setups in setups_by_fam.items():
        _cb(f"{family}: {len(setups)} setups 4h")
        dev_rep, dev_m = _run_segment(
            setups, c4h, family=family, seg_dates=dev, cost_kind="realistic",
            eff=eff, funding_events=funding_events, wf_folds=wf_folds,
            min_candles=min_candles, segment_label="DEV")
        stop = _early_stop(dev_m)
        block = {"dev": dev_m, "early_stop": stop, "n_setups": len(setups)}
        if stop is None and run_val:
            _, block["val"] = _run_segment(
                setups, c4h, family=family, seg_dates=val,
                cost_kind="realistic", eff=eff, funding_events=funding_events,
                wf_folds=wf_folds, min_candles=min_candles,
                segment_label="VAL")
        # verdict de 4 eixos vem do standard_report do DEV (sempre presente)
        verdict = dev_m["standard_report"]["verdict"]
        decision = _decision_from_verdict(verdict)
        block["verdict"] = verdict
        block["decision"] = decision
        fam_reports.append({"family": family, "decision": decision,
                            "verdict": verdict, "early_stop": stop,
                            "n_setups": len(setups), "block": block})

    overall = max((fr["decision"] for fr in fam_reports),
                  key=lambda x: order.get(x, 0), default="REJEITAR")
    return EdgeResearch48Report(
        schema="edge_research_phase48_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos,
                  "market": "bybit_linear_perp_4h", "timeframe": "4h",
                  "effective_config": eff.to_dict(),
                  "cost_bps": BYBIT_COST_BPS,
                  "note": "OOS travado (so DEV+VAL aqui); refinar exige janela "
                          "futura."},
        cost_diagnosis=cost_diag, families=tuple(fam_reports),
        overall_decision=overall,
        notes=("Familias cost-aware (4h, baixo turnover, stops largos, R "
               "grande). net inclui fees+spread+slippage+funding.",
               "standard_report em todos; verdict 4 eixos; desafio Hyro = "
               "sobreviveu + atingiu meta. OOS preservado.",
               "Demo/live bloqueados; PROMOVER=so elegibilidade paper.",))


__all__ = ["FAMILIES", "EdgeResearch48Report", "run_edge_research48"]
