"""
Edge Research FASE 45 — orquestrador multi-timeframe.
=====================================================
1h regime/direcao (classify_regimes, so no 1h, 1x) + setups 15m
(mtf_setups, SL/TP estrutural) + execucao variante A (15m) / B (5m gatilho).
Segmentos DEV/VAL/OOS e criterios/metricas/verdict REUTILIZADOS da FASE 44.
Adiciona metricas de comparacao 15m-vs-5m. OOS so apos DEV+VAL; passe unico.
NAO altera RiskEngine/ModeGuard/piso; sem ordem; demo/live bloqueados.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase44 import (
    CRIT,
    _bootstrap_expectancy_ci,
    _critical_gates,
    _decide,
    _early_stop,
    _metrics,
    _noncritical_gates,
    _slice_by_date,
)

# Hipoteses FASE 45 (familias MTF novas; NAO as rejeitadas da FASE 44).
HYPOTHESES = ("H1_trend_vol_expansion", "H2_pullback_continuation")
_WINDOW_5M = 6           # janela do gatilho 5m (candles) p/ variante B
# Sizing DENTRO dos caps do RiskEngine: max_position_size_pct=10% e
# max_exposure_per_asset_pct=20% do capital. 9,5% fica sob ambos (sem
# `exposure_limit`/`position_size`). A e B usam o MESMO sizing.
_POSITION_FRACTION = 0.095


# ----------------------- metricas de comparacao ---------------------------

def _close_reason(t) -> str:
    cr = getattr(t, "close_reason", None)
    return getattr(cr, "value", None) or (str(cr) if cr else "")


def _mae_mfe(rep, candles) -> Dict[str, Optional[float]]:
    """MAE/MFE medios (% do entry) dos candles entre entrada e saida."""
    maes, mfes = [], []
    n = len(candles)
    for t in (rep.trades or []):
        e, x = t.entry_candle_idx, t.exit_candle_idx
        if e is None or x is None or e < 0 or x >= n or x < e:
            continue
        entry = t.entry_price
        if not entry or entry <= 0:
            continue
        seg = candles[e:x + 1]
        hi = max(float(c.high) for c in seg)
        lo = min(float(c.low) for c in seg)
        if t.side == "buy":
            maes.append((entry - lo) / entry)
            mfes.append((hi - entry) / entry)
        else:
            maes.append((hi - entry) / entry)
            mfes.append((entry - lo) / entry)
    return {"mae_mean_pct": round(sum(maes) / len(maes) * 100, 4) if maes
            else None,
            "mfe_mean_pct": round(sum(mfes) / len(mfes) * 100, 4) if mfes
            else None}


def _setups_in_segment(setups, seg_dates, variant) -> List[Any]:
    from datetime import datetime, timezone

    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    s, e = _p(seg_dates[0]), _p(seg_dates[1])
    key = (lambda x: x.open_ts) if variant == "A" else (lambda x: x.close_ts)
    out = []
    for st in setups:
        ts = key(st)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if s <= ts < e:
            out.append(st)
    return out


def _comparison(rep, candles, setups, *, variant, seg_dates) -> Dict[str, Any]:
    seg_setups = _setups_in_segment(setups, seg_dates, variant)
    n_setups = len(seg_setups)
    below = sum(1 for st in seg_setups if st.below_floor)
    trades = rep.trades or []
    n_tr = len(trades)
    stops = sum(1 for t in trades if _close_reason(t) == "stop_loss")
    tps = sum(1 for t in trades if _close_reason(t) == "take_profit")
    mm = _mae_mfe(rep, candles)
    return {
        "setups_detected": n_setups,
        "entries_executed": n_tr,
        "setups_not_entered": max(0, n_setups - n_tr),
        "pct_stops_below_floor": round(below / n_setups, 4) if n_setups
        else None,
        "stop_rate": round(stops / n_tr, 4) if n_tr else None,
        "take_profit_rate": round(tps / n_tr, 4) if n_tr else None,
        "avg_entry_price": round(sum(t.entry_price for t in trades) / n_tr, 2)
        if n_tr else None,
        **mm,
    }


# ----------------------------- specs/execucao -----------------------------

def _spec_for(hyp_id, variant, setups, regime_map, size):
    from crypto_trading_bot.research.mtf_strategy import (
        MtfSetupStrategyA,
        MtfSetupStrategyB,
    )
    from crypto_trading_bot.research.strategy_research import StrategySpec

    if variant == "A":
        def _factory(_cfg):
            return MtfSetupStrategyA(
                setups=setups, regime_map=regime_map, hypothesis_id=hyp_id,
                position_size_usd=size)
        name = f"mtf_{hyp_id}_A15m"
    else:
        def _factory(_cfg):
            return MtfSetupStrategyB(
                setups=setups, regime_map=regime_map, hypothesis_id=hyp_id,
                position_size_usd=size, window_candles=_WINDOW_5M)
        name = f"mtf_{hyp_id}_B5m"
    return StrategySpec(name=name, factory=_factory, description=name,
                        default_config={})


def _run_eval(spec, candles, setups, *, cost_label, capital, wf_folds,
              regime_ts_map, variant, seg_dates, min_candles):
    from crypto_trading_bot.research.calibration_costs import (
        build_cost_scenario,
    )
    from crypto_trading_bot.research.strategy_research import evaluate_strategy
    cost = build_cost_scenario(cost_label).config
    res = evaluate_strategy(
        spec, list(candles), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=cost,
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2 else None),
        precompute_features=True)
    rep = res.single_report
    m = _metrics(rep, candles, capital=capital, regime_ts_map=regime_ts_map)
    m["cost_scenario"] = cost_label
    m["comparison"] = _comparison(rep, candles, setups, variant=variant,
                                  seg_dates=seg_dates)
    wf = getattr(res, "wf_summary", None)
    if wf:
        m["walk_forward"] = dict(wf)
    return m


# ----------------------------- verdict ------------------------------------

def _pf_min(variant: str) -> float:
    return CRIT["pf_net_min_15m"] if variant == "A" else CRIT["pf_net_min_5m"]


def _sample_ok45(oos, valoos, variant) -> bool:
    if variant == "A":   # 15m
        return ((oos.get("total_trades") or 0) >= CRIT["min_trades_oos_15m"]
                and valoos >= CRIT["min_trades_valoos_15m"])
    return ((oos.get("total_trades") or 0) >= CRIT["min_trades_oos_5m"]
            and valoos >= CRIT["min_trades_valoos_5m"])


def _verdict_variant(block, variant) -> Tuple[str, Dict[str, bool], Dict[str, bool]]:
    if block.get("early_stop") is not None or "oos" not in block:
        return "REJEITAR", {}, {}
    oos = block["oos"]; stressed = block.get("oos_stressed"); val = block.get("val") or {}
    sens = block.get("sensitivity") or {}
    valoos = (val.get("total_trades") or 0) + (oos.get("total_trades") or 0)
    crit = _critical_gates(oos, stressed)
    # ajusta PF critico por variante (A=15m exige 1.20)
    pf = oos.get("profit_factor_net")
    crit["pf_net_ok"] = pf is not None and pf >= _pf_min(variant)
    noncrit = _noncritical_gates(oos, val, sens)
    v = _decide(crit, noncrit, _sample_ok45(oos, valoos, variant))
    return v, crit, noncrit


@dataclass(frozen=True)
class EdgeResearch45Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    hypotheses: Tuple[Mapping[str, Any], ...]
    overall_verdict: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments),
                "hypotheses": [dict(h) for h in self.hypotheses],
                "overall_verdict": self.overall_verdict,
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def _sensitivity45(hyp, variant, regime_map, candles_15m, dev_candles, *,
                   capital, regime_ts_map, seg_dates, min_candles,
                   size) -> Dict[str, Any]:
    """Sensibilidade: re-detecta setups com risk_reward +-1 passo (vizinhanca)
    e mede PF no DEV. Vizinhanca pequena, sem grid."""
    from crypto_trading_bot.research.mtf_setups import detect_setups
    pfs = []
    variants_out = []
    for rr in (1.2, 1.8):
        setups = detect_setups(candles_15m, hypothesis=hyp,
                               params={"risk_reward": rr})
        spec = _spec_for(hyp, variant, setups, regime_map, size)
        try:
            m = _run_eval(spec, dev_candles, setups,
                          cost_label="realistic_research", capital=capital,
                          wf_folds=None, regime_ts_map=regime_ts_map,
                          variant=variant, seg_dates=seg_dates,
                          min_candles=min_candles)
            pf = m.get("profit_factor_net")
            variants_out.append({"risk_reward": rr, "profit_factor_net": pf})
            if pf is not None:
                pfs.append(pf)
        except Exception:  # noqa: BLE001
            continue
    stable = bool(pfs) and all(p >= CRIT["param_stability_pf_min"] for p in pfs)
    return {"param": "risk_reward", "stable": stable, "variants": variants_out}


def run_edge_research45(
    candles_5m: Sequence, candles_15m: Sequence, candles_1h: Sequence, *,
    symbol: str = "BTCUSDT",
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-05-31"),
    capital: float = 5000.0, wf_folds: int = 5, regime_lookback: int = 96,
    hypotheses: Optional[Sequence[str]] = None, run_oos: bool = True,
    progress=None,
) -> EdgeResearch45Report:
    from datetime import datetime, timezone
    from crypto_trading_bot.research.htf_regime_filter import (
        align_from_classification,
    )
    from crypto_trading_bot.research.market_regime import classify_regimes
    from crypto_trading_bot.research.mtf_setups import detect_setups

    def _cb(m):
        if progress:
            progress(m)

    hyps = list(hypotheses) if hypotheses else list(HYPOTHESES)
    _cb("classificando regime 1h (uma vez) + alinhando 1h->15m e 1h->5m")
    rc1h = classify_regimes(candles_1h, lookback=regime_lookback)
    regime_map_15m = align_from_classification(
        candles_15m, candles_1h, rc1h, low_interval_minutes=15,
        high_interval_minutes=60)
    regime_map_5m = align_from_classification(
        candles_5m, candles_1h, rc1h, low_interval_minutes=5,
        high_interval_minutes=60)
    tf_series = {"A": candles_15m, "B": candles_5m}
    tf_regmap = {"A": regime_map_15m, "B": regime_map_5m}
    min_candles = 120
    size = round(_POSITION_FRACTION * capital, 2)   # dentro dos caps
    seg = {"dev": dev, "val": val, "oos": oos}

    hyp_reports: List[Dict[str, Any]] = []
    order = {"PROMOVER_PARA_PAPER": 2, "REFINAR_COM_HIPOTESE_ESPECIFICA": 1,
             "REJEITAR": 0}
    for hyp in hyps:
        _cb(f"{hyp}: detectando setups 15m")
        setups = detect_setups(candles_15m, hypothesis=hyp)
        variant_blocks: Dict[str, Any] = {}
        for variant in ("A", "B"):
            candles = tf_series[variant]
            rmap = tf_regmap[variant]
            spec = _spec_for(hyp, variant, setups, rmap, size)
            dev_c = _slice_by_date(candles, *seg["dev"])
            _cb(f"{hyp} {variant} DEV")
            dev_m = _run_eval(spec, dev_c, setups,
                              cost_label="realistic_research", capital=capital,
                              wf_folds=wf_folds, regime_ts_map=rmap,
                              variant=variant, seg_dates=seg["dev"],
                              min_candles=min_candles)
            stop = _early_stop(dev_m)
            block = {"dev": dev_m, "early_stop": stop}
            if stop is None and run_oos:
                val_c = _slice_by_date(candles, *seg["val"])
                oos_c = _slice_by_date(candles, *seg["oos"])
                _cb(f"{hyp} {variant} VAL")
                block["val"] = _run_eval(
                    spec, val_c, setups, cost_label="realistic_research",
                    capital=capital, wf_folds=wf_folds, regime_ts_map=rmap,
                    variant=variant, seg_dates=seg["val"],
                    min_candles=min_candles)
                _cb(f"{hyp} {variant} OOS (realista+stressed+zero)")
                block["oos"] = _run_eval(
                    spec, oos_c, setups, cost_label="realistic_research",
                    capital=capital, wf_folds=None, regime_ts_map=rmap,
                    variant=variant, seg_dates=seg["oos"],
                    min_candles=min_candles)
                block["oos_stressed"] = _run_eval(
                    spec, oos_c, setups, cost_label="stressed_research",
                    capital=capital, wf_folds=None, regime_ts_map=rmap,
                    variant=variant, seg_dates=seg["oos"],
                    min_candles=min_candles)
                block["oos_zero_diag"] = _run_eval(
                    spec, oos_c, setups, cost_label="zero_cost",
                    capital=capital, wf_folds=None, regime_ts_map=rmap,
                    variant=variant, seg_dates=seg["oos"],
                    min_candles=min_candles)
                block["sensitivity"] = _sensitivity45(
                    hyp, variant, rmap, candles_15m, dev_c, capital=capital,
                    regime_ts_map=rmap, seg_dates=seg["dev"],
                    min_candles=min_candles, size=size)
            v, crit, noncrit = _verdict_variant(block, variant)
            block["verdict"] = v
            block["critical_gates"] = crit
            block["noncritical_gates"] = noncrit
            variant_blocks[variant] = block
        # verdict da hipotese = melhor entre A e B
        best = max(variant_blocks.items(),
                   key=lambda kv: order[kv[1]["verdict"]])
        # comparacao incremental B vs A (se ambos chegaram ao OOS)
        incr = _incremental(variant_blocks)
        hyp_reports.append({
            "hypothesis": hyp, "verdict": best[1]["verdict"],
            "chosen_variant": best[0], "incremental_B_vs_A": incr,
            "variants": variant_blocks})

    overall = max((h["verdict"] for h in hyp_reports),
                  key=lambda x: order[x], default="REJEITAR")
    return EdgeResearch45Report(
        schema="edge_research_phase45_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos,
                  "note": "OOS travado; refinar exige janela futura "
                          "(future_holdout reservado)"},
        hypotheses=tuple(hyp_reports), overall_verdict=overall,
        notes=("1h=regime/direcao; 15m=setup+SL/TP estrutural; 5m=gatilho.",
               "Demo/live bloqueados; PROMOVER=so elegibilidade paper.",
               "Custo realista principal; zero=diag; stressed=robustez.",))


def _incremental(variant_blocks) -> Dict[str, Any]:
    a = variant_blocks.get("A", {})
    b = variant_blocks.get("B", {})
    a_oos = a.get("oos"); b_oos = b.get("oos")
    if not a_oos or not b_oos:
        return {"available": False,
                "reason": "uma das variantes nao chegou ao OOS"}
    return {
        "available": True,
        "expectancy_incremental": round(
            (b_oos.get("expectancy_net_usd") or 0)
            - (a_oos.get("expectancy_net_usd") or 0), 4),
        "drawdown_incremental_pct": round(
            abs(b_oos.get("max_drawdown_pct") or 0)
            - abs(a_oos.get("max_drawdown_pct") or 0), 4),
        "pf_A": a_oos.get("profit_factor_net"),
        "pf_B": b_oos.get("profit_factor_net"),
    }


__all__ = ["HYPOTHESES", "EdgeResearch45Report", "run_edge_research45"]
