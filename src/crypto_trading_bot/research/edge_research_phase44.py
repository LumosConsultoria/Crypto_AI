"""
Edge Research (FASE 44) — orquestrador de pesquisa de edge.
===========================================================
Avalia hipoteses (H1 tendencia c/ expansao de volatilidade; H2 reversao a
media em range) no 5m (primario) e 15m (controle), com VARIANTE HTF (gate
de regime 15m) SOMENTE no 5m, em segmentos cronologicos DEV/VAL/OOS, custo
realista (principal) + zero (diagnostico) + stressed (robustez), com
walk-forward, estabilidade mensal, por regime, concentracao (sobre gross
profit), IC bootstrap da expectancy, sensibilidade de parametros e baseline
ajustado a risco. Verdict TRAVADO (PROMOVER_PARA_PAPER | REFINAR_COM_
HIPOTESE_ESPECIFICA | REJEITAR). NAO altera RiskEngine/ModeGuard/piso; NAO
envia ordem; demo/live seguem bloqueados. Reusa as primitivas existentes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# Hipoteses -> familia research existente.
HYPOTHESES: Dict[str, Dict[str, Any]] = {
    "H1_trend_vol_expansion": {
        "family": "volatility_contraction_expansion_research",
        "htf_allowed": ("trend_up", "trend_down", "breakout"),
        "sensitivity_param": None,   # resolvido do default_config
    },
    "H2_range_mean_reversion": {
        "family": "range_mean_reversion_vwap_bollinger_research",
        "htf_allowed": ("range",),
        "sensitivity_param": None,
    },
}

# Criterios TRAVADOS (definidos no plano; NAO afrouxar pos-OOS).
CRIT = {
    "pf_net_min_5m": 1.15,
    "pf_net_min_15m": 1.20,
    "pf_net_stressed_min": 1.00,
    "min_trades_oos_5m": 100,
    "min_trades_valoos_5m": 200,
    "min_trades_oos_15m": 40,
    "min_trades_valoos_15m": 80,
    "max_drawdown_pct": 25.0,
    "sign_consistency_min": 0.60,
    "concentration_top5_max": 0.50,
    "param_stability_pf_min": 1.05,
    "regime_min_trades": 30,
}


# ----------------------------- metricas puras -----------------------------

def _trade_pnls(rep) -> List[float]:
    return [float(t.pnl_usd or 0.0) for t in (rep.trades or [])]


def _gross_pf(rep) -> Optional[float]:
    g_win = sum((t.gross_pnl_usd or 0.0) for t in (rep.trades or [])
                if (t.gross_pnl_usd or 0.0) > 0)
    g_loss = sum(-(t.gross_pnl_usd or 0.0) for t in (rep.trades or [])
                 if (t.gross_pnl_usd or 0.0) < 0)
    return round(g_win / g_loss, 4) if g_loss > 0 else None


def _bootstrap_expectancy_ci(pnls: Sequence[float], *, iters: int = 1000,
                             seed: int = 42,
                             alpha: float = 0.05) -> Dict[str, Optional[float]]:
    """IC bootstrap (percentil) da expectancy (media de pnl/trade)."""
    n = len(pnls)
    if n < 2:
        return {"mean": (round(pnls[0], 4) if n == 1 else None),
                "ci_low": None, "ci_high": None, "n": n}
    rng = random.Random(seed)
    means = []
    for _ in range(iters):
        s = 0.0
        for _ in range(n):
            s += pnls[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    lo = means[int((alpha / 2) * iters)]
    hi = means[int((1 - alpha / 2) * iters) - 1]
    return {"mean": round(sum(pnls) / n, 4), "ci_low": round(lo, 4),
            "ci_high": round(hi, 4), "n": n}


def _concentration(rep) -> Dict[str, Optional[float]]:
    """Concentracao do lucro: share dos top-5% trades vencedores sobre o
    GROSS PROFIT positivo (nao sobre net; evita distorcao das perdas)."""
    wins = sorted((float(t.pnl_usd or 0.0) for t in (rep.trades or [])
                   if (t.pnl_usd or 0.0) > 0), reverse=True)
    gross = sum(wins)
    if not wins or gross <= 0:
        return {"top5pct_share": None, "n_winners": len(wins)}
    k = max(1, int(round(len(wins) * 0.05)))
    return {"top5pct_share": round(sum(wins[:k]) / gross, 4),
            "n_winners": len(wins)}


def _monthly_stability(rep, candles) -> Dict[str, Any]:
    """sign_consistency = fracao de meses-calendario net-positivos +
    net sem o melhor mes (concentracao temporal). Usa entry_candle_idx."""
    from crypto_trading_bot.backtesting.data_splits import (
        split_by_calendar_month,
    )
    months = split_by_calendar_month(list(candles))
    by_month: Dict[str, float] = {}
    for label, s, e in months:
        by_month[label] = 0.0
    # map indice de entrada -> mes
    bounds = [(label, s, e) for (label, s, e) in months]
    for t in (rep.trades or []):
        idx = t.entry_candle_idx
        if idx is None:
            continue
        for label, s, e in bounds:
            if s <= idx <= e:
                by_month[label] += float(t.pnl_usd or 0.0)
                break
    vals = list(by_month.values())
    n = len(vals)
    pos = sum(1 for v in vals if v > 0)
    total = sum(vals)
    best = max(vals) if vals else 0.0
    return {
        "months": n,
        "sign_consistency": round(pos / n, 4) if n else None,
        "net_total": round(total, 4),
        "net_excluding_best_month": round(total - best, 4),
        "by_month": {k: round(v, 4) for k, v in by_month.items()},
    }


def _regime_breakdown(rep, regime_ts_map: Mapping[int, Any]) -> Dict[str, Any]:
    """Tagueia cada trade pelo regime (15m, causal) do candle de ENTRADA,
    via entry_time -> regime_ts_map (sem re-classificar; O(n) ).
    Para o 5m o regime e o do 15m alinhado (HTF); para o 15m, o proprio."""
    from crypto_trading_bot.research.htf_regime_filter import _ts_key
    agg: Dict[str, Dict[str, float]] = {}
    for t in (rep.trades or []):
        et = getattr(t, "entry_time", None)
        reg = regime_ts_map.get(_ts_key(et)) if et is not None else None
        if reg is None:
            continue
        a = agg.setdefault(reg, {"trades": 0, "net_pnl": 0.0, "wins": 0})
        a["trades"] += 1
        pnl = float(t.pnl_usd or 0.0)
        a["net_pnl"] += pnl
        if pnl > 0:
            a["wins"] += 1
    out = {}
    for reg, a in agg.items():
        tr = int(a["trades"])
        out[reg] = {"trades": tr, "net_pnl": round(a["net_pnl"], 4),
                    "win_rate": round(a["wins"] / tr, 4) if tr else None,
                    "sufficient": tr >= CRIT["regime_min_trades"]}
    return out


def _baseline_risk_adjusted(candles) -> Dict[str, Optional[float]]:
    """Buy-and-hold REFERENCIA, normalizado por drawdown (retorno/maxDD).
    NAO e gate por PnL absoluto."""
    if len(candles) < 2:
        return {"bh_return_pct": None, "bh_max_dd_pct": None,
                "bh_return_over_dd": None}
    closes = [float(c.close) for c in candles]
    first, last = closes[0], closes[-1]
    ret = (last / first - 1.0) * 100.0 if first else None
    peak = closes[0]
    max_dd = 0.0
    for px in closes:
        peak = max(peak, px)
        dd = (peak - px) / peak * 100.0 if peak else 0.0
        max_dd = max(max_dd, dd)
    rod = (ret / max_dd) if (ret is not None and max_dd > 0) else None
    return {"bh_return_pct": round(ret, 4) if ret is not None else None,
            "bh_max_dd_pct": round(max_dd, 4),
            "bh_return_over_dd": round(rod, 4) if rod is not None else None}


def _metrics(rep, candles, *, capital: float,
             regime_ts_map: Mapping[int, Any]) -> Dict[str, Any]:
    pnls = _trade_pnls(rep)
    total_ret_pct = ((rep.final_capital - capital) / capital * 100.0
                     if capital else 0.0)
    dd = abs(rep.max_drawdown_pct or 0.0)
    payoff = (round(abs(rep.avg_win_usd / rep.avg_loss_usd), 4)
              if rep.avg_loss_usd else None)
    rod = round(total_ret_pct / dd, 4) if dd > 0 else None
    return {
        "total_trades": rep.total_trades,
        "win_rate": rep.win_rate,
        "profit_factor_net": rep.profit_factor,
        "profit_factor_gross": _gross_pf(rep),
        "expectancy_net_usd": rep.expectancy_usd,
        "expectancy_ci": _bootstrap_expectancy_ci(pnls),
        "total_pnl_usd": rep.total_pnl_usd,
        "total_fees_usd": rep.total_fees_usd,
        "total_slippage_usd": rep.total_slippage_usd,
        "payoff": payoff,
        "max_drawdown_pct": rep.max_drawdown_pct,
        "return_pct": round(total_ret_pct, 4),
        "return_over_dd": rod,
        "final_capital": rep.final_capital,
        "blocked_reasons": dict(getattr(rep, "risk_blocked_reasons", {})
                                or {}),
        "concentration": _concentration(rep),
        "monthly": _monthly_stability(rep, candles),
        "regime": _regime_breakdown(rep, regime_ts_map),
        "baseline": _baseline_risk_adjusted(candles),
    }


# ----------------------------- execucao -----------------------------------

def _slice_by_date(candles, start_date: Optional[str], end_date: Optional[str]):
    from datetime import datetime, timezone

    def _p(d):
        if not d:
            return None
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    s, e = _p(start_date), _p(end_date)
    out = []
    for c in candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if s is not None and ts < s:
            continue
        if e is not None and ts >= e:
            continue
        out.append(c)
    return out


def _wrapped_spec(base_spec, regime_map, allowed):
    """StrategySpec cujo factory devolve o HtfRegimeGatedStrategy."""
    from crypto_trading_bot.research.htf_regime_filter import (
        HtfRegimeGatedStrategy,
    )
    from crypto_trading_bot.research.strategy_research import StrategySpec

    def _factory(config):
        base = base_spec.factory(dict(config))
        return HtfRegimeGatedStrategy(base, regime_map, allowed)

    return StrategySpec(name=f"{base_spec.name}_htf15m", factory=_factory,
                        description=f"{base_spec.name} + HTF 15m regime gate",
                        default_config=dict(base_spec.default_config))


def _run_eval(spec, candles, *, cost_label, capital, wf_folds,
              regime_ts_map, min_candles):
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
    wf = getattr(res, "wf_summary", None)
    if wf:
        m["walk_forward"] = dict(wf)
    return m


__all__ = [
    "CRIT", "HYPOTHESES", "EdgeResearchReport", "run_edge_research",
]


# ----------------------------- verdict ------------------------------------

@dataclass(frozen=True)
class EdgeResearchReport:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    hypotheses: Tuple[Mapping[str, Any], ...]
    overall_verdict: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema, "symbol": self.symbol,
            "generated_at": self.generated_at,
            "segments": dict(self.segments),
            "hypotheses": [dict(h) for h in self.hypotheses],
            "overall_verdict": self.overall_verdict,
            "real_execution_allowed": False,
            "demo_blocked": True, "live_blocked": True,
            "strategy_promoted": False,
            "notes": list(self.notes),
        }


def _critical_gates(oos_5m: Mapping[str, Any],
                    stressed_5m: Optional[Mapping[str, Any]]) -> Dict[str, bool]:
    """Gates CRITICOS (falhar qualquer => REJEITAR) no OOS 5m, custo
    realista (+ stressed p/ o gate de custo)."""
    pf = oos_5m.get("profit_factor_net")
    exp_ci = oos_5m.get("expectancy_ci") or {}
    dd = abs(oos_5m.get("max_drawdown_pct") or 0.0)
    stressed_pf = (stressed_5m or {}).get("profit_factor_net")
    return {
        "net_pnl_positive": (oos_5m.get("total_pnl_usd") or 0.0) > 0,
        "pf_net_ok": pf is not None and pf >= CRIT["pf_net_min_5m"],
        "expectancy_ci_low_ge_0": (exp_ci.get("ci_low") is not None
                                   and exp_ci["ci_low"] >= 0),
        "stressed_survives": (stressed_pf is not None
                              and stressed_pf >= CRIT["pf_net_stressed_min"]),
        "drawdown_ok": dd <= CRIT["max_drawdown_pct"],
    }


def _noncritical_gates(oos_5m, val_5m, sens) -> Dict[str, bool]:
    monthly = (val_5m or {}).get("monthly") or {}
    conc = (oos_5m or {}).get("concentration") or {}
    regime = (oos_5m or {}).get("regime") or {}
    base = (oos_5m or {}).get("baseline") or {}
    sc = monthly.get("sign_consistency")
    top5 = conc.get("top5pct_share")
    rod = oos_5m.get("return_over_dd")
    bh_rod = base.get("bh_return_over_dd")
    return {
        "sign_consistency": sc is not None and sc >= CRIT["sign_consistency_min"],
        "not_concentrated": (top5 is not None
                             and top5 < CRIT["concentration_top5_max"]
                             and (monthly.get("net_excluding_best_month") or 0)
                             >= 0),
        "param_stable": bool(sens) and sens.get("stable", False),
        "regime_sufficient": any(r.get("sufficient")
                                 for r in regime.values()) if regime else False,
        "beats_baseline_risk_adj": (rod is not None and bh_rod is not None
                                    and rod >= bh_rod),
    }


def _sample_ok(oos, valoos, *, tf: str) -> bool:
    if tf == "5m":
        return ((oos.get("total_trades") or 0) >= CRIT["min_trades_oos_5m"]
                and valoos >= CRIT["min_trades_valoos_5m"])
    return ((oos.get("total_trades") or 0) >= CRIT["min_trades_oos_15m"]
            and valoos >= CRIT["min_trades_valoos_15m"])


def _decide(crit: Mapping[str, bool], noncrit: Mapping[str, bool],
            sample_ok: bool) -> str:
    if not sample_ok:
        return "REJEITAR"          # insufficient_sample => nao promove
    if not all(crit.values()):
        return "REJEITAR"
    n_ok = sum(1 for v in noncrit.values() if v)
    if n_ok >= 4:
        return "PROMOVER_PARA_PAPER"
    return "REFINAR_COM_HIPOTESE_ESPECIFICA"


def run_edge_research(
    candles_5m: Sequence, candles_15m: Sequence, *,
    symbol: str = "BTCUSDT",
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-06-01"),
    capital: float = 5000.0, wf_folds: int = 5, regime_lookback: int = 96,
    hypotheses: Optional[Sequence[str]] = None,
    run_oos: bool = True, progress=None,
) -> EdgeResearchReport:
    """Orquestra DEV->VAL->OOS p/ as hipoteses no 5m (primario) + 15m
    (controle), variante HTF so no 5m. OOS so e tocado se DEV passar
    early-stop. Custo realista principal; stressed no OOS p/ gate de custo."""
    from datetime import datetime, timezone

    def _cb(msg):
        if progress:
            progress(msg)

    hyps = list(hypotheses) if hypotheses else list(HYPOTHESES.keys())
    # Classifica regime SO no 15m UMA vez (classify_regimes e O(n^2); jamais
    # no 5m). Deriva: map5 (5m->regime 15m, causal close_time) p/ gate HTF e
    # breakdown do 5m; map15 (15m->proprio regime) p/ breakdown do controle.
    _cb("classificando regime 15m (uma vez) + alinhando 15m->5m causal")
    from crypto_trading_bot.research.htf_regime_filter import (
        align_from_classification,
        regime_ts_map,
    )
    from crypto_trading_bot.research.market_regime import classify_regimes
    rc15 = classify_regimes(candles_15m, lookback=regime_lookback)
    regime_map = align_from_classification(candles_5m, candles_15m, rc15)
    map15 = regime_ts_map(candles_15m, rc15)
    tf_regime_map = {"5m": regime_map, "15m": map15}

    from crypto_trading_bot.research.strategy_family_research import (
        _family_spec,
    )

    seg_def = {"dev": dev, "val": val, "oos": oos}
    series = {"5m": candles_5m, "15m": candles_15m}
    # min_candles por TF (warmup do FeatureEngine).
    min_candles = 120

    hyp_reports: List[Dict[str, Any]] = []
    for hyp in hyps:
        meta = HYPOTHESES[hyp]
        base_spec, _ = _family_spec(meta["family"])
        allowed = meta["htf_allowed"]
        tf_blocks: Dict[str, Any] = {}
        verdict_5m = "REJEITAR"
        for tf, candles in series.items():
            rmap = tf_regime_map[tf]
            variants = ["base"] + (["htf"] if tf == "5m" else [])
            var_blocks: Dict[str, Any] = {}
            for variant in variants:
                spec = (base_spec if variant == "base"
                        else _wrapped_spec(base_spec, regime_map, allowed))
                # DEV (realista) + early-stop
                dev_c = _slice_by_date(candles, *seg_def["dev"])
                _cb(f"{hyp} {tf} {variant} DEV")
                dev_m = _run_eval(spec, dev_c, cost_label="realistic_research",
                                  capital=capital, wf_folds=wf_folds,
                                  regime_ts_map=rmap, min_candles=min_candles)
                stop = _early_stop(dev_m)
                block = {"dev": dev_m, "early_stop": stop}
                if stop is None and run_oos:
                    val_c = _slice_by_date(candles, *seg_def["val"])
                    oos_c = _slice_by_date(candles, *seg_def["oos"])
                    _cb(f"{hyp} {tf} {variant} VAL")
                    block["val"] = _run_eval(
                        spec, val_c, cost_label="realistic_research",
                        capital=capital, wf_folds=wf_folds,
                        regime_ts_map=rmap, min_candles=min_candles)
                    _cb(f"{hyp} {tf} {variant} OOS (realista+stressed+zero)")
                    block["oos"] = _run_eval(
                        spec, oos_c, cost_label="realistic_research",
                        capital=capital, wf_folds=None,
                        regime_ts_map=rmap, min_candles=min_candles)
                    block["oos_stressed"] = _run_eval(
                        spec, oos_c, cost_label="stressed_research",
                        capital=capital, wf_folds=None,
                        regime_ts_map=rmap, min_candles=min_candles)
                    block["oos_zero_diag"] = _run_eval(
                        spec, oos_c, cost_label="zero_cost",
                        capital=capital, wf_folds=None,
                        regime_ts_map=rmap, min_candles=min_candles)
                    block["sensitivity"] = _sensitivity(
                        spec, dev_c, capital=capital, min_candles=min_candles)
                var_blocks[variant] = block
            tf_blocks[tf] = var_blocks
        # verdict no 5m primario: melhor entre base|htf que NAO parou cedo.
        v, chosen = _verdict_for_hypothesis(tf_blocks.get("5m", {}))
        hyp_reports.append({
            "hypothesis": hyp, "family": meta["family"],
            "chosen_variant_5m": chosen, "verdict": v,
            "timeframes": tf_blocks})
        verdict_5m = v

    order = {"PROMOVER_PARA_PAPER": 2, "REFINAR_COM_HIPOTESE_ESPECIFICA": 1,
             "REJEITAR": 0}
    overall = max((h["verdict"] for h in hyp_reports),
                  key=lambda x: order[x], default="REJEITAR")
    return EdgeResearchReport(
        schema="edge_research_phase44_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos,
                  "note": "OOS travado; refinar exige janela futura nao "
                          "observada"},
        hypotheses=tuple(hyp_reports), overall_verdict=overall,
        notes=("Demo/live bloqueados; nenhuma estrategia promovida "
               "automaticamente; PROMOVER habilita SO p/ paper.",
               "Custo realista = resultado principal; zero=diagnostico; "
               "stressed=robustez.",))


def _early_stop(dev_m: Mapping[str, Any]) -> Optional[str]:
    """Early-stop no DEV (custo realista). Retorna motivo ou None."""
    pf = dev_m.get("profit_factor_net")
    exp = dev_m.get("expectancy_net_usd")
    trades = dev_m.get("total_trades") or 0
    monthly = dev_m.get("monthly") or {}
    sc = monthly.get("sign_consistency")
    if trades < 30:
        return "insufficient_sample_dev"
    if (exp is not None and exp <= 0) and (pf is not None and pf < 1.05):
        return "no_edge_dev"
    if sc is not None and sc < 0.40:
        return "profit_concentrated_dev"
    return None


def _sensitivity(spec, dev_c, *, capital, min_candles) -> Dict[str, Any]:
    """Sensibilidade +-1 passo no 1o param numerico do default_config
    (vizinhanca, nao busca ampla). Edge nao pode ser otimo de faca."""
    cfg = dict(spec.default_config)
    key = None
    for k, v in cfg.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v:
            key = k
            break
    if key is None:
        return {"param": None, "stable": False, "variants": []}
    base_v = cfg[key]
    variants = []
    pfs = []
    from crypto_trading_bot.research.calibration_costs import (
        build_cost_scenario,
    )
    from crypto_trading_bot.research.strategy_research import evaluate_strategy
    for factor in (0.8, 1.2):
        try:
            ov = {key: type(base_v)(base_v * factor)}
            res = evaluate_strategy(
                spec, list(dev_c), initial_capital=capital,
                min_candles=min_candles, config_override=ov,
                execution_cost_config=build_cost_scenario(
                    "realistic_research").config,
                precompute_features=True)
            pf = res.single_report.profit_factor
            variants.append({"param": key, "value": ov[key],
                             "profit_factor_net": pf})
            if pf is not None:
                pfs.append(pf)
        except Exception:  # noqa: BLE001
            continue
    stable = bool(pfs) and all(p >= CRIT["param_stability_pf_min"]
                               for p in pfs)
    return {"param": key, "base_value": base_v, "stable": stable,
            "variants": variants}


def _verdict_for_hypothesis(tf5: Mapping[str, Any]) -> Tuple[str, Optional[str]]:
    """Decide o verdict no 5m primario, escolhendo a melhor variante
    (base|htf) que chegou ao OOS."""
    order = {"PROMOVER_PARA_PAPER": 2, "REFINAR_COM_HIPOTESE_ESPECIFICA": 1,
             "REJEITAR": 0}
    best = ("REJEITAR", None)
    for variant, block in tf5.items():
        if block.get("early_stop") is not None or "oos" not in block:
            continue
        oos = block["oos"]
        stressed = block.get("oos_stressed")
        val = block.get("val") or {}
        sens = block.get("sensitivity") or {}
        valoos = ((val.get("total_trades") or 0)
                  + (oos.get("total_trades") or 0))
        crit = _critical_gates(oos, stressed)
        noncrit = _noncritical_gates(oos, val, sens)
        v = _decide(crit, noncrit, _sample_ok(oos, valoos, tf="5m"))
        if order[v] > order[best[0]]:
            best = (v, variant)
    return best
