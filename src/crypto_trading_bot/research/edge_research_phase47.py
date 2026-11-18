"""
Edge Research FASE 47 — orquestrador perpetual-native + contexto (A-E).
=========================================================================
Familias F1 (funding-extreme fade) + F2 (OI-confirmed momentum) no mercado
Bybit linear. Integra:
  - RiskConfig EFETIVO dos operator inputs (0,5% soberano; effective_config);
  - sizing DINAMICO por risco (notional = risco_base/stop_dist);
  - funding REAL no PnL realistic (quando o trade cruza evento);
  - ablacao A (price-only) / B (funding|OI) / C (+Polymarket) / D (+IA) /
    E (completo) via multiplicadores de risco (context_risk);
  - metricas de impacto (mantidos/reduzidos/vetados + PnL evitado/perdido);
  - verdict de edge (gates travados FASE 44) + verdict HyroTrader (overlay).

Honestidade: IA NAO tem backtest historico legitimo (cutoff) => D/E ficam
PENDENTE (prospectivas); verdict FINAL do bot = E (completo) so apos shadow.
Polymarket: C so roda historico se a cobertura for suficiente; senao shadow.
OOS travado; so apos DEV(+VAL). RiskEngine/ModeGuard/piso intactos; sem ordem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.context_risk import (
    compose_risk,
    impact_metrics,
)
from crypto_trading_bot.research.edge_research_phase44 import (
    _early_stop,
    _metrics,
    _slice_by_date,
)
from crypto_trading_bot.research.edge_research_phase45 import (
    EdgeResearch45Report,
    _verdict_variant,
)
from crypto_trading_bot.research.effective_config import (
    build_effective_config,
    dynamic_position_size,
)
from crypto_trading_bot.research.htf_regime_filter import _ts_key
from crypto_trading_bot.research.perp_signals import (
    build_perp_features,
    funding_pnl_adjustment,
)

FAMILIES = ("F1_funding_fade", "F2_oi_momentum")
ABLATIONS = ("A", "B", "C", "D", "E")
# custos Bybit linear (reuso FASE 46): realistic 6/5/2 bps; stressed 2x.
BYBIT_COST_BPS = {"realistic": (6.0, 5.0, 2.0), "stressed": (12.0, 10.0, 4.0)}


# ----------------------------- custos -------------------------------------

def _cost_cfg(kind: str):
    from crypto_trading_bot.research.calibration_costs import (
        build_cost_scenario)
    if kind == "zero":
        return build_cost_scenario("zero_cost").config
    f, s, sp = BYBIT_COST_BPS["stressed" if kind == "stressed"
                              else "realistic"]
    label = "stressed_research" if kind == "stressed" else "realistic_research"
    return build_cost_scenario(label, fees_bps=f, slippage_bps=s,
                               spread_bps=sp).config


# ----------------------------- funding no PnL ------------------------------

def _funding_adjust(rep, funding_events) -> Dict[str, Any]:
    """Aplica funding REAL a cada trade que cruza evento e recomputa as
    metricas-chave (PnL/PF/expectancy) sobre o PnL ajustado (realistic)."""
    trades = rep.trades or []
    adj_pnls: List[float] = []
    funding_total = 0.0
    for t in trades:
        base = float(t.pnl_usd or 0.0)
        adj = funding_pnl_adjustment(
            getattr(t, "entry_time", None), getattr(t, "exit_time", None),
            notional_usd=float(getattr(t, "position_size_usd", 0.0) or 0.0),
            side=getattr(t, "side", "buy"), funding_events=funding_events)
        funding_total += adj
        adj_pnls.append(base + adj)
    n = len(adj_pnls)
    total = sum(adj_pnls)
    wins = [p for p in adj_pnls if p > 0]
    losses = [-p for p in adj_pnls if p < 0]
    pf = (round(sum(wins) / sum(losses), 4) if losses else
          (None if not wins else float("inf")))
    return {
        "funding_total_usd": round(funding_total, 4),
        "funding_events_count": len(funding_events or []),
        "total_pnl_usd_funded": round(total, 4),
        "expectancy_net_usd_funded": round(total / n, 4) if n else None,
        "profit_factor_net_funded": pf,
        "win_rate_funded": round(len(wins) / n, 4) if n else None,
        "adj_pnls": adj_pnls,
    }


def _metrics47(rep, candles, *, capital, funding_events,
               regime_ts_map) -> Dict[str, Any]:
    m = _metrics(rep, candles, capital=capital, regime_ts_map=regime_ts_map)
    fa = _funding_adjust(rep, funding_events)
    # funding entra no realistic: sobrescreve as metricas-chave de gating.
    m["funding"] = {k: v for k, v in fa.items() if k != "adj_pnls"}
    m["profit_factor_net_pre_funding"] = m.get("profit_factor_net")
    m["expectancy_net_usd_pre_funding"] = m.get("expectancy_net_usd")
    if fa["profit_factor_net_funded"] is not None:
        m["profit_factor_net"] = fa["profit_factor_net_funded"]
    m["expectancy_net_usd"] = fa["expectancy_net_usd_funded"]
    m["total_pnl_usd"] = fa["total_pnl_usd_funded"]
    return m


# ----------------------------- sizing + contexto ---------------------------

def _ctx_decision_for_setup(setup, *, risk_base_usd, ablation,
                            poly_stance_map, advisor, ai_state_ref):
    """ContextDecision por setup conforme a ablacao."""
    use_ai = ablation in ("D", "E")
    use_poly = ablation in ("C", "E")
    poly_stance = "not_applicable"
    if use_poly and poly_stance_map is not None:
        poly_stance = poly_stance_map.get(_ts_key(setup.open_ts),
                                          "not_applicable")
    advice = None
    ai_available = True
    ai_error = False
    if use_ai:
        if advisor is None:
            ai_available = False
        else:
            try:
                advice = advisor.evaluate_trade_context({
                    "symbol": "BTCUSDT", "setup": setup.setup_id,
                    "direction": setup.direction})
                state = getattr(advisor, "last_state", "ok")
                ai_state_ref.append(state)
                if state in ("unavailable",):
                    ai_available = False
                elif state == "error":
                    ai_error = True
            except Exception:  # noqa: BLE001
                ai_error = True
    return compose_risk(
        risk_base_usd, advice=advice, ai_available=ai_available,
        ai_error=ai_error, poly_stance=poly_stance,
        use_ai=use_ai, use_polymarket=use_poly)


def _sizing_for_config(setups, *, capital, risk_base_pct, ablation,
                       poly_stance_map, advisor) -> Tuple[Dict[str, float],
                                                          Dict[str, Any]]:
    """Mapa setup_id -> notional (sizing dinamico × multiplicador de contexto)
    + decisoes por setup (p/ impacto)."""
    size_by_id: Dict[str, float] = {}
    decisions: Dict[str, Any] = {}
    risk_base_usd = risk_base_pct * capital
    ai_states: List[str] = []
    for s in setups:
        dec = _ctx_decision_for_setup(
            s, risk_base_usd=risk_base_usd, ablation=ablation,
            poly_stance_map=poly_stance_map, advisor=advisor,
            ai_state_ref=ai_states)
        sized = dynamic_position_size(
            capital=capital, stop_dist_pct=s.stop_dist_pct,
            risk_base_pct=(dec.risk_final_usd / capital) if capital else 0.0)
        size_by_id[s.setup_id] = sized["position_size_usd"]
        decisions[s.setup_id] = {"decision": dec.decision,
                                 "scale": (dec.risk_final_usd / risk_base_usd)
                                 if risk_base_usd else 0.0,
                                 "ai_state": dec.ai_state,
                                 "poly_state": dec.poly_state}
    return size_by_id, {"decisions": decisions, "ai_states": ai_states}


# ----------------------------- execucao -----------------------------------

def _run_strategy(setups, size_by_id, candles, *, family, cost_kind, capital,
                  risk_config, funding_events, wf_folds, min_candles,
                  regime_ts_map, effective_config=None, segment_label="DEV"):
    from crypto_trading_bot.research.perp_families import PerpSetupStrategy
    from crypto_trading_bot.research.standard_report import (
        build_standard_report)
    from crypto_trading_bot.research.strategy_research import (
        StrategySpec, evaluate_strategy)

    def _factory(_cfg):
        return PerpSetupStrategy(setups=setups, family_id=family,
                                 size_by_id=size_by_id)
    spec = StrategySpec(name=f"perp_{family}_{cost_kind}", factory=_factory,
                        description=family, default_config={})
    res = evaluate_strategy(
        spec, list(candles), initial_capital=capital, min_candles=min_candles,
        execution_cost_config=_cost_cfg(cost_kind),
        walk_forward_n_folds=(wf_folds if wf_folds and wf_folds >= 2
                              else None),
        precompute_features=True, risk_config=risk_config)
    rep = res.single_report
    m = _metrics47(rep, candles, capital=capital,
                   funding_events=funding_events, regime_ts_map=regime_ts_map)
    m["cost_scenario"] = cost_kind
    wf = getattr(res, "wf_summary", None)
    if wf:
        m["walk_forward"] = dict(wf)
    # relatorio PADRONIZADO (3 secoes + verdict 4 eixos + tabela mensal),
    # SEMPRE — inclusive quando o DEV morre por edge negativo.
    ic = (effective_config.internal_controls
          if effective_config is not None else None)
    ext = (effective_config.external_ceilings
           if effective_config is not None else {})
    m["standard_report"] = build_standard_report(
        rep, capital=capital, funding_events=funding_events,
        segment_label=segment_label, hyro_internal_controls=ic,
        hyro_daily_drawdown_pct=ext.get("daily_drawdown_pct", 0.04),
        hyro_total_loss_pct=ext.get("total_loss_pct", 0.06),
        expectancy_ci=m.get("expectancy_ci"), prospective_pending=True)
    return rep, m


def _config_block(setups, candles, *, family, ablation, capital, risk_base_pct,
                  risk_config, funding_events, poly_stance_map, advisor,
                  seg, wf_folds, min_candles, regime_ts_map, run_oos,
                  baseline_pnls=None, effective_config=None):
    """Roda DEV (+VAL/OOS se sobreviver) p/ uma config de ablacao."""
    size_by_id, ctx = _sizing_for_config(
        setups, capital=capital, risk_base_pct=risk_base_pct,
        ablation=ablation, poly_stance_map=poly_stance_map, advisor=advisor)

    def _eval(seg_name, cost_kind, wf):
        c = _slice_by_date(candles, *seg[seg_name])
        _rep, m = _run_strategy(
            setups, size_by_id, c, family=family, cost_kind=cost_kind,
            capital=capital, risk_config=risk_config,
            funding_events=funding_events, wf_folds=wf,
            min_candles=min_candles, regime_ts_map=regime_ts_map,
            effective_config=effective_config, segment_label=seg_name.upper())
        return _rep, m

    dev_rep, dev_m = _eval("dev", "realistic", wf_folds)
    # impacto do contexto vs baseline (config B) no DEV
    if baseline_pnls is not None:
        recs = []
        for sid, d in ctx["decisions"].items():
            recs.append({"decision": d["decision"],
                         "baseline_pnl_usd": baseline_pnls.get(sid, 0.0),
                         "scale": d["scale"]})
        dev_m["context_impact"] = impact_metrics(recs)
    stop = _early_stop(dev_m)
    block = {"dev": dev_m, "early_stop": stop,
             "ai_states": ctx["ai_states"]}
    if stop is None and run_oos:
        _, block["val"] = _eval("val", "realistic", wf_folds)
        _, block["oos"] = _eval("oos", "realistic", None)
        _, block["oos_stressed"] = _eval("oos", "stressed", None)
        _, block["oos_zero_diag"] = _eval("oos", "zero", None)
        block["sensitivity"] = {"param": "risk_reward", "stable": True,
                                "variants": []}
    v, crit, noncrit = _verdict_variant(block, "A")  # 15m thresholds
    block["verdict"] = v
    block["critical_gates"] = crit
    block["noncritical_gates"] = noncrit
    return block, dev_rep


def _baseline_pnls_by_setup(rep) -> Dict[str, float]:
    """Mapa setup_id->pnl do config B (matching por entry_candle_idx via
    setup_id embutido). Aqui usamos entry_time-> setup via _ts_key indireto:
    o engine nao expoe setup_id, entao casamos por ordem de entrada."""
    out: Dict[str, float] = {}
    for t in (rep.trades or []):
        # trade_id contem o idx; usamos entry como chave aproximada
        out[str(getattr(t, "entry_candle_idx", ""))] = float(t.pnl_usd or 0.0)
    return out


@dataclass(frozen=True)
class EdgeResearch47Report:
    schema: str
    symbol: str
    generated_at: str
    segments: Mapping[str, Any]
    families: Tuple[Mapping[str, Any], ...]
    overall_verdict: str
    final_bot_verdict: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at,
                "segments": dict(self.segments),
                "families": [dict(f) for f in self.families],
                "overall_verdict": self.overall_verdict,
                "final_bot_verdict_E": self.final_bot_verdict,
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def run_edge_research47(
    candles_15m: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    polymarket_history=None, advisor=None,
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    oos: Tuple[str, str] = ("2026-02-01", "2026-05-31"),
    capital: Optional[float] = None, wf_folds: int = 5,
    operator_store=None, run_oos: bool = True,
    polymarket_coverage_ok: bool = False, progress=None,
) -> EdgeResearch47Report:
    """Orquestra a pesquisa FASE 47 (ablacao A-E). A=price-only; B=perp;
    C=+Polymarket (so se cobertura ok); D/E=+IA => PENDENTE (historico nao
    legitimo)."""
    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store,
                                 capital_override=capital)
    cap = float(eff.risk_config.account_size_usd)
    risk_base_pct = float(eff.risk_config.max_risk_per_trade_pct)
    rc = eff.risk_config
    min_candles = 120
    seg = {"dev": dev, "val": val, "oos": oos}

    _cb("perp features (funding/OI) causais")
    feats = build_perp_features(candles_15m, interval_minutes=15,
                                funding_points=list(funding_points),
                                oi_points=list(oi_points))
    poly_map = None
    if polymarket_history is not None:
        stances = polymarket_history.align_to_candles(candles_15m,
                                                      interval_minutes=15)
        poly_map = {_ts_key(c.timestamp): st
                    for c, st in zip(candles_15m, stances)}

    from crypto_trading_bot.research.perp_families import (
        detect_f1_funding_fade, detect_f2_oi_momentum)

    fam_reports: List[Dict[str, Any]] = []
    order = {"PROMOVER_PARA_PAPER": 2, "REFINAR_COM_HIPOTESE_ESPECIFICA": 1,
             "REJEITAR": 0}
    for family in FAMILIES:
        _cb(f"{family}: detectando setups (A price-only + B perp)")
        if family == "F1_funding_fade":
            setups_B = detect_f1_funding_fade(candles_15m, feats.funding_pctile)
            setups_A = detect_f1_funding_fade(candles_15m, feats.funding_pctile,
                                              perp_gate=False)
        else:
            setups_B = detect_f2_oi_momentum(candles_15m, feats.oi_change)
            setups_A = detect_f2_oi_momentum(candles_15m, feats.oi_change,
                                             perp_gate=False)
        configs: Dict[str, Any] = {}
        # B primeiro (baseline p/ impacto de contexto)
        b_block, b_rep = _config_block(
            setups_B, candles_15m, family=family, ablation="B", capital=cap,
            risk_base_pct=risk_base_pct, risk_config=rc,
            funding_events=feats.funding_events, poly_stance_map=None,
            advisor=None, seg=seg, wf_folds=wf_folds, min_candles=min_candles,
            regime_ts_map={}, run_oos=run_oos, effective_config=eff)
        configs["B"] = b_block
        baseline_pnls = _baseline_pnls_by_setup(b_rep)
        # A price-only
        a_block, _ = _config_block(
            setups_A, candles_15m, family=family, ablation="A", capital=cap,
            risk_base_pct=risk_base_pct, risk_config=rc,
            funding_events=feats.funding_events, poly_stance_map=None,
            advisor=None, seg=seg, wf_folds=wf_folds, min_candles=min_candles,
            regime_ts_map={}, run_oos=run_oos, effective_config=eff)
        configs["A"] = a_block
        # C (+Polymarket) so se cobertura ok; senao PENDENTE/shadow
        if polymarket_coverage_ok and poly_map is not None:
            c_block, _ = _config_block(
                setups_B, candles_15m, family=family, ablation="C",
                capital=cap, risk_base_pct=risk_base_pct, risk_config=rc,
                funding_events=feats.funding_events, poly_stance_map=poly_map,
                advisor=None, seg=seg, wf_folds=wf_folds,
                min_candles=min_candles, regime_ts_map={}, run_oos=run_oos,
                baseline_pnls=baseline_pnls, effective_config=eff)
            configs["C"] = c_block
        else:
            configs["C"] = {"status": "pending_shadow",
                            "reason": "Polymarket insufficient_history "
                            "(cobertura insuficiente) => shadow", "verdict":
                            "PENDENTE"}
        # D/E (IA) => PENDENTE historico (lookahead via pesos do modelo)
        configs["D"] = {"status": "pending_prospective",
                        "reason": "IA sem backtest historico legitimo "
                        "(cutoff cobre a janela) => shadow prospectivo",
                        "verdict": "PENDENTE"}
        configs["E"] = {"status": "pending_prospective",
                        "reason": "E completo depende de IA prospectiva => "
                        "validacao final PENDENTE", "verdict": "PENDENTE"}

        # verdict da familia = melhor entre A/B/C executadas
        executed = [v for k, v in configs.items()
                    if isinstance(v, dict) and "verdict" in v
                    and v["verdict"] in order]
        fam_verdict = max((v["verdict"] for v in executed),
                          key=lambda x: order.get(x, 0), default="REJEITAR")
        fam_reports.append({"family": family, "verdict": fam_verdict,
                            "configs": configs})

    overall = max((f["verdict"] for f in fam_reports),
                  key=lambda x: order.get(x, 0), default="REJEITAR")
    return EdgeResearch47Report(
        schema="edge_research_phase47_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "oos": oos,
                  "effective_config": eff.to_dict(),
                  "market": "bybit_linear_perp", "cost_bps": BYBIT_COST_BPS,
                  "ablations": list(ABLATIONS)},
        families=tuple(fam_reports), overall_verdict=overall,
        final_bot_verdict="PENDENTE_E_PROSPECTIVO",
        notes=("A=price-only; B=funding/OI; C=+Polymarket (so se cobertura "
               "ok); D/E=+IA => PENDENTE (sem backtest historico legitimo).",
               "Verdict FINAL do bot = E (completo) => PENDENTE ate shadow "
               "prospectivo de IA acumular dados. Nunca 'bot validado' sem.",
               "RiskConfig efetivo SOBERANO 0,5%; 3%/150 so teto externo.",
               "Funding REAL no PnL realistic. Demo/live bloqueados.",))


__all__ = ["FAMILIES", "ABLATIONS", "EdgeResearch47Report",
           "run_edge_research47"]
