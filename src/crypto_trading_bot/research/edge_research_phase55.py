"""
Edge Research FASE 55 — roda a agenda de hipoteses NORMAIS CONDICIONADAS pelo
research loop controlado, avaliador REAL via standard_report dual-profile
(Hyro 5k via hyro_challenge_attempts + Trader Padrao 5k via
standard_trader_monthly_close). 0,5% primario + 1% analise separada. DEV; VAL
so se DEV passar; OOS NUNCA avaliado. Reusa _run53 (FASE 53) e o motor existente
(NAO altera core/standard_report).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.edge_research_phase47 import BYBIT_COST_BPS
from crypto_trading_bot.research.edge_research_phase53 import _run53
from crypto_trading_bot.research.effective_config import build_effective_config

# guardrails FASE 55 (complementos do operador) — EXPLICITOS:
MIN_TRADES_DEV = 30          # PF bonito com poucos trades = maquiagem
MIN_ACTIVE_MONTHS = 3        # precisa estar ativo em varios meses
MIN_HYRO_ATTEMPTS = 3        # 'passaria' so com tentativas bem separadas


def _harden(sr: Mapping[str, Any], *, min_trades: int = MIN_TRADES_DEV,
            min_months: int = MIN_ACTIVE_MONTHS,
            min_attempts: int = MIN_HYRO_ATTEMPTS) -> Dict[str, Any]:
    """Endurece o standard_report p/ a DECISAO (mais rigoroso que o base; NAO
    altera o modulo compartilhado): (a) amostra insuficiente (trades<min_trades
    ou meses ativos<min_months) => edge_estatistico NAO aprova; (b) Hyro
    'passaria' exige tentativas reais (total_attempts>=min_attempts) senao
    'fraco_instavel'. Reporta trade_count/meses/estabilidade/tentativas."""
    sr = dict(sr)
    v = dict(sr.get("verdict", {}) or {})
    sm = sr.get("strategy_metrics", {}) or {}
    tb = sr.get("temporal_breakdown", {}) or {}
    att = sr.get("hyro_challenge_attempts", {}) or {}
    n = sm.get("num_trades") or 0
    months = tb.get("months_total") or 0
    sc = tb.get("sign_consistency")
    n_att = att.get("total_attempts") or 0
    sample_ok = n >= min_trades and months >= min_months
    guard = {"num_trades": n, "active_months": months,
             "monthly_sign_consistency": sc, "total_hyro_attempts": n_att,
             "min_trades": min_trades, "min_active_months": min_months,
             "min_hyro_attempts": min_attempts,
             "sample_sufficient": sample_ok}
    if not sample_ok and v.get("edge_estatistico") == "aprovado":
        v["edge_estatistico"] = "rejeitado"
        guard["edge_downgraded_insufficient_sample"] = True
    if v.get("hyro_challenge") == "passaria" and n_att < min_attempts:
        v["hyro_challenge"] = "fraco_instavel"
        guard["hyro_downgraded_few_attempts"] = True
    # reclassifica com a MESMA regra do standard_report
    trader, hyro = v.get("standard_trader"), v.get("hyro_challenge")
    if trader != "aprovado":
        cls = "sem_edge_operacional"
    elif hyro == "passaria":
        cls = "candidata_paper"
    else:
        cls = "edge_possivel_incompativel_com_challenge"
    sr["verdict"] = v
    sr["classification"] = cls
    sr["phase55_sample_guard"] = guard
    return sr


@dataclass(frozen=True)
class EdgeResearch55Report:
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


def run_edge_research55(
    candles_1h: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    operator_store=None, wf_folds: int = 5, progress=None
) -> EdgeResearch55Report:
    from crypto_trading_bot.research.normal_families_phase55 import (
        DETECTORS_55, HOLD_BARS_55)
    from crypto_trading_bot.research.normal_hypotheses_phase55 import (
        proposed_hypotheses_phase55)
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

    setups_by: Dict[str, list] = {}
    for h in proposed_hypotheses_phase55():
        det = DETECTORS_55[h.name]
        if h.name == "breakout_oi_funding_confirmed":
            setups_by[h.name] = det(candles_1h, pf.oi_change, pf.funding_pctile,
                                    params=dict(h.fixed_params))
        else:
            setups_by[h.name] = det(candles_1h, params=dict(h.fixed_params))
        _cb(f"{h.name}: {len(setups_by[h.name])} setups")

    reports: Dict[str, Dict[str, Any]] = {}

    def evaluator(spec, segment):
        # RANKING/DECISAO usam SO 0,5% (primario). O 1% e sensibilidade separada.
        seg_dates = dev if segment == "DEV" else val
        m = _run53(setups_by[spec.name], candles_1h, seg_dates=seg_dates,
                   risk_config=rc05, risk_base_pct=0.005,
                   funding_events=funding_events, wf_folds=wf_folds,
                   min_candles=mc, segment_label=segment, eff=eff,
                   family_id=spec.name, max_holding=HOLD_BARS_55[spec.name])
        hardened = _harden(m["standard_report"])     # guards FASE 55
        reports.setdefault(spec.name, {})[segment] = {"metrics": m,
                                                       "report": hardened}
        return hardened

    _cb("research loop (DEV; VAL so se DEV passar; OOS intocado)")
    loop = run_research_loop(proposed_hypotheses_phase55(), evaluator,
                             progress=progress)

    per_hyp: Dict[str, Any] = {}
    for name, segs in reports.items():
        dev_sr = segs.get("DEV", {}).get("report", {})
        block = {
            "n_setups": len(setups_by.get(name, [])),
            "dev_classification": dev_sr.get("classification"),
            "dev_verdict": dev_sr.get("verdict"),
            "dev_strategy_metrics": dev_sr.get("strategy_metrics"),
            "dev_sample_guard": dev_sr.get("phase55_sample_guard"),
            "dev_hyro_attempts": (dev_sr.get("hyro_challenge_attempts") or {}),
            "dev_monthly_close": dev_sr.get("standard_trader_monthly_close"),
        }
        if "VAL" in segs:
            val_sr = segs["VAL"].get("report", {})
            block["val_classification"] = val_sr.get("classification")
            block["val_verdict"] = val_sr.get("verdict")
            block["val_strategy_metrics"] = val_sr.get("strategy_metrics")
            block["val_sample_guard"] = val_sr.get("phase55_sample_guard")
        # 1% = SENSIBILIDADE SEPARADA (fora do ranking/decisao, que sao 0,5%)
        m1 = _run53(setups_by[name], candles_1h, seg_dates=dev,
                    risk_config=rc1, risk_base_pct=0.01,
                    funding_events=funding_events, wf_folds=None,
                    min_candles=mc, segment_label="DEV", eff=eff,
                    family_id=name, max_holding=HOLD_BARS_55[name])
        block["sensitivity_1pct_separate"] = {
            "note": ("risco 1% — SENSIBILIDADE SEPARADA; NAO entra no ranking "
                     "nem na decisao (primario=0,5%)"),
            "trader_padrao_dev": m1["standard_report"].get(
                "standard_trader_evaluation")}
        per_hyp[name] = block

    ld = loop.to_dict()
    decision = ("CANDIDATA_PENDENTE_APROVACAO_OOS" if ld["candidate"]
                else "NENHUMA_CANDIDATA")

    return EdgeResearch55Report(
        schema="edge_research_phase55_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        segments={"dev": dev, "val": val, "market": "bybit_linear_perp_1h",
                  "cost_bps": BYBIT_COST_BPS,
                  "effective_config": eff.to_dict(),
                  "note": "OOS travado (so DEV+VAL; loop nunca avalia OOS)."},
        loop=ld, per_hypothesis=per_hyp, decision=decision,
        notes=("Agenda NORMAL condicionada (regime/vol/OI/funding) via research "
               "loop; dual-profile (hyro_challenge_attempts + monthly_close). "
               "RANKING/DECISAO = 0,5% (primario); 1% = sensibilidade SEPARADA "
               "(fora do ranking). VAL so apos DEV (binario); OOS intocado.",
               "GUARDS FASE 55: amostra insuficiente (trades<30 ou meses<3) NAO "
               "aprova edge (PF com poucos trades = maquiagem); Hyro 'passaria' "
               "exige >=3 tentativas reais; OI/funding alinhados CAUSAL (asof "
               "por close_time + percentil causal, sem lookahead).",
               "Candidata DEV+VAL => pede aprovacao antes do OOS; demo/live "
               "bloqueados; nada promovido.",))


__all__ = ["EdgeResearch55Report", "run_edge_research55"]
