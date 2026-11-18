"""
Strategy Family Research + Market Regime Discovery (FASE 38)
============================================================
Pesquisa OFFLINE e CONSULTIVA: descobre se ha INDICIO de edge por REGIME
de mercado nas estrategias atuais e em 2 familias research-only, sem
overfitting e sem qualquer autorizacao de demo.

Metodo por regime:
    * trade-tagging (PRINCIPAL): 1 backtest completo por familia; cada
      trade marcado pelo regime do candle de ENTRADA; metricas agregadas
      por regime.
    * segmentos (CROSS-CHECK): backtest por trechos contiguos do mesmo
      regime; segmentos curtos => inconclusive; NUNCA base p/ promover.

⚠️  Inviolaveis: demo SEMPRE bloqueada; piso 0.005/RiskEngine/ModeGuard
    intactos; sem ordem/API/secret; sem autoaplicar; sem promover ao
    registry; nunca escolher por PnL isolado; sem prometer performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.market_regime import (
    PRIMARY_REGIMES,
    RegimeClassification,
    classify_regimes,
)

# Thresholds CONSULTIVOS (documentados; nao sao limites de risco).
MIN_TRADES_PER_REGIME = 10
MIN_REGIME_COVERAGE = 0.05
MIN_SEGMENT_LENGTH = 120          # cross-check: trecho curto => inconclusive
MIN_PF_PROMOTE = 1.2
MAX_DD_PROMOTE_PCT = 25.0
MIN_STABILITY_PROMOTE = 0.6


class FamilyResearchError(Exception):
    pass


# Familias avaliadas: atuais + 2 prototipos research-only.
def _family_spec(family: str):
    if family == "trend_pullback_bidirectional":
        from crypto_trading_bot.strategies\
            .trend_pullback_bidirectional_strategy import (
                build_trend_pullback_bidirectional_spec as b)
        return b(), False
    if family == "volatility_breakout":
        from crypto_trading_bot.strategies.volatility_breakout_strategy \
            import build_volatility_breakout_spec as b
        return b(), False
    if family == "mean_reversion_research":
        from crypto_trading_bot.strategies.mean_reversion_strategy import (
            build_mean_reversion_spec as b)
        return b(), True
    if family == "volatility_contraction_expansion_research":
        from crypto_trading_bot.strategies\
            .volatility_contraction_expansion_strategy import (
                build_volatility_contraction_expansion_spec as b)
        return b(), True
    if family == "range_mean_reversion_vwap_bollinger_research":
        from crypto_trading_bot.strategies\
            .range_mean_reversion_vwap_bollinger_strategy import (
                build_range_mean_reversion_vwap_bollinger_spec as b)
        return b(), True
    raise FamilyResearchError(f"familia desconhecida: {family!r}")


DEFAULT_FAMILIES: Tuple[str, ...] = (
    "trend_pullback_bidirectional",
    "volatility_breakout",
    "mean_reversion_research",
    "volatility_contraction_expansion_research",
)


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeMetrics:
    regime: str
    trades: int
    win_rate: float
    profit_factor: Optional[float]
    expectancy_usd: float
    total_pnl_usd: float
    max_drawdown_pct: float
    payoff: Optional[float]
    coverage: float
    sample_sufficient: bool
    source: str = "trade_tagging"      # trade_tagging | segment_crosscheck
    inconclusive: bool = False

    def to_dict(self) -> dict:
        return {
            "regime": self.regime, "trades": self.trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": self.profit_factor,
            "expectancy_usd": round(self.expectancy_usd, 6),
            "total_pnl_usd": round(self.total_pnl_usd, 6),
            "max_drawdown_pct": round(self.max_drawdown_pct, 6),
            "payoff": self.payoff, "coverage": round(self.coverage, 6),
            "sample_sufficient": self.sample_sufficient,
            "source": self.source, "inconclusive": self.inconclusive,
        }


@dataclass(frozen=True)
class FamilyWalkForward:
    in_sample_pf: Optional[float]
    out_of_sample_pf: Optional[float]
    stability: Optional[float]
    overfitting_warning: bool
    inconclusive: bool

    def to_dict(self) -> dict:
        return {
            "in_sample_pf": self.in_sample_pf,
            "out_of_sample_pf": self.out_of_sample_pf,
            "stability": self.stability,
            "overfitting_warning": self.overfitting_warning,
            "inconclusive": self.inconclusive,
        }


@dataclass(frozen=True)
class FamilyRegimeReport:
    family: str
    is_prototype: bool
    overall: RegimeMetrics
    overall_blocked_reasons: Mapping[str, int]
    per_regime_tagging: Tuple[RegimeMetrics, ...]
    per_regime_segments: Tuple[RegimeMetrics, ...]
    walk_forward: FamilyWalkForward
    cost_realistic_pnl_usd: Optional[float]
    recommendation: str
    recommendation_detail: str
    best_regime: Optional[str]
    demo_authorized: bool          # SEMPRE False
    demo_block_reason: str

    def to_dict(self) -> dict:
        return {
            "family": self.family, "is_prototype": self.is_prototype,
            "overall": self.overall.to_dict(),
            "overall_blocked_reasons": dict(self.overall_blocked_reasons),
            "per_regime_tagging": [m.to_dict()
                                   for m in self.per_regime_tagging],
            "per_regime_segments": [m.to_dict()
                                    for m in self.per_regime_segments],
            "walk_forward": self.walk_forward.to_dict(),
            "cost_realistic_pnl_usd": self.cost_realistic_pnl_usd,
            "recommendation": self.recommendation,
            "recommendation_detail": self.recommendation_detail,
            "best_regime": self.best_regime,
            "demo_authorized": self.demo_authorized,
            "demo_block_reason": self.demo_block_reason,
        }


@dataclass(frozen=True)
class FamilyResearchReport:
    schema: str = "strategy_family_research_v1"
    symbol: str = ""
    timeframe: str = ""
    rows: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    data_source: str = "unknown"
    synthetic_warning: bool = False
    regime_distribution: Mapping[str, float] = field(default_factory=dict)
    regime_counts: Mapping[str, int] = field(default_factory=dict)
    families: Tuple[FamilyRegimeReport, ...] = field(default_factory=tuple)
    demo_blocked: bool = True       # SEMPRE True
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema, "symbol": self.symbol,
            "timeframe": self.timeframe, "rows": self.rows,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "data_source": self.data_source,
            "synthetic_warning": self.synthetic_warning,
            "regime_distribution": {
                k: round(v, 6) for k, v in self.regime_distribution.items()},
            "regime_counts": dict(self.regime_counts),
            "families": [f.to_dict() for f in self.families],
            "demo_blocked": self.demo_blocked,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# Metricas a partir de um subconjunto de trades (trade-tagging)
# --------------------------------------------------------------------------

def _metrics_from_trades(
    trades: Sequence, *, regime: str, initial_capital: float,
    coverage: float, source: str,
) -> RegimeMetrics:
    closed = [t for t in trades
              if not t.is_open and t.pnl_usd is not None]
    n = len(closed)
    wins = [t.pnl_usd for t in closed if t.pnl_usd > 0]
    losses = [t.pnl_usd for t in closed if t.pnl_usd <= 0]
    gross_w = sum(wins)
    gross_l = sum(losses)
    total = sum(t.pnl_usd for t in closed)
    pf = (round(gross_w / abs(gross_l), 4) if gross_l < 0 else None)
    expectancy = total / n if n else 0.0
    win_rate = len(wins) / n * 100.0 if n else 0.0
    avg_win = gross_w / len(wins) if wins else 0.0
    avg_loss = gross_l / len(losses) if losses else 0.0
    payoff = (round(avg_win / abs(avg_loss), 4) if avg_loss < 0 else None)
    # Drawdown do subconjunto (cumulativo por ordem de entrada).
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for t in sorted(closed, key=lambda x: x.entry_time):
        cum += t.pnl_usd
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    max_dd_pct = (mdd / initial_capital * 100.0) if initial_capital else 0.0
    sample_sufficient = (n >= MIN_TRADES_PER_REGIME
                         and coverage >= MIN_REGIME_COVERAGE)
    return RegimeMetrics(
        regime=regime, trades=n, win_rate=win_rate, profit_factor=pf,
        expectancy_usd=expectancy, total_pnl_usd=total,
        max_drawdown_pct=max_dd_pct, payoff=payoff, coverage=coverage,
        sample_sufficient=sample_sufficient, source=source,
        inconclusive=not sample_sufficient)


# --------------------------------------------------------------------------
# Backtest helper (precompute O(n))
# --------------------------------------------------------------------------

def _run_backtest(spec, candles, *, capital, min_candles, symbol,
                  cost_config=None):
    from crypto_trading_bot.backtesting import BacktestEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.risk.risk_engine import RiskEngine
    engine = BacktestEngine(
        strategy=spec.factory(dict(spec.default_config)),
        risk_engine=RiskEngine(initial_capital=capital),
        feature_engine=FeatureEngine(), initial_capital=capital,
        min_candles=min_candles, symbol=symbol,
        execution_cost_config=cost_config)
    return engine.run(candles, precompute_features=True)


def _walk_forward(spec, candles, *, capital, min_candles, symbol,
                  n_folds) -> FamilyWalkForward:
    from crypto_trading_bot.research.strategy_parameter_advisor import (
        detect_overfitting, stability_score,
    )
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    try:
        ev = evaluate_strategy(
            spec=spec, candles=list(candles), initial_capital=capital,
            min_candles=min_candles, symbol=symbol,
            walk_forward_n_folds=n_folds, precompute_features=True)
    except Exception:  # noqa: BLE001
        return FamilyWalkForward(None, None, None, False, True)
    in_pf = getattr(ev.single_report, "profit_factor", None)
    test_pfs = []
    test_with_trades = 0
    folds = ev.wf_fold_results or ()
    for f in folds:
        if int(getattr(f.test_report, "total_trades", 0) or 0) > 0:
            test_with_trades += 1
            pf = getattr(f.test_report, "profit_factor", None)
            if pf is not None:
                test_pfs.append(float(pf))
    out_pf = round(sum(test_pfs) / len(test_pfs), 4) if test_pfs else None
    inconclusive = out_pf is None or test_with_trades < max(2, n_folds // 2)
    return FamilyWalkForward(
        in_sample_pf=in_pf, out_of_sample_pf=out_pf,
        stability=stability_score(in_pf, out_pf),
        overfitting_warning=detect_overfitting(in_pf, out_pf),
        inconclusive=inconclusive)


# --------------------------------------------------------------------------
# Recomendacao por familia (consultiva; demo SEMPRE bloqueada)
# --------------------------------------------------------------------------

def _recommend_family(
    per_regime: Sequence[RegimeMetrics], wf: FamilyWalkForward,
    *, real_dataset: bool,
) -> Tuple[str, str, Optional[str], bool, str]:
    """(recommendation, detail, best_regime, demo_gate_satisfied,
    demo_block_reason)."""
    # Regime ROBUSTO p/ promover: amostra suficiente + PF/exp/dd + WF.
    promotable = [
        m for m in per_regime
        if m.sample_sufficient and m.profit_factor is not None
        and m.profit_factor >= MIN_PF_PROMOTE
        and m.expectancy_usd > 0
        and m.max_drawdown_pct >= -MAX_DD_PROMOTE_PCT
    ]
    wf_ok = (not wf.inconclusive and not wf.overfitting_warning
             and wf.stability is not None
             and wf.stability >= MIN_STABILITY_PROMOTE)

    if promotable and wf_ok:
        best = max(promotable, key=lambda m: (m.profit_factor or 0.0,
                                              m.expectancy_usd))
        gate = real_dataset
        detail = (
            f"edge ROBUSTO no regime '{best.regime}' (PF={best.profit_factor}"
            f", exp={round(best.expectancy_usd, 4)}, amostra "
            f"{best.trades}) E walk-forward estavel (stability="
            f"{wf.stability}, overfit={wf.overfitting_warning}). Candidata "
            "a FASE 37.4 (calibracao). CONSULTIVO; NUNCA direto a demo.")
        return ("promover_para_calibracao", detail, best.regime, gate,
                _block_reason(gate))

    # Indicio fraco: algum regime com expectancy>0 mas inconclusivo/WF fraco.
    weak = [m for m in per_regime
            if m.trades > 0 and m.expectancy_usd > 0]
    if weak:
        wr = sorted(weak, key=lambda m: -m.expectancy_usd)[0]
        detail = (
            f"indicio em '{wr.regime}' (exp={round(wr.expectancy_usd, 4)}, "
            f"amostra {wr.trades}, suficiente={wr.sample_sufficient}), mas "
            "walk-forward inconclusivo/instavel ou amostra pequena. "
            "CONTINUAR PESQUISA (mais dados/folds); nao promover.")
        return ("continuar_pesquisa", detail, wr.regime, False,
                _block_reason(False))

    return ("rejeitar_familia",
            "sem edge consistente em nenhum regime (expectancy<=0 / PF<1). "
            "Nao promover; nao operar como esta.",
            None, False, _block_reason(False))


def _block_reason(gate: bool) -> str:
    if gate:
        return ("criterios de promocao atendidos, porem CONSULTIVO: demo "
                "permanece BLOQUEADA ate gates + V1-V12 + readiness + "
                "decisao humana. Promocao e p/ CALIBRACAO, nao p/ demo.")
    return ("demo BLOQUEADA: sem edge robusto/estavel suficiente (e mesmo "
            "se houvesse, autorizacao e manual/gated).")


# --------------------------------------------------------------------------
# Orquestracao por familia
# --------------------------------------------------------------------------

def research_family(
    family: str, candles: Sequence, rc: RegimeClassification, *,
    capital: float, min_candles: int, symbol: str, wf_folds: int,
    cost_config, run_segments: bool, real_dataset: bool = True,
    progress=None,
) -> FamilyRegimeReport:
    spec, is_proto = _family_spec(family)

    def _p(msg):
        if progress is not None:
            try:
                progress(f"[{family}] {msg}")
            except Exception:  # noqa: BLE001
                pass

    _p("backtest (trade-tagging)")
    rep = _run_backtest(spec, candles, capital=capital,
                        min_candles=min_candles, symbol=symbol)
    overall = _metrics_from_trades(
        rep.trades, regime="ALL", initial_capital=capital, coverage=1.0,
        source="trade_tagging")

    # Trade-tagging por regime: marca trade pelo regime na ENTRADA.
    idx_to_regime = {lab.index: lab.primary_regime for lab in rc.labels}
    by_regime: Dict[str, List] = {}
    for t in rep.trades:
        reg = idx_to_regime.get(int(t.entry_candle_idx), "warmup_unlabeled")
        by_regime.setdefault(reg, []).append(t)
    tagging: List[RegimeMetrics] = []
    for reg in sorted(by_regime):
        cov = rc.coverage.get(reg, 0.0)
        tagging.append(_metrics_from_trades(
            by_regime[reg], regime=reg, initial_capital=capital,
            coverage=cov, source="trade_tagging"))

    # Segmentos (CROSS-CHECK): so regimes com tagging suficiente; trechos
    # longos o bastante; curtos => inconclusive. NUNCA base p/ promover.
    segments: List[RegimeMetrics] = []
    if run_segments:
        _p("segmentos (cross-check)")
        suff_regimes = {m.regime for m in tagging if m.sample_sufficient}
        for reg in sorted(suff_regimes):
            seg_trades = []
            long_segs = [s for s in rc.segments
                         if s.primary_regime == reg
                         and s.length >= MIN_SEGMENT_LENGTH]
            for s in long_segs[:5]:   # limita custo
                sub = list(candles[s.start_index:s.end_index + 1])
                if len(sub) < min_candles + 5:
                    continue
                sub_rep = _run_backtest(
                    spec, sub, capital=capital, min_candles=min_candles,
                    symbol=symbol)
                seg_trades.extend(sub_rep.trades)
            cov = rc.coverage.get(reg, 0.0)
            m = _metrics_from_trades(
                seg_trades, regime=reg, initial_capital=capital,
                coverage=cov, source="segment_crosscheck")
            segments.append(m)

    _p(f"walk-forward ({wf_folds} folds)")
    wf = _walk_forward(spec, candles, capital=capital,
                       min_candles=min_candles, symbol=symbol,
                       n_folds=wf_folds)

    cost_pnl = None
    if cost_config is not None:
        _p("custo (realistic_research)")
        cost_rep = _run_backtest(
            spec, candles, capital=capital, min_candles=min_candles,
            symbol=symbol, cost_config=cost_config)
        cost_pnl = round(float(cost_rep.total_pnl_usd), 6)

    rec, detail, best_regime, gate, block = _recommend_family(
        tagging, wf, real_dataset=real_dataset)

    return FamilyRegimeReport(
        family=family, is_prototype=is_proto, overall=overall,
        overall_blocked_reasons=dict(
            getattr(rep, "risk_blocked_reasons", {}) or {}),
        per_regime_tagging=tuple(tagging),
        per_regime_segments=tuple(segments), walk_forward=wf,
        cost_realistic_pnl_usd=cost_pnl, recommendation=rec,
        recommendation_detail=detail, best_regime=best_regime,
        demo_authorized=False, demo_block_reason=block)


def run_family_research(
    candles: Sequence, *, families: Optional[Sequence[str]] = None,
    capital: float = 5000.0, min_candles: int = 60, symbol: str = "BTCUSDT",
    timeframe: str = "15m", data_source: str = "csv",
    regime_lookback: int = 96, wf_folds: int = 5,
    cost_config=None, run_segments: bool = True, progress=None,
) -> FamilyResearchReport:
    if not candles:
        raise FamilyResearchError("nenhum candle fornecido")
    fams = list(families) if families else list(DEFAULT_FAMILIES)
    real_dataset = str(data_source).lower().startswith(("real", "csv"))

    if progress:
        progress("classificando regimes")
    rc = classify_regimes(candles, lookback=regime_lookback)

    # Default cost: realistic_research (rotulado) se nada informado.
    if cost_config is None:
        from crypto_trading_bot.research.calibration_costs import (
            build_cost_scenario,
        )
        cost_config = build_cost_scenario("realistic_research").config

    blocks: List[FamilyRegimeReport] = []
    for fam in fams:
        blocks.append(research_family(
            fam, candles, rc, capital=capital, min_candles=min_candles,
            symbol=symbol, wf_folds=wf_folds, cost_config=cost_config,
            run_segments=run_segments, real_dataset=real_dataset,
            progress=progress))

    synthetic = not real_dataset
    notes = [
        "demo BLOQUEADA por padrao: relatorio CONSULTIVO; NUNCA autoriza "
        "demo. 'promover_para_calibracao' encaminha p/ FASE 37.4, nao p/ "
        "demo.",
        "prototipos research-only (mean_reversion, vol_contraction_"
        "expansion) NAO estao no registry operacional e NAO sao usados "
        "por demo/session runner.",
        "regime do candle i usa SOMENTE candles <= i (anti look-ahead). "
        "Segmentos sao apenas cross-check; trechos curtos => inconclusive.",
        "piso 0.005/RiskEngine/ModeGuard intactos; nada autoaplicado.",
    ]
    if synthetic:
        notes.append(
            "dados sinteticos: metricas ILUSTRATIVAS, nao performance real.")

    def _iso(ts):
        if ts is None:
            return None
        from datetime import timezone
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return FamilyResearchReport(
        symbol=symbol, timeframe=timeframe, rows=len(candles),
        first_timestamp=_iso(getattr(candles[0], "timestamp", None)),
        last_timestamp=_iso(getattr(candles[-1], "timestamp", None)),
        data_source=data_source, synthetic_warning=synthetic,
        regime_distribution=dict(rc.coverage),
        regime_counts=dict(rc.coverage_counts),
        families=tuple(blocks), demo_blocked=True, notes=tuple(notes))


__all__ = [
    "DEFAULT_FAMILIES",
    "FamilyRegimeReport",
    "FamilyResearchError",
    "FamilyResearchReport",
    "FamilyWalkForward",
    "RegimeMetrics",
    "research_family",
    "run_family_research",
]
