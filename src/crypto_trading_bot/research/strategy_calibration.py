"""
Strategy Calibration Offline + Cost Realism (FASE 37.4)
=======================================================
Calibra e AVALIA, de forma OFFLINE e controlada, variacoes LIMITADAS e
EXPLICITAS de estrategias usando os backtests corrigidos (FASE 37/.1/.2/
.3) como baseline. Gera recomendacao CONSULTIVA:

    manter | ajustar | rejeitar | bloquear_demo

⚠️  Regras inviolaveis:
    * NAO baixa o piso 0.005 do RiskEngine. O "filtro de stop" desta fase
      (`stop_loss_floor_filter_pct`) eh um FILTRO DE SINAL (rejeita sinal
      doomed ANTES do RiskEngine) — mapeado para o param da estrategia
      `min_stop_loss_pct`; NUNCA altera o piso real.
    * NAO afrouxa RiskEngine/ModeGuard. NAO envia ordem. NAO chama API.
    * NAO autoaplica parametros. O resultado NUNCA autoriza demo.
    * "ajustar" so com estabilidade em walk-forward E sem overfitting.
    * bloquear_demo eh o DEFAULT; demo depende de gates/V1-V12/readiness/
      decisao humana (consultivo).

Reusa: evaluate_strategy (com precompute O(n)), run_walk_forward,
ExecutionCostConfig (via calibration_costs), e os helpers de robustez/
overfitting/estabilidade do strategy_parameter_advisor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.calibration_costs import (
    CostScenario,
    default_cost_sweep,
)

# --------------------------------------------------------------------------
# Thresholds CONSULTIVOS (research; documentados, nao sao limites de risco)
# --------------------------------------------------------------------------
MIN_TRADES_EVALUABLE = 5
MIN_PF_FOR_ADJUST = 1.2
MIN_EXPECTANCY_FOR_ADJUST = 0.0      # > 0
MAX_DD_FOR_ADJUST_PCT = 25.0
MIN_STABILITY_FOR_ADJUST = 0.6       # razao out/in (walk-forward)
MIN_FOLD_CONSISTENCY = 0.6           # fracao de folds com test PF >= 1

# Demo gate (consultivo) — mesmos thresholds; demo NUNCA autorizada aqui.
DEMO_GATE_MIN_OOS_PF = 1.2
DEMO_GATE_MAX_DD_PCT = 25.0


# Estrategias canonicas e quais eixos OFAT cada uma suporta.
_AXIS_STOP_MULT = "stop_atr_multiplier"
_AXIS_RR = "risk_reward_ratio"
_AXIS_STOP_FILTER = "stop_loss_floor_filter_pct"  # -> config min_stop_loss_pct

_OFAT_STOP_MULT = (1.5, 1.75, 2.0, 2.5)
_OFAT_RR = (1.5, 2.0, 2.5, 3.0)
_OFAT_STOP_FILTER = (None, 0.005)     # off | filtro no nivel do piso

# Eixos suportados por estrategia (canonica -> builder + axes).
_STRATEGY_SUPPORT = {
    "trend_pullback_bidirectional": (
        _AXIS_STOP_MULT, _AXIS_RR, _AXIS_STOP_FILTER),
    "trend_pullback": (_AXIS_STOP_MULT, _AXIS_RR),
    "volatility_breakout": (_AXIS_STOP_MULT, _AXIS_RR),
}


class CalibrationError(Exception):
    """Erro de configuracao da calibracao."""


# --------------------------------------------------------------------------
# Dataclasses de resultado
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VariantMetrics:
    total_trades: int
    win_rate: float
    profit_factor: Optional[float]
    expectancy_usd: float
    total_pnl_usd: float
    max_drawdown_pct: float
    payoff: Optional[float]
    risk_blocked_count: int
    blocked_reasons_summary: Mapping[str, int]

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "expectancy_usd": round(self.expectancy_usd, 6),
            "total_pnl_usd": round(self.total_pnl_usd, 6),
            "max_drawdown_pct": round(self.max_drawdown_pct, 6),
            "payoff": self.payoff,
            "risk_blocked_count": self.risk_blocked_count,
            "blocked_reasons_summary": dict(self.blocked_reasons_summary),
        }


@dataclass(frozen=True)
class VariantResult:
    name: str                 # "baseline" | "stop_atr_multiplier=2.0" ...
    axis: str                 # "baseline" | eixo OFAT
    value: Any
    config_override: Mapping[str, Any]
    metrics: VariantMetrics

    def to_dict(self) -> dict:
        return {
            "name": self.name, "axis": self.axis, "value": self.value,
            "config_override": dict(self.config_override),
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class CostSweepRow:
    variant_name: str
    scenario: str
    is_research_illustrative: bool
    metrics: VariantMetrics

    def to_dict(self) -> dict:
        return {
            "variant_name": self.variant_name,
            "scenario": self.scenario,
            "is_research_illustrative": self.is_research_illustrative,
            "metrics": self.metrics.to_dict(),
        }


@dataclass(frozen=True)
class WalkForwardEval:
    variant_name: str
    n_folds: int
    in_sample_pf: Optional[float]
    out_of_sample_pf: Optional[float]      # media dos folds de teste
    stability: Optional[float]
    fold_consistency: Optional[float]      # fracao de folds test PF>=1
    overfitting_warning: bool
    inconclusive: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "variant_name": self.variant_name,
            "n_folds": self.n_folds,
            "in_sample_pf": self.in_sample_pf,
            "out_of_sample_pf": self.out_of_sample_pf,
            "stability": self.stability,
            "fold_consistency": self.fold_consistency,
            "overfitting_warning": self.overfitting_warning,
            "inconclusive": self.inconclusive,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StrategyCalibration:
    strategy: str
    is_candidate: bool
    baseline: VariantResult
    variants: Tuple[VariantResult, ...]
    selected_for_followup: Tuple[str, ...]
    cost_sweep: Tuple[CostSweepRow, ...]
    walk_forward: Tuple[WalkForwardEval, ...]
    recommendation: str       # manter|ajustar|rejeitar|bloquear_demo|manual_review
    recommendation_detail: str
    suggested_config: Optional[Mapping[str, Any]]
    demo_gate_satisfied: bool
    demo_authorized: bool     # SEMPRE False
    demo_block_reason: str

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "is_candidate": self.is_candidate,
            "baseline": self.baseline.to_dict(),
            "variants": [v.to_dict() for v in self.variants],
            "selected_for_followup": list(self.selected_for_followup),
            "cost_sweep": [r.to_dict() for r in self.cost_sweep],
            "walk_forward": [w.to_dict() for w in self.walk_forward],
            "recommendation": self.recommendation,
            "recommendation_detail": self.recommendation_detail,
            "suggested_config": (
                dict(self.suggested_config)
                if self.suggested_config is not None else None),
            "demo_gate_satisfied": self.demo_gate_satisfied,
            "demo_authorized": self.demo_authorized,
            "demo_block_reason": self.demo_block_reason,
        }


@dataclass(frozen=True)
class CalibrationReport:
    schema: str = "strategy_calibration_v1"
    symbol: str = ""
    timeframe: str = ""
    rows: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    data_source: str = "unknown"           # real | synthetic | csv
    synthetic_warning: bool = False
    strategies: Tuple[StrategyCalibration, ...] = field(
        default_factory=tuple)
    demo_blocked: bool = True               # SEMPRE True (consultivo)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "rows": self.rows,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "data_source": self.data_source,
            "synthetic_warning": self.synthetic_warning,
            "strategies": [s.to_dict() for s in self.strategies],
            "demo_blocked": self.demo_blocked,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# Builders OFAT (um-fator-por-vez em torno do baseline)
# --------------------------------------------------------------------------

def build_ofat_variants(strategy: str) -> List[Tuple[str, str, Any, dict]]:
    """Retorna [(name, axis, value, config_override), ...] OFAT.

    O baseline NAO entra aqui (avaliado separadamente). Cada variante muda
    UM parametro em relacao ao default. O filtro de stop usa o nome
    explicito `stop_loss_floor_filter_pct` e mapeia para o param da
    estrategia `min_stop_loss_pct` (filtro de SINAL, nunca o piso real).
    """
    axes = _STRATEGY_SUPPORT.get(strategy)
    if axes is None:
        raise CalibrationError(
            f"strategy desconhecida p/ calibracao: {strategy!r}. "
            f"Aceitas: {sorted(_STRATEGY_SUPPORT)}")
    out: List[Tuple[str, str, Any, dict]] = []
    if _AXIS_STOP_MULT in axes:
        for v in _OFAT_STOP_MULT:
            out.append((f"{_AXIS_STOP_MULT}={v}", _AXIS_STOP_MULT, v,
                        {"stop_atr_multiplier": v}))
    if _AXIS_RR in axes:
        for v in _OFAT_RR:
            out.append((f"{_AXIS_RR}={v}", _AXIS_RR, v,
                        {"risk_reward_ratio": v}))
    if _AXIS_STOP_FILTER in axes:
        for v in _OFAT_STOP_FILTER:
            label = f"{_AXIS_STOP_FILTER}={'off' if v is None else v}"
            # mapeia para o param da estrategia (filtro de sinal).
            override = {} if v is None else {"min_stop_loss_pct": v}
            out.append((label, _AXIS_STOP_FILTER, v, override))
    return out


# --------------------------------------------------------------------------
# Avaliacao
# --------------------------------------------------------------------------

def _payoff(avg_win: float, avg_loss: float) -> Optional[float]:
    if avg_loss is None or avg_loss >= 0:
        return None
    if avg_win <= 0:
        return 0.0
    return round(avg_win / abs(avg_loss), 4)


def _metrics_from_report(rep) -> VariantMetrics:
    return VariantMetrics(
        total_trades=int(getattr(rep, "total_trades", 0) or 0),
        win_rate=float(getattr(rep, "win_rate", 0.0) or 0.0),
        profit_factor=getattr(rep, "profit_factor", None),
        expectancy_usd=float(getattr(rep, "expectancy_usd", 0.0) or 0.0),
        total_pnl_usd=float(getattr(rep, "total_pnl_usd", 0.0) or 0.0),
        max_drawdown_pct=float(getattr(rep, "max_drawdown_pct", 0.0) or 0.0),
        payoff=_payoff(
            float(getattr(rep, "avg_win_usd", 0.0) or 0.0),
            float(getattr(rep, "avg_loss_usd", 0.0) or 0.0)),
        risk_blocked_count=int(getattr(rep, "risk_blocked_count", 0) or 0),
        blocked_reasons_summary=dict(
            getattr(rep, "risk_blocked_reasons", {}) or {}),
    )


def _spec_for(strategy: str):
    if strategy == "trend_pullback_bidirectional":
        from crypto_trading_bot.strategies\
            .trend_pullback_bidirectional_strategy import (
                build_trend_pullback_bidirectional_spec as b)
        return b()
    if strategy == "trend_pullback":
        from crypto_trading_bot.strategies.trend_pullback_strategy import (
            build_trend_pullback_spec as b)
        return b()
    if strategy == "volatility_breakout":
        from crypto_trading_bot.strategies\
            .volatility_breakout_strategy import (
                build_volatility_breakout_spec as b)
        return b()
    raise CalibrationError(f"strategy desconhecida: {strategy!r}")


def _evaluate(spec, candles, config_override, *, capital, min_candles,
              symbol, cost_config=None, precompute=True):
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    ev = evaluate_strategy(
        spec=spec, candles=list(candles),
        config_override=dict(config_override),
        initial_capital=capital, min_candles=min_candles, symbol=symbol,
        execution_cost_config=cost_config,
        precompute_features=precompute,
    )
    return ev.single_report


# --------------------------------------------------------------------------
# Selecao deterministica para follow-up (custos + walk-forward)
# --------------------------------------------------------------------------

def _score(m: VariantMetrics) -> float:
    """Score deterministico PRE-REGISTRADO (nao PnL isolado): PF acima de
    1, expectancy positiva e drawdown baixo. Empata por nome depois."""
    pf = m.profit_factor if m.profit_factor is not None else 0.0
    score = (pf - 1.0) * 2.0
    score += 1.0 if m.expectancy_usd > 0 else -1.0
    score -= max(0.0, m.max_drawdown_pct) / 100.0
    if m.total_trades < MIN_TRADES_EVALUABLE:
        score -= 5.0
    return round(score, 6)


def _dominates(a: VariantMetrics, b: VariantMetrics) -> bool:
    """a domina b se >= em (PF, expectancy, -drawdown) e > em ao menos um."""
    pa = a.profit_factor if a.profit_factor is not None else 0.0
    pb = b.profit_factor if b.profit_factor is not None else 0.0
    ge = (pa >= pb and a.expectancy_usd >= b.expectancy_usd
          and a.max_drawdown_pct <= b.max_drawdown_pct)
    gt = (pa > pb or a.expectancy_usd > b.expectancy_usd
          or a.max_drawdown_pct < b.max_drawdown_pct)
    return ge and gt


def select_for_followup(
    baseline: VariantResult, variants: Sequence[VariantResult],
    *, top_n: int = 3,
) -> List[str]:
    """Selecao DETERMINISTICA (nao subjetiva): baseline SEMPRE +
    variantes nao-dominadas, limitado a top_n por _score (tie-break
    deterministico). Nao escolhe por PnL isolado."""
    names = ["baseline"]
    pool = list(variants)
    non_dominated = [
        v for v in pool
        if not any(_dominates(o.metrics, v.metrics) for o in pool
                   if o is not v)
    ]
    ranked = sorted(
        non_dominated,
        key=lambda v: (-_score(v.metrics), -v.metrics.expectancy_usd,
                       v.metrics.max_drawdown_pct, v.name),
    )
    for v in ranked:
        if len(names) >= top_n + 1:
            break
        names.append(v.name)
    return names


# --------------------------------------------------------------------------
# Walk-forward por variante
# --------------------------------------------------------------------------

def _walk_forward_eval(
    spec, candles, variant: VariantResult, *, n_folds, capital,
    min_candles, symbol, cost_config, precompute,
) -> WalkForwardEval:
    from crypto_trading_bot.research.strategy_parameter_advisor import (
        detect_overfitting, stability_score,
    )
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    try:
        ev = evaluate_strategy(
            spec=spec, candles=list(candles),
            config_override=dict(variant.config_override),
            initial_capital=capital, min_candles=min_candles, symbol=symbol,
            execution_cost_config=cost_config,
            walk_forward_n_folds=n_folds,
            precompute_features=precompute,
        )
    except Exception as e:  # noqa: BLE001
        return WalkForwardEval(
            variant_name=variant.name, n_folds=n_folds,
            in_sample_pf=None, out_of_sample_pf=None, stability=None,
            fold_consistency=None, overfitting_warning=False,
            inconclusive=True, reason=f"wf_error:{type(e).__name__}")

    in_pf = getattr(ev.single_report, "profit_factor", None)
    test_pfs: List[float] = []
    test_with_trades = 0
    folds = ev.wf_fold_results or ()
    for f in folds:
        tr = f.test_report
        if int(getattr(tr, "total_trades", 0) or 0) > 0:
            test_with_trades += 1
            pf = getattr(tr, "profit_factor", None)
            if pf is not None:
                test_pfs.append(float(pf))
    out_pf = round(sum(test_pfs) / len(test_pfs), 4) if test_pfs else None
    fold_consistency = (
        round(sum(1 for pf in test_pfs if pf >= 1.0) / len(folds), 4)
        if folds else None)
    inconclusive = (out_pf is None or test_with_trades < max(2, n_folds // 2))
    return WalkForwardEval(
        variant_name=variant.name, n_folds=n_folds,
        in_sample_pf=in_pf, out_of_sample_pf=out_pf,
        stability=stability_score(in_pf, out_pf),
        fold_consistency=fold_consistency,
        overfitting_warning=detect_overfitting(in_pf, out_pf),
        inconclusive=inconclusive,
        reason="ok" if not inconclusive else "insufficient_oos_trades",
    )


# --------------------------------------------------------------------------
# Recomendacao + demo gate (consultivo; demo SEMPRE bloqueada)
# --------------------------------------------------------------------------

def _variant_viable_for_adjust(
    baseline: VariantResult, cand: VariantResult,
    wf: Optional[WalkForwardEval],
) -> bool:
    m = cand.metrics
    if m.total_trades < MIN_TRADES_EVALUABLE:
        return False
    pf = m.profit_factor if m.profit_factor is not None else 0.0
    if not (pf >= MIN_PF_FOR_ADJUST
            and m.expectancy_usd > MIN_EXPECTANCY_FOR_ADJUST
            and m.max_drawdown_pct <= MAX_DD_FOR_ADJUST_PCT):
        return False
    if not _dominates(m, baseline.metrics):
        return False
    # "ajustar" EXIGE walk-forward estavel e sem overfitting.
    if wf is None or wf.inconclusive or wf.overfitting_warning:
        return False
    if wf.stability is None or wf.stability < MIN_STABILITY_FOR_ADJUST:
        return False
    if wf.fold_consistency is None or \
            wf.fold_consistency < MIN_FOLD_CONSISTENCY:
        return False
    return True


def _recommend(
    strategy: str, baseline: VariantResult,
    variants: Sequence[VariantResult],
    wf_by_name: Mapping[str, WalkForwardEval], *, real_dataset: bool,
) -> Tuple[str, str, Optional[dict], bool, str]:
    """Retorna (recommendation, detail, suggested_config,
    demo_gate_satisfied, demo_block_reason)."""
    # Candidatas viaveis p/ ajustar (dominam baseline + WF estavel).
    viable = [
        v for v in variants
        if _variant_viable_for_adjust(baseline, v, wf_by_name.get(v.name))
    ]
    base_exp = baseline.metrics.expectancy_usd
    base_pf = baseline.metrics.profit_factor or 0.0

    if viable:
        best = max(viable, key=lambda v: _score(v.metrics))
        wf = wf_by_name.get(best.name)
        sat = _demo_gate(best, wf, real_dataset=real_dataset)
        detail = (
            f"variante '{best.name}' domina o baseline (PF/expectancy/"
            f"drawdown) E estavel em walk-forward (stability="
            f"{wf.stability}, overfitting={wf.overfitting_warning}). "
            "Sugestao CONSULTIVA; exige nova validacao + decisao humana; "
            "NUNCA autoaplicada.")
        return ("ajustar", detail, dict(best.config_override), sat,
                _demo_block_reason(sat))

    # Sem variante viavel: manter (baseline ja ok) vs rejeitar (ruim).
    baseline_ok = (base_pf >= MIN_PF_FOR_ADJUST
                   and base_exp > MIN_EXPECTANCY_FOR_ADJUST)
    # Houve variante que dominou baseline porem WF inconclusivo/overfit?
    dominators_wf_failed = any(
        _dominates(v.metrics, baseline.metrics)
        and (wf_by_name.get(v.name) is None
             or wf_by_name[v.name].inconclusive
             or wf_by_name[v.name].overfitting_warning)
        for v in variants
    )
    if baseline_ok:
        return ("manter",
                "baseline ja atende PF/expectancy e nenhuma variante o "
                "supera com robustez de walk-forward.",
                None, False, _demo_block_reason(False))
    if dominators_wf_failed:
        return ("manual_review",
                "ha variante(s) que superam o baseline no backtest, mas o "
                "walk-forward foi inconclusivo ou indicou overfitting. "
                "NAO ajustar; revisar manualmente (mais dados/folds).",
                None, False, _demo_block_reason(False))
    return ("rejeitar",
            "baseline com expectancy/PF insuficientes e nenhuma variante "
            "viavel e estavel. Nao operar esta estrategia como esta.",
            None, False, _demo_block_reason(False))


def _demo_gate(
    cand: VariantResult, wf: Optional[WalkForwardEval], *,
    real_dataset: bool,
) -> bool:
    """Criterios do gate de demo (CONSULTIVO). Mesmo satisfeito, a demo
    NUNCA eh autorizada por este modulo."""
    if not real_dataset:
        return False
    if wf is None or wf.inconclusive or wf.overfitting_warning:
        return False
    if wf.out_of_sample_pf is None or \
            wf.out_of_sample_pf < DEMO_GATE_MIN_OOS_PF:
        return False
    m = cand.metrics
    return (m.expectancy_usd > 0
            and m.max_drawdown_pct <= DEMO_GATE_MAX_DD_PCT)


def _demo_block_reason(gate_satisfied: bool) -> str:
    if gate_satisfied:
        return (
            "demo_gate_satisfied porem CONSULTIVO: demo permanece BLOQUEADA "
            "ate gates operacionais + V1-V12 + readiness + decisao humana.")
    return (
        "demo BLOQUEADA: criterios de robustez/walk-forward nao satisfeitos "
        "(e mesmo se fossem, autorizacao e manual/gated).")


# --------------------------------------------------------------------------
# Orquestracao por estrategia e geral
# --------------------------------------------------------------------------

def calibrate_strategy(
    strategy: str, candles: Sequence, *, is_candidate: bool,
    capital: float, min_candles: int, symbol: str,
    cost_scenarios: Sequence[CostScenario], walk_forward_folds: int,
    top_n_followup: int, precompute: bool, real_dataset: bool,
    progress: Optional[Any] = None,
) -> StrategyCalibration:
    def _p(msg: str) -> None:
        if progress is not None:
            try:
                progress(f"[{strategy}] {msg}")
            except Exception:  # noqa: BLE001
                pass

    spec = _spec_for(strategy)

    # 1) Baseline (default, zero-cost).
    _p("baseline")
    base_rep = _evaluate(
        spec, candles, {}, capital=capital, min_candles=min_candles,
        symbol=symbol, cost_config=None, precompute=precompute)
    baseline = VariantResult(
        name="baseline", axis="baseline", value=None,
        config_override={}, metrics=_metrics_from_report(base_rep))

    # 2) Variantes OFAT (zero-cost).
    variants: List[VariantResult] = []
    _ofat = build_ofat_variants(strategy)
    for _vi, (name, axis, value, override) in enumerate(_ofat, start=1):
        _p(f"variante {_vi}/{len(_ofat)}: {name}")
        rep = _evaluate(
            spec, candles, override, capital=capital,
            min_candles=min_candles, symbol=symbol, cost_config=None,
            precompute=precompute)
        variants.append(VariantResult(
            name=name, axis=axis, value=value, config_override=override,
            metrics=_metrics_from_report(rep)))

    # 3) Selecao deterministica para follow-up.
    selected = select_for_followup(baseline, variants, top_n=top_n_followup)
    sel_set = {s: (baseline if s == "baseline"
                   else next(v for v in variants if v.name == s))
               for s in selected}

    # 4) Cost sweep nas selecionadas.
    _p(f"cost sweep ({len(selected)} variantes x {len(cost_scenarios)})")
    cost_rows: List[CostSweepRow] = []
    for sname, vres in sel_set.items():
        for sc in cost_scenarios:
            rep = _evaluate(
                spec, candles, vres.config_override, capital=capital,
                min_candles=min_candles, symbol=symbol,
                cost_config=sc.config, precompute=precompute)
            cost_rows.append(CostSweepRow(
                variant_name=sname, scenario=sc.label,
                is_research_illustrative=sc.is_research_illustrative,
                metrics=_metrics_from_report(rep)))

    # 5) Walk-forward nas selecionadas (zero-cost p/ estabilidade base).
    _p(f"walk-forward ({len(selected)} variantes, {walk_forward_folds} folds)")
    wf_list: List[WalkForwardEval] = []
    for sname, vres in sel_set.items():
        wf_list.append(_walk_forward_eval(
            spec, candles, vres, n_folds=walk_forward_folds,
            capital=capital, min_candles=min_candles, symbol=symbol,
            cost_config=None, precompute=precompute))
    wf_by_name = {w.variant_name: w for w in wf_list}

    # 6) Recomendacao + demo gate (so consideram variantes com WF rodado).
    considered = [v for v in variants if v.name in wf_by_name]
    rec, detail, suggested, gate_sat, block_reason = _recommend(
        strategy, baseline, considered, wf_by_name,
        real_dataset=real_dataset)

    return StrategyCalibration(
        strategy=strategy, is_candidate=is_candidate, baseline=baseline,
        variants=tuple(variants), selected_for_followup=tuple(selected),
        cost_sweep=tuple(cost_rows), walk_forward=tuple(wf_list),
        recommendation=rec, recommendation_detail=detail,
        suggested_config=suggested, demo_gate_satisfied=gate_sat,
        demo_authorized=False, demo_block_reason=block_reason)


def run_calibration(
    candles: Sequence, *, candidate: str, secondary: Optional[str] = None,
    capital: float = 5000.0, min_candles: int = 60, symbol: str = "BTCUSDT",
    timeframe: str = "15m", data_source: str = "csv",
    cost_scenarios: Optional[Sequence[CostScenario]] = None,
    walk_forward_folds: int = 5, top_n_followup: int = 3,
    precompute: bool = True, progress: Optional[Any] = None,
) -> CalibrationReport:
    """Roda a calibracao para o candidato + (opcional) secundaria."""
    if not candles:
        raise CalibrationError("nenhum candle fornecido")
    scenarios = list(cost_scenarios) if cost_scenarios is not None \
        else default_cost_sweep()
    real_dataset = str(data_source).lower().startswith(("real", "csv"))

    blocks: List[StrategyCalibration] = []
    blocks.append(calibrate_strategy(
        candidate, candles, is_candidate=True, capital=capital,
        min_candles=min_candles, symbol=symbol, cost_scenarios=scenarios,
        walk_forward_folds=walk_forward_folds, top_n_followup=top_n_followup,
        precompute=precompute, real_dataset=real_dataset,
        progress=progress))
    if secondary and secondary != candidate:
        blocks.append(calibrate_strategy(
            secondary, candles, is_candidate=False, capital=capital,
            min_candles=min_candles, symbol=symbol,
            cost_scenarios=scenarios, walk_forward_folds=walk_forward_folds,
            top_n_followup=top_n_followup, precompute=precompute,
            real_dataset=real_dataset, progress=progress))

    synthetic = not real_dataset
    notes = [
        "demo BLOQUEADA por padrao: este relatorio e CONSULTIVO e NUNCA "
        "autoriza demo. Demo depende de gates operacionais + V1-V12 + "
        "readiness + decisao humana.",
        "custos != zero sao research_illustrative (parametros de "
        "simulacao), NAO tabela real de exchange e NAO limite de risco.",
        "piso 0.005 do RiskEngine inalterado; 'stop_loss_floor_filter_pct' "
        "e filtro de SINAL (pre-RiskEngine), nao o piso real.",
        "'ajustar' exige walk-forward estavel e sem overfitting; nada "
        "autoaplicado.",
    ]
    if synthetic:
        notes.append(
            "dados sinteticos: metricas ILUSTRATIVAS, nao performance real.")

    def _iso(ts):
        if ts is None:
            return None
        from datetime import timezone
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return CalibrationReport(
        symbol=symbol, timeframe=timeframe, rows=len(candles),
        first_timestamp=_iso(getattr(candles[0], "timestamp", None)),
        last_timestamp=_iso(getattr(candles[-1], "timestamp", None)),
        data_source=data_source, synthetic_warning=synthetic,
        strategies=tuple(blocks), demo_blocked=True, notes=tuple(notes))


__all__ = [
    "CalibrationError",
    "CalibrationReport",
    "CostSweepRow",
    "StrategyCalibration",
    "VariantMetrics",
    "VariantResult",
    "WalkForwardEval",
    "build_ofat_variants",
    "calibrate_strategy",
    "run_calibration",
    "select_for_followup",
]
