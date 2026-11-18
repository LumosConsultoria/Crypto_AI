"""
Edge Research FASE 60 — Multi-Asset Cross-Sectional Sprint (Bybit Linear 5m).
============================================================================
3 hipoteses cross-sectional (scan/ranking; 1 posicao; melhor ativo elegivel por
ciclo; SEM basket). Params PRE-FIXADOS; sem grid. Custos reais Bybit; dual-
profile (hyro_challenge_attempts + standard_trader_monthly_close); gate dos 8
criterios (FASE 59) por segmento. DEV primeiro; VAL so se DEV passar; OOS
intocado. 0,5% primario + 1% sensibilidade separada.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.cross_sectional import (
    REALISTIC_COST, Universe, run_xs_backtest)
from crypto_trading_bot.research.edge_research_phase59 import _gate, _reason
from crypto_trading_bot.research.effective_config import build_effective_config


def _seg_range(timestamps: Sequence, dev_lo: str, dev_hi: str):
    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    def _utc(ts):
        return ts if getattr(ts, "tzinfo", None) else ts.replace(
            tzinfo=timezone.utc)
    ts = [_utc(t) for t in timestamps]
    return bisect.bisect_left(ts, _p(dev_lo)), bisect.bisect_left(ts, _p(dev_hi))


@dataclass(frozen=True)
class EdgeResearch60Report:
    schema: str
    universe: Mapping[str, Any]
    generated_at: str
    segments: Mapping[str, Any]
    loop: Mapping[str, Any]
    per_hypothesis: Mapping[str, Any]
    ranking: Tuple[Mapping[str, Any], ...]
    decision: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "universe": dict(self.universe),
                "generated_at": self.generated_at,
                "segments": dict(self.segments), "loop": dict(self.loop),
                "per_hypothesis": dict(self.per_hypothesis),
                "ranking": [dict(r) for r in self.ranking],
                "decision": self.decision, "real_execution_allowed": False,
                "demo_blocked": True, "live_blocked": True,
                "strategy_promoted": False, "notes": list(self.notes)}


def _spec(name, rationale, why_diff, params, family):
    from crypto_trading_bot.research.research_loop import HypothesisSpec
    return HypothesisSpec(
        name=name, economic_rationale=rationale, why_different=why_diff,
        data_used=["ohlcv", "multi_asset"], fixed_params=dict(params),
        accept_criteria=("DEV->VAL: net>0/PF>=1,15/exp>0/>=100tr/sc>=0,60/"
                         ">=3meses/Hyro attempts>=3/class!=sem_edge/CI ok"),
        expected_reason_to_work="edge RELATIVO entre ativos (nao previsao BTC).",
        family=family, variants=1)


def run_edge_research60(
    candles_by_symbol: Dict[str, Sequence], *,
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    operator_store=None, progress=None) -> EdgeResearch60Report:
    from crypto_trading_bot.research.cross_sectional_families import (
        DETECTORS, H1_PARAMS, H2_PARAMS, H3_PARAMS, HOLD_BARS)
    from crypto_trading_bot.research.research_loop import run_research_loop
    from crypto_trading_bot.research.standard_report import build_standard_report

    def _cb(m):
        if progress:
            progress(m)

    eff = build_effective_config(store=operator_store)
    capital = float(eff.risk_config.account_size_usd)
    max_notional = eff.sizing_policy["caps"].get("hyro_max_notional_usd")
    _cb(f"universe: {list(candles_by_symbol)}")
    u = Universe(candles_by_symbol)
    dev_lo, dev_hi = _seg_range(u.timestamps, *dev)
    val_lo, val_hi = _seg_range(u.timestamps, *val)

    specs = [
        _spec("relative_strength_continuation_5m",
              "seguir o ativo de maior forca relativa em regime amplo favoravel",
              "edge RELATIVO (ranking entre ativos), nao previsao absoluta de "
              "1 ativo; evita queda ampla correlacionada", H1_PARAMS,
              "xs_relative_strength"),
        _spec("relative_reversion_after_dispersion_5m",
              "fade do ativo mais esticado vs basket quando a dispersao extrema "
              "reverte", "reversao CROSS-SECTIONAL condicionada a dispersao do "
              "basket, nao MR de preco isolado", H2_PARAMS,
              "xs_dispersion_reversion"),
        _spec("btc_lead_lag_alt_follow_5m",
              "BTC lider; entrar no alt que atrasou na direcao do BTC com "
              "confirmacao", "explora LEAD-LAG entre ativos (relacao causal "
              "BTC->alt), nao momentum de 1 ativo", H3_PARAMS, "xs_lead_lag"),
    ]

    setups_by: Dict[str, list] = {}
    for sp in specs:
        _cb(f"setups: {sp.name}")
        setups_by[sp.name] = DETECTORS[sp.name](u, params=dict(sp.fixed_params))
        _cb(f"  {sp.name}: {len(setups_by[sp.name])} setups")

    reports: Dict[str, Dict[str, Any]] = {}

    def evaluator(spec, segment):
        lo, hi = (dev_lo, dev_hi) if segment == "DEV" else (val_lo, val_hi)
        rep = run_xs_backtest(u, setups_by[spec.name], capital=capital,
                              risk_base_pct=0.005, max_notional=max_notional,
                              cost_pct=REALISTIC_COST, max_holding=HOLD_BARS,
                              seg_lo=lo, seg_hi=hi)
        base = build_standard_report(rep, capital=capital, funding_events=[],
                                     segment_label=segment,
                                     hyro_internal_controls=eff.internal_controls,
                                     hyro_daily_drawdown_pct=eff.external_ceilings[
                                         "daily_drawdown_pct"],
                                     hyro_total_loss_pct=eff.external_ceilings[
                                         "total_loss_pct"], risk_base_pct=0.005)
        gate = _gate(base)
        ret = dict(base)
        v = dict(base.get("verdict", {}) or {})
        v["edge_estatistico"] = "aprovado" if gate["passed"] else "rejeitado"
        ret["verdict"] = v
        ret["phase60_gate"] = gate
        ret["phase59_gate"] = gate                # p/ _reason
        reports.setdefault(spec.name, {})[segment] = ret
        return ret

    _cb("research loop (DEV; VAL so se DEV passar; OOS intocado)")
    loop = run_research_loop(specs, evaluator, progress=progress)

    per_hyp: Dict[str, Any] = {}
    rank_rows: List[Dict[str, Any]] = []
    for sp in specs:
        segs = reports.get(sp.name, {})
        dev_sr = segs.get("DEV", {})
        sm = dev_sr.get("strategy_metrics", {}) or {}
        rep1 = run_xs_backtest(u, setups_by[sp.name], capital=capital,
                               risk_base_pct=0.01, max_notional=max_notional,
                               cost_pct=REALISTIC_COST, max_holding=HOLD_BARS,
                               seg_lo=dev_lo, seg_hi=dev_hi)
        sr1 = build_standard_report(rep1, capital=capital, funding_events=[],
                                    segment_label="DEV", risk_base_pct=0.01)
        block = {
            "name": sp.name, "n_setups": len(setups_by.get(sp.name, [])),
            "params_prefixed": dict(sp.fixed_params),
            "dev_classification": dev_sr.get("classification"),
            "dev_verdict": dev_sr.get("verdict"),
            "dev_gate": dev_sr.get("phase60_gate"),
            "dev_strategy_metrics": sm,
            "dev_hyro_attempts": dev_sr.get("hyro_challenge_attempts"),
            "dev_monthly_close": dev_sr.get("standard_trader_monthly_close"),
            "sensitivity_1pct_separate": {
                "note": "1% — sensibilidade SEPARADA, fora da decisao (0,5%)",
                "trader_padrao_dev": sr1.get("standard_trader_evaluation")},
            "reject_reason": _reason(dev_sr),
        }
        if "VAL" in segs:
            vsr = segs["VAL"]
            block["val_classification"] = vsr.get("classification")
            block["val_gate"] = vsr.get("phase60_gate")
            block["val_strategy_metrics"] = vsr.get("strategy_metrics")
            block["val_reject_reason"] = _reason(vsr)
        per_hyp[sp.name] = block
        n_pass = sum(1 for ok in (dev_sr.get("phase60_gate", {}).get("checks")
                                  or {}).values() if ok)
        rank_rows.append({"name": sp.name, "n_setups": block["n_setups"],
                          "dev_trades": sm.get("num_trades"),
                          "dev_net": sm.get("net_pnl_usd"),
                          "dev_pf": sm.get("profit_factor_net"),
                          "dev_criteria_passed": n_pass,
                          "dev_classification": dev_sr.get("classification")})
    rank_rows.sort(key=lambda r: (-(r["dev_criteria_passed"] or 0),
                                  -((r["dev_net"] or 0))))

    ld = loop.to_dict()
    decision = ("CANDIDATA_PENDENTE_APROVACAO_OOS" if ld["candidate"]
                else "NENHUMA_CANDIDATA")
    return EdgeResearch60Report(
        schema="edge_research_phase60_v1",
        universe={"symbols": u.symbols, "n_bars_aligned": u.n,
                  "first": str(u.timestamps[0]) if u.timestamps else None,
                  "last": str(u.timestamps[-1]) if u.timestamps else None},
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "market": "bybit_linear_perp_5m_xs",
                  "cost_bps": REALISTIC_COST * 10000, "max_holding": HOLD_BARS,
                  "execution": "1 posicao; melhor ativo elegivel/ciclo; sem basket",
                  "funding": "~0 (holds ~2h << 8h); modelar por ativo antes de "
                             "promover", "effective_config": eff.to_dict()},
        loop=ld, per_hypothesis=per_hyp, ranking=tuple(rank_rows),
        decision=decision,
        notes=("Cross-sectional scan/ranking, 1 posicao, sem basket; params "
               "PRE-FIXADOS; custos reais; dual-profile; gate 8 criterios por "
               "segmento; VAL so apos DEV; OOS intocado; 1% separado.",
               "Candidata DEV+VAL => pede aprovacao antes do OOS; demo/live "
               "bloqueados; nada promovido.",))


__all__ = ["EdgeResearch60Report", "run_edge_research60"]
