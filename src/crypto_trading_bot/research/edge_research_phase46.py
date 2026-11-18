"""
Edge Research FASE 46 — mercado-alvo Bybit Linear + direcao 1h por EMA-slope.
============================================================================
Hipotese UNICA: direcao 1h por slope de EMA (htf_direction) + setup
breakout 15m (mtf_setups H1) + SL/TP estrutural + entrada 15m (variante A,
principal). Gatilho 5m (variante B) = ABLACAO, rodada SO se A sobreviver ao
DEV. Sizing DERIVADO da RiskConfig (sem numero magico). Custos Bybit linear
configuraveis/documentados (+ overlay funding no stressed se material).
Segmentos/criterios/early-stops/verdict REUTILIZADOS (FASE 44/45). OOS so
apos DEV+VAL. Sem ordem/demo/live; RiskEngine/ModeGuard/piso intactos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase44 import (
    _early_stop,
    _metrics,
    _slice_by_date,
)
from crypto_trading_bot.research.edge_research_phase45 import (
    EdgeResearch45Report,
    _comparison,
    _incremental,
    _spec_for,
    _verdict_variant,
)

HYPOTHESES = ("H1_trend_vol_expansion",)   # hipotese unica (breakout+EMAslope)
_SIZING_MARGIN = 0.90      # folga DOCUMENTADA sob max_position_size_pct

# Custos Bybit LINEAR (BPS; documentados; configuraveis). Taker ~0,06%,
# slippage ~0,05%, spread ~0,02%. stressed = ~2x. Overlay de funding so se
# a auditoria mostrar materialidade (curto horizonte => 2a ordem).
BYBIT_COST_BPS = {"realistic": (6.0, 5.0, 2.0),
                  "stressed": (12.0, 10.0, 4.0)}


def _sizing_from_riskconfig(capital: float) -> Dict[str, Any]:
    """position_size_usd DERIVADO da RiskConfig (sem 9,5% magico). Para os
    stops estruturais de 15m (<= max_stop_loss_pct=5%) o cap de posicao
    prevalece sobre o termo de risco => size = MARGIN x max_position_size_pct
    x capital, sob o cap de exposicao. Documentado."""
    from crypto_trading_bot.config.risk_config import get_risk_config
    rc = get_risk_config()
    pos_cap = float(rc.max_position_size_pct) * capital
    size = round(_SIZING_MARGIN * pos_cap, 2)
    return {
        "position_size_usd": size,
        "derivation": {
            "max_position_size_pct": float(rc.max_position_size_pct),
            "max_exposure_per_asset_pct": float(rc.max_exposure_per_asset_pct),
            "max_risk_per_trade_pct": float(rc.max_risk_per_trade_pct),
            "margin": _SIZING_MARGIN,
            "note": "size = margin * max_position_size_pct * capital; cap de "
                    "posicao prevalece p/ stops estruturais <= max_stop_loss",
        },
    }


def _cost_cfg(kind: str):
    from crypto_trading_bot.research.calibration_costs import (
        build_cost_scenario,
    )
    if kind == "zero":
        return build_cost_scenario("zero_cost").config
    f, s, sp = BYBIT_COST_BPS["stressed" if kind == "stressed"
                              else "realistic"]
    label = "stressed_research" if kind == "stressed" else "realistic_research"
    return build_cost_scenario(label, fees_bps=f, slippage_bps=s,
                               spread_bps=sp).config


def _run_eval46(spec, candles, setups, *, cost_kind, capital, wf_folds,
                regime_ts_map, variant, seg_dates, min_candles):
    from crypto_trading_bot.research.strategy_research import evaluate_strategy
    res = evaluate_strategy(
        spec, list(candles), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=_cost_cfg(cost_kind),
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2 else None),
        precompute_features=True)
    rep = res.single_report
    m = _metrics(rep, candles, capital=capital, regime_ts_map=regime_ts_map)
    m["cost_scenario"] = cost_kind
    m["comparison"] = _comparison(rep, candles, setups, variant=variant,
                                  seg_dates=seg_dates)
    wf = getattr(res, "wf_summary", None)
    if wf:
        m["walk_forward"] = dict(wf)
    return m


def _run_variant(spec, candles, setups, *, variant, regime_map, capital,
                 wf_folds, seg, min_candles, run_oos) -> Dict[str, Any]:
    dev_c = _slice_by_date(candles, *seg["dev"])
    dev_m = _run_eval46(spec, dev_c, setups, cost_kind="realistic",
                        capital=capital, wf_folds=wf_folds,
                        regime_ts_map=regime_map, variant=variant,
                        seg_dates=seg["dev"], min_candles=min_candles)
    stop = _early_stop(dev_m)
    block = {"dev": dev_m, "early_stop": stop}
    if stop is None and run_oos:
        for seg_name, cost in (("val", "realistic"),):
            c = _slice_by_date(candles, *seg[seg_name])
            block[seg_name] = _run_eval46(
                spec, c, setups, cost_kind=cost, capital=capital,
                wf_folds=wf_folds, regime_ts_map=regime_map, variant=variant,
                seg_dates=seg[seg_name], min_candles=min_candles)
        oos_c = _slice_by_date(candles, *seg["oos"])
        block["oos"] = _run_eval46(spec, oos_c, setups, cost_kind="realistic",
                                   capital=capital, wf_folds=None,
                                   regime_ts_map=regime_map, variant=variant,
                                   seg_dates=seg["oos"], min_candles=min_candles)
        block["oos_stressed"] = _run_eval46(
            spec, oos_c, setups, cost_kind="stressed", capital=capital,
            wf_folds=None, regime_ts_map=regime_map, variant=variant,
            seg_dates=seg["oos"], min_candles=min_candles)
        block["oos_zero_diag"] = _run_eval46(
            spec, oos_c, setups, cost_kind="zero", capital=capital,
            wf_folds=None, regime_ts_map=regime_map, variant=variant,
            seg_dates=seg["oos"], min_candles=min_candles)
    v, crit, noncrit = _verdict_variant(block, variant)
    block["verdict"] = v
    block["critical_gates"] = crit
    block["noncritical_gates"] = noncrit
    return block


def run_edge_research46(
    candles_5m: Sequence, candles_15m: Sequence, candles_1h: Sequence, *,
    symbol: str = "BTCUSDT",
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-05-31"),
    capital: float = 5000.0, wf_folds: int = 5,
    ema_period: int = 50, slope_k: int = 6, slope_threshold: float = 0.001,
    hypotheses: Optional[Sequence[str]] = None, run_oos: bool = True,
    progress=None,
) -> EdgeResearch45Report:
    from datetime import datetime, timezone
    from crypto_trading_bot.research.htf_direction import (
        align_direction_to_exec,
        ema_slope_direction,
    )
    from crypto_trading_bot.research.mtf_setups import detect_setups

    def _cb(m):
        if progress:
            progress(m)

    hyps = list(hypotheses) if hypotheses else list(HYPOTHESES)
    _cb("direcao 1h por EMA-slope (causal) + alinhando 1h->15m e 1h->5m")
    dir_1h = ema_slope_direction(candles_1h, ema_period=ema_period,
                                 slope_k=slope_k, threshold=slope_threshold)
    rmap_15 = align_direction_to_exec(candles_15m, candles_1h, dir_1h,
                                      low_interval_minutes=15)
    rmap_5 = align_direction_to_exec(candles_5m, candles_1h, dir_1h,
                                     low_interval_minutes=5)
    sizing = _sizing_from_riskconfig(capital)
    size = sizing["position_size_usd"]
    seg = {"dev": dev, "val": val, "oos": oos}
    min_candles = 120
    order = {"PROMOVER_PARA_PAPER": 2, "REFINAR_COM_HIPOTESE_ESPECIFICA": 1,
             "REJEITAR": 0}

    hyp_reports: List[Dict[str, Any]] = []
    for hyp in hyps:
        _cb(f"{hyp}: detectando setups 15m")
        setups = detect_setups(candles_15m, hypothesis=hyp)
        # Variante A (15m) — PRINCIPAL.
        _cb(f"{hyp} A(15m) DEV->...")
        specA = _spec_for(hyp, "A", setups, rmap_15, size)
        a_block = _run_variant(specA, candles_15m, setups, variant="A",
                               regime_map=rmap_15, capital=capital,
                               wf_folds=wf_folds, seg=seg,
                               min_candles=min_candles, run_oos=run_oos)
        variants = {"A": a_block}
        # Variante B (5m) — ABLACAO, SO se A sobreviveu o DEV.
        if a_block.get("early_stop") is None:
            _cb(f"{hyp} B(5m) ablacao DEV->...")
            specB = _spec_for(hyp, "B", setups, rmap_5, size)
            variants["B"] = _run_variant(
                specB, candles_5m, setups, variant="B", regime_map=rmap_5,
                capital=capital, wf_folds=wf_folds, seg=seg,
                min_candles=min_candles, run_oos=run_oos)
        else:
            variants["B"] = {"skipped": "ablacao 5m nao executada: A nao "
                             "sobreviveu ao DEV", "early_stop": None,
                             "verdict": "N/A"}
        hyp_reports.append({
            "hypothesis": hyp, "verdict": a_block["verdict"],
            "primary_variant": "A",
            "incremental_B_vs_A": _incremental(variants)
            if "B" in variants and "dev" in variants["B"] else
            {"available": False, "reason": "ablacao 5m nao executada"},
            "variants": variants})

    overall = max((h["verdict"] for h in hyp_reports),
                  key=lambda x: order.get(x, 0), default="REJEITAR")
    return EdgeResearch45Report(
        schema="edge_research_phase46_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos, "sizing": sizing,
                  "ema_slope": {"ema_period": ema_period, "slope_k": slope_k,
                                "threshold": slope_threshold},
                  "market": "bybit_linear_perp",
                  "cost_bps": BYBIT_COST_BPS,
                  "note": "OOS travado; refinar exige janela futura."},
        hypotheses=tuple(hyp_reports), overall_verdict=overall,
        notes=("Mercado-alvo Bybit linear; 1h direcao=EMA-slope; 15m setup+"
               "SL/TP estrutural (entrada principal); 5m=ablacao se A passa "
               "DEV.",
               "Sizing derivado da RiskConfig (margem documentada).",
               "Demo/live bloqueados; PROMOVER=so elegibilidade paper.",))


__all__ = ["HYPOTHESES", "run_edge_research46"]
