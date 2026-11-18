"""
Regime Window Analysis (FASE 39)
================================
Analise TEMPORAL multi-janela, 100% OFFLINE e CONSULTIVA. Reavalia a
FASE 38 (familias x regime) em:
    * full_period      (todo o CSV)
    * monthly_windows  (cada mes-calendario)
    * reference_windows (janelas nomeadas da FASE 38)
com PARAMETROS FIXOS (sem tuning/grid). Mede estabilidade do edge por
(familia x regime) ao longo dos MESES e emite um verdict para o
mean_reversion-in-range + uma recomendacao consultiva + backlog de
hipoteses (papel).

⚠️  Inviolaveis: demo SEMPRE bloqueada (demo_authorized=False); piso
    0.005/RiskEngine/ModeGuard intactos; sem baixar dados; sem ordem/API/
    secret; sem tuning/grid; sem promover ao registry; nunca por PnL
    isolado; sem prometer performance.

Anti-overfitting:
    * Regimes classificados UMA vez na serie completa (causal,
      anti-lookahead) e FATIADOS por janela (sem recomputo, sem gap de
      warm-up entre meses).
    * sign_consistency e estabilidade calculados SOMENTE sobre
      monthly_windows; full_period e reference_windows NAO entram nessa
      estatistica (apenas referencia comparativa).
    * Mes com poucos trades => sample_sufficient=False; nao sustenta edge.
    * NUNCA promover com base em uma janela isolada.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.backtesting.data_splits import split_by_calendar_month
from crypto_trading_bot.research.market_regime import (
    RegimeClassification,
    RegimeLabel,
    classify_regimes,
)
from crypto_trading_bot.research.strategy_family_research import (
    DEFAULT_FAMILIES,
    FamilyRegimeReport,
    MIN_TRADES_PER_REGIME,
    research_family,
)

# Thresholds CONSULTIVOS (documentados).
MIN_MONTHS_FOR_STABILITY = 3
MIN_SIGN_CONSISTENCY = 0.6        # fracao de meses com expectancy>0
MIN_PF_PROMOTE = 1.2
HYPOTHESIS_BACKLOG_VERSION = "v1"


# Backlog de hipoteses futuras (PAPEL; nao implementado nesta fase).
HYPOTHESIS_BACKLOG: Tuple[Mapping[str, Any], ...] = (
    {
        "hypothesis": "range_mean_reversion_vwap_bollinger",
        "target_regime": "range",
        "success_criterion": "PF>=1.2 e expectancy>0 estaveis cross-mes "
                             "no regime range, com walk-forward nao-degradante",
        "overfitting_risk": "medio: filtros adicionais podem ajustar ao "
                            "periodo; exigir validacao cross-janela",
        "data_needed": "ja disponivel (17mo BTCUSDT 15m)",
        "suggested_priority": "alta (mean_reversion-in-range foi a unica pista)",
    },
    {
        "hypothesis": "no_trade_filter_chop_noise",
        "target_regime": "chop_noise",
        "success_criterion": "reduzir trades perdedores em chop sem perder "
                             "edge nos demais regimes",
        "overfitting_risk": "baixo: filtro de supressao, nao gera sinal novo",
        "data_needed": "ja disponivel",
        "suggested_priority": "media",
    },
    {
        "hypothesis": "volatility_contraction_volume_obv_confirm",
        "target_regime": "breakout",
        "success_criterion": "breakout confirmado por volume/OBV com PF>=1.2",
        "overfitting_risk": "medio; breakout tem baixa cobertura (~1%) => "
                            "amostra pequena, alto risco de ruido",
        "data_needed": "pode exigir mais dados (cobertura breakout baixa)",
        "suggested_priority": "baixa ate haver mais amostra de breakout",
    },
    {
        "hypothesis": "selective_trend_following_trend_only",
        "target_regime": "trend_up/trend_down",
        "success_criterion": "operar so em trend_up/down com PF>=1.2 estavel",
        "overfitting_risk": "medio",
        "data_needed": "ja disponivel",
        "suggested_priority": "media",
    },
    {
        "hypothesis": "min_max_volatility_filter",
        "target_regime": "secondary_flags high/low_volatility como gate",
        "success_criterion": "filtrar entradas fora da faixa de vol util",
        "overfitting_risk": "medio (percentis podem ajustar ao periodo)",
        "data_needed": "ja disponivel",
        "suggested_priority": "media",
    },
    {
        "hypothesis": "session_hour_filter",
        "target_regime": "todos",
        "success_criterion": "edge por hora/sessao (duvidoso em cripto 24/7)",
        "overfitting_risk": "alto: 24/7 sem sessao clara => provavel ruido",
        "data_needed": "ja disponivel",
        "suggested_priority": "baixa",
    },
)


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class WindowFamilyResult:
    """Resultado de UMA familia em UMA janela (resumo do FASE 38)."""
    family: str
    is_prototype: bool
    recommendation: str
    best_regime: Optional[str]
    overall_trades: int
    overall_pf: Optional[float]
    overall_expectancy: float
    per_regime: Tuple[Mapping[str, Any], ...]   # RegimeMetrics.to_dict()

    def to_dict(self) -> dict:
        return {
            "family": self.family, "is_prototype": self.is_prototype,
            "recommendation": self.recommendation,
            "best_regime": self.best_regime,
            "overall_trades": self.overall_trades,
            "overall_pf": self.overall_pf,
            "overall_expectancy": round(self.overall_expectancy, 6),
            "per_regime": [dict(m) for m in self.per_regime],
        }


@dataclass(frozen=True)
class WindowReport:
    label: str
    window_type: str          # full_period | monthly | reference
    start_index: int
    end_index: int
    rows: int
    first_timestamp: Optional[str]
    last_timestamp: Optional[str]
    regime_distribution: Mapping[str, float]
    families: Tuple[WindowFamilyResult, ...]

    def to_dict(self) -> dict:
        return {
            "label": self.label, "window_type": self.window_type,
            "start_index": self.start_index, "end_index": self.end_index,
            "rows": self.rows, "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "regime_distribution": {
                k: round(v, 6) for k, v in self.regime_distribution.items()},
            "families": [f.to_dict() for f in self.families],
        }


@dataclass(frozen=True)
class FamilyRegimeStability:
    """Estabilidade cross-MES (so monthly_windows) de (familia x regime)."""
    family: str
    regime: str
    n_months: int
    n_sample_sufficient: int
    mean_pf: Optional[float]
    std_pf: Optional[float]
    mean_expectancy: Optional[float]
    std_expectancy: Optional[float]
    sign_consistency: Optional[float]    # fracao meses suf. com exp>0
    mean_coverage: Optional[float]

    def to_dict(self) -> dict:
        return {
            "family": self.family, "regime": self.regime,
            "n_months": self.n_months,
            "n_sample_sufficient": self.n_sample_sufficient,
            "mean_pf": self.mean_pf, "std_pf": self.std_pf,
            "mean_expectancy": self.mean_expectancy,
            "std_expectancy": self.std_expectancy,
            "sign_consistency": self.sign_consistency,
            "mean_coverage": self.mean_coverage,
        }


@dataclass(frozen=True)
class MeanReversionRangeVerdict:
    verdict: str              # ruido|insuficiencia_amostra|pista_para_pesquisa|rejeitar
    window_sensitive: bool
    full_period_trades: int
    full_period_pf: Optional[float]
    full_period_expectancy: float
    full_period_sample_sufficient: bool
    monthly_sign_consistency: Optional[float]
    walk_forward_inconclusive: bool
    detail: str

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "window_sensitive": self.window_sensitive,
            "full_period_trades": self.full_period_trades,
            "full_period_pf": self.full_period_pf,
            "full_period_expectancy": round(self.full_period_expectancy, 6),
            "full_period_sample_sufficient":
                self.full_period_sample_sufficient,
            "monthly_sign_consistency": self.monthly_sign_consistency,
            "walk_forward_inconclusive": self.walk_forward_inconclusive,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RegimeWindowReport:
    schema: str = "regime_window_analysis_v1"
    symbol: str = ""
    timeframe: str = ""
    rows: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    data_source: str = "real"
    full_period: Optional[Mapping[str, Any]] = None
    monthly_windows: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple)
    reference_windows: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple)
    stability: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    mean_reversion_range_verdict: Optional[Mapping[str, Any]] = None
    decision: str = "manter_demo_bloqueada"
    decision_detail: str = ""
    hypothesis_backlog: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple)
    demo_blocked: bool = True       # SEMPRE True
    demo_authorized: bool = False   # SEMPRE False
    partial: bool = False
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema, "symbol": self.symbol,
            "timeframe": self.timeframe, "rows": self.rows,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "data_source": self.data_source,
            "full_period": dict(self.full_period) if self.full_period
            else None,
            "monthly_windows": [dict(w) for w in self.monthly_windows],
            "reference_windows": [dict(w) for w in self.reference_windows],
            "stability": [dict(s) for s in self.stability],
            "mean_reversion_range_verdict": (
                dict(self.mean_reversion_range_verdict)
                if self.mean_reversion_range_verdict else None),
            "decision": self.decision,
            "decision_detail": self.decision_detail,
            "hypothesis_backlog": [dict(h) for h in self.hypothesis_backlog],
            "demo_blocked": self.demo_blocked,
            "demo_authorized": self.demo_authorized,
            "partial": self.partial,
            "notes": list(self.notes),
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slice_classification(
    rc_full: RegimeClassification, start: int, end: int,
) -> RegimeClassification:
    """Fatia rc_full p/ [start,end] e RE-INDEXA para janela-local (0-based).

    Reaproveita a classificacao CAUSAL da serie completa (sem recomputo e
    sem gap de warm-up entre meses). Anti-lookahead preservado: o rotulo
    do indice global g so usou candles <= g.
    """
    labels: List[RegimeLabel] = []
    for lab in rc_full.labels:
        if start <= lab.index <= end:
            labels.append(RegimeLabel(
                index=lab.index - start,
                primary_regime=lab.primary_regime,
                secondary_flags=lab.secondary_flags))
    counts: Dict[str, int] = {}
    for lab in labels:
        counts[lab.primary_regime] = counts.get(lab.primary_regime, 0) + 1
    total = len(labels)
    coverage = {k: (v / total if total else 0.0)
                for k, v in counts.items()}
    return RegimeClassification(
        labels=tuple(labels), segments=(), coverage=coverage,
        coverage_counts=counts, lookback=rc_full.lookback, n_labeled=total)


def _family_result(fr: FamilyRegimeReport) -> WindowFamilyResult:
    return WindowFamilyResult(
        family=fr.family, is_prototype=fr.is_prototype,
        recommendation=fr.recommendation, best_regime=fr.best_regime,
        overall_trades=fr.overall.trades,
        overall_pf=fr.overall.profit_factor,
        overall_expectancy=fr.overall.expectancy_usd,
        per_regime=tuple(m.to_dict() for m in fr.per_regime_tagging))


def _eval_window(
    label: str, window_type: str, candles: Sequence, start: int, end: int,
    rc_full: RegimeClassification, *, families: Sequence[str],
    capital: float, min_candles: int, symbol: str, wf_folds: int,
    cost_config, real_dataset: bool, progress=None,
) -> Tuple[WindowReport, Dict[str, FamilyRegimeReport]]:
    sub = list(candles[start:end + 1])
    rc_win = _slice_classification(rc_full, start, end)
    fam_results: List[WindowFamilyResult] = []
    fam_reports: Dict[str, FamilyRegimeReport] = {}
    for fam in families:
        if progress:
            progress(f"[{label}] {fam}")
        fr = research_family(
            fam, sub, rc_win, capital=capital, min_candles=min_candles,
            symbol=symbol, wf_folds=wf_folds, cost_config=cost_config,
            run_segments=False, real_dataset=real_dataset)
        fam_reports[fam] = fr
        fam_results.append(_family_result(fr))
    wr = WindowReport(
        label=label, window_type=window_type, start_index=start,
        end_index=end, rows=len(sub),
        first_timestamp=_iso(getattr(sub[0], "timestamp", None))
        if sub else None,
        last_timestamp=_iso(getattr(sub[-1], "timestamp", None))
        if sub else None,
        regime_distribution=dict(rc_win.coverage),
        families=tuple(fam_results))
    return wr, fam_reports


# --------------------------------------------------------------------------
# Estabilidade cross-mes (SO monthly_windows)
# --------------------------------------------------------------------------

def _compute_stability(
    monthly: Sequence[WindowReport], families: Sequence[str],
) -> List[FamilyRegimeStability]:
    out: List[FamilyRegimeStability] = []
    # Coleta por (familia, regime) ao longo dos meses.
    keys: set = set()
    for wr in monthly:
        for f in wr.families:
            for m in f.per_regime:
                keys.add((f.family, m["regime"]))
    for fam, regime in sorted(keys):
        pfs: List[float] = []
        exps: List[float] = []
        covs: List[float] = []
        n_suff = 0
        n_months = 0
        suff_exps: List[float] = []
        for wr in monthly:
            fam_block = next((f for f in wr.families if f.family == fam),
                            None)
            if fam_block is None:
                continue
            m = next((mm for mm in fam_block.per_regime
                      if mm["regime"] == regime), None)
            if m is None:
                continue
            n_months += 1
            covs.append(float(m.get("coverage", 0.0)))
            if m.get("sample_sufficient"):
                n_suff += 1
                if m.get("profit_factor") is not None:
                    pfs.append(float(m["profit_factor"]))
                exps.append(float(m.get("expectancy_usd", 0.0)))
                suff_exps.append(float(m.get("expectancy_usd", 0.0)))
        sign_consistency = (
            round(sum(1 for e in suff_exps if e > 0) / len(suff_exps), 4)
            if suff_exps else None)
        out.append(FamilyRegimeStability(
            family=fam, regime=regime, n_months=n_months,
            n_sample_sufficient=n_suff,
            mean_pf=round(statistics.mean(pfs), 4) if pfs else None,
            std_pf=round(statistics.pstdev(pfs), 4) if len(pfs) > 1
            else (0.0 if pfs else None),
            mean_expectancy=round(statistics.mean(exps), 6) if exps
            else None,
            std_expectancy=round(statistics.pstdev(exps), 6)
            if len(exps) > 1 else (0.0 if exps else None),
            sign_consistency=sign_consistency,
            mean_coverage=round(statistics.mean(covs), 6) if covs
            else None))
    return out


# --------------------------------------------------------------------------
# Verdict mean_reversion-in-range
# --------------------------------------------------------------------------

def _mr_range_verdict(
    full_reports: Mapping[str, FamilyRegimeReport],
    stability: Sequence[FamilyRegimeStability],
    family: str = "mean_reversion_research",
) -> MeanReversionRangeVerdict:
    fam = family
    fr = full_reports.get(fam)
    full_m = None
    if fr is not None:
        full_m = next((m for m in fr.per_regime_tagging
                       if m.regime == "range"), None)
    wf_inconcl = bool(fr.walk_forward.inconclusive) if fr else True

    st = next((s for s in stability
               if s.family == fam and s.regime == "range"), None)
    sign_cons = st.sign_consistency if st else None

    if full_m is None or full_m.trades == 0:
        return MeanReversionRangeVerdict(
            verdict="insuficiencia_amostra", window_sensitive=False,
            full_period_trades=0, full_period_pf=None,
            full_period_expectancy=0.0, full_period_sample_sufficient=False,
            monthly_sign_consistency=sign_cons,
            walk_forward_inconclusive=wf_inconcl,
            detail="sem trades de range no periodo completo.")

    pf = full_m.profit_factor
    exp = full_m.expectancy_usd
    suff = full_m.sample_sufficient
    pf_ok = pf is not None and pf >= MIN_PF_PROMOTE
    # window_sensitive: full razoavel mas meses inconsistentes.
    window_sensitive = bool(
        exp > 0 and sign_cons is not None
        and sign_cons < MIN_SIGN_CONSISTENCY)

    if not suff:
        verdict = "insuficiencia_amostra"
        detail = (f"amostra insuficiente mesmo no completo "
                  f"(trades={full_m.trades} < {MIN_TRADES_PER_REGIME}).")
    elif exp > 0 and not pf_ok and sign_cons is not None \
            and sign_cons >= MIN_SIGN_CONSISTENCY and not wf_inconcl:
        verdict = "pista_para_pesquisa"
        detail = (f"expectancy>0 com amostra suficiente (trades="
                  f"{full_m.trades}) e consistencia mensal "
                  f"{sign_cons}, porem PF={pf} < {MIN_PF_PROMOTE}. "
                  "Merece NOVA hipotese (continuar pesquisa); NAO promover.")
    elif exp <= 0 or (pf is not None and pf < 1.0):
        verdict = "rejeitar"
        detail = (f"amostra suficiente porem expectancy={round(exp, 4)} / "
                  f"PF={pf} insuficientes no completo.")
    elif window_sensitive:
        verdict = "ruido"
        detail = (f"expectancy>0 no completo mas consistencia mensal baixa "
                  f"({sign_cons}) => provavel ruido/window-sensitive.")
    else:
        # exp>0, PF>=1.2, consistente => seria promovivel; ainda CONSULTIVO.
        verdict = "pista_para_pesquisa"
        detail = (f"edge aparente (PF={pf}, exp={round(exp, 4)}); validar "
                  "via FASE 37.4 antes de qualquer uso. Demo BLOQUEADA.")
    return MeanReversionRangeVerdict(
        verdict=verdict, window_sensitive=window_sensitive,
        full_period_trades=full_m.trades, full_period_pf=pf,
        full_period_expectancy=exp, full_period_sample_sufficient=suff,
        monthly_sign_consistency=sign_cons,
        walk_forward_inconclusive=wf_inconcl, detail=detail)


# --------------------------------------------------------------------------
# Decisao consultiva
# --------------------------------------------------------------------------

def _decide(
    full_reports: Mapping[str, FamilyRegimeReport],
    stability: Sequence[FamilyRegimeStability],
    mr_verdict: MeanReversionRangeVerdict,
) -> Tuple[str, str]:
    # Promovivel: alguma (familia x regime) com edge robusto E estavel
    # (PF>=1.2, exp>0, amostra suf. no completo, WF estavel, consistencia).
    for fam, fr in full_reports.items():
        if fr.walk_forward.inconclusive or fr.walk_forward.overfitting_warning:
            continue
        for m in fr.per_regime_tagging:
            if not m.sample_sufficient:
                continue
            pf = m.profit_factor
            st = next((s for s in stability
                       if s.family == fam and s.regime == m.regime), None)
            cons_ok = (st is not None and st.sign_consistency is not None
                       and st.sign_consistency >= MIN_SIGN_CONSISTENCY
                       and st.n_sample_sufficient >= MIN_MONTHS_FOR_STABILITY)
            if (pf is not None and pf >= MIN_PF_PROMOTE
                    and m.expectancy_usd > 0 and cons_ok):
                return ("promover_para_calibracao",
                        f"'{fam}' x '{m.regime}': edge robusto e estavel "
                        f"cross-mes (PF={pf}, consistencia="
                        f"{st.sign_consistency}). Encaminhar a FASE 37.4. "
                        "CONSULTIVO; demo BLOQUEADA.")

    if mr_verdict.verdict == "pista_para_pesquisa":
        return ("continuar_pesquisa",
                "mean_reversion-in-range e PISTA (sem edge robusto). "
                "Avaliar hipoteses do backlog (ex.: range mean-reversion + "
                "filtro VWAP/Bollinger). NAO promover; demo BLOQUEADA.")
    if mr_verdict.verdict == "insuficiencia_amostra":
        return ("expandir_dataset",
                "pista limitada por amostra mesmo no completo. Considerar "
                "(PAPEL) mais dados (outro periodo/timeframe/ativo) antes de "
                "novas hipoteses. NAO baixar agora; demo BLOQUEADA.")
    if mr_verdict.verdict == "ruido":
        return ("rejeitar_definitivamente",
                "sinal de range nao sobrevive a consistencia mensal "
                "(provavel ruido). Rejeitar o conjunto atual; demo "
                "BLOQUEADA.")
    return ("rejeitar_definitivamente",
            "nenhuma familia/regime mostrou edge robusto e estavel no "
            "periodo completo + meses. Rejeitar conjunto atual; demo "
            "BLOQUEADA.")


# --------------------------------------------------------------------------
# Orquestracao
# --------------------------------------------------------------------------

def run_regime_window_analysis(
    candles: Sequence, *, families: Optional[Sequence[str]] = None,
    capital: float = 5000.0, min_candles: int = 60, symbol: str = "BTCUSDT",
    timeframe: str = "15m", data_source: str = "real",
    regime_lookback: int = 96, wf_folds: int = 5,
    reference_windows: Optional[Sequence[Tuple[str, str, str]]] = None,
    cost_config=None, min_window_candles: int = 200,
    focus_family: str = "mean_reversion_research", progress=None,
) -> RegimeWindowReport:
    """Roda a analise temporal multi-janela. reference_windows: lista de
    (label, start_date, end_date) UTC (date-only inclusivo no fim)."""
    if not candles:
        from crypto_trading_bot.research.strategy_family_research import (
            FamilyResearchError,
        )
        raise FamilyResearchError("nenhum candle fornecido")
    fams = list(families) if families else list(DEFAULT_FAMILIES)
    real_dataset = str(data_source).lower().startswith(("real", "csv"))
    if cost_config is None:
        from crypto_trading_bot.research.calibration_costs import (
            build_cost_scenario,
        )
        cost_config = build_cost_scenario("realistic_research").config

    if progress:
        progress("classificando regimes (serie completa, causal)")
    rc_full = classify_regimes(candles, lookback=regime_lookback)

    partial = False
    full_wr = None
    full_reports: Dict[str, FamilyRegimeReport] = {}
    monthly: List[WindowReport] = []
    refs: List[WindowReport] = []
    try:
        # full_period
        if progress:
            progress("full_period")
        full_wr, full_reports = _eval_window(
            "full_period", "full_period", candles, 0, len(candles) - 1,
            rc_full, families=fams, capital=capital, min_candles=min_candles,
            symbol=symbol, wf_folds=wf_folds, cost_config=cost_config,
            real_dataset=real_dataset, progress=progress)

        # monthly_windows
        for label, s, e in split_by_calendar_month(list(candles)):
            if (e - s + 1) < min_window_candles:
                # mes muito curto p/ avaliar; registra distribuicao apenas.
                rc_win = _slice_classification(rc_full, s, e)
                monthly.append(WindowReport(
                    label=label, window_type="monthly", start_index=s,
                    end_index=e, rows=e - s + 1,
                    first_timestamp=_iso(getattr(candles[s], "timestamp",
                                                 None)),
                    last_timestamp=_iso(getattr(candles[e], "timestamp",
                                                None)),
                    regime_distribution=dict(rc_win.coverage),
                    families=tuple()))
                continue
            wr, _ = _eval_window(
                label, "monthly", candles, s, e, rc_full, families=fams,
                capital=capital, min_candles=min_candles, symbol=symbol,
                wf_folds=wf_folds, cost_config=cost_config,
                real_dataset=real_dataset, progress=progress)
            monthly.append(wr)

        # reference_windows
        for label, sd, ed in (reference_windows or []):
            s, e = _date_range_indices(candles, sd, ed)
            if s is None or e is None or e < s:
                continue
            wr, _ = _eval_window(
                label, "reference", candles, s, e, rc_full, families=fams,
                capital=capital, min_candles=min_candles, symbol=symbol,
                wf_folds=wf_folds, cost_config=cost_config,
                real_dataset=real_dataset, progress=progress)
            refs.append(wr)
    except KeyboardInterrupt:
        partial = True
        if progress:
            progress("INTERROMPIDO (Ctrl+C) -> relatorio PARCIAL")

    # Estabilidade SO sobre monthly_windows com familias avaliadas.
    monthly_eval = [w for w in monthly if w.families]
    stability = _compute_stability(monthly_eval, fams)
    mr_verdict = _mr_range_verdict(full_reports, stability, focus_family)
    if full_reports and not partial:
        decision, detail = _decide(full_reports, stability, mr_verdict)
    else:
        decision, detail = ("manter_demo_bloqueada",
                            "analise parcial/incompleta; decisao adiada. "
                            "demo BLOQUEADA.")

    notes = [
        "demo BLOQUEADA por padrao: relatorio CONSULTIVO; NUNCA autoriza "
        "demo (depende de gates + V1-V12 + readiness + humano).",
        "params FIXOS em todas as janelas; sem tuning/grid. Teste e "
        "CONSISTENCIA cross-mes, nunca a melhor janela.",
        "estabilidade calculada SO sobre monthly_windows; full_period e "
        "reference_windows sao referencia comparativa (nao entram na "
        "estatistica de consistencia).",
        "regimes classificados 1x na serie completa (causal) e fatiados "
        "por janela: sem recomputo, sem gap de warm-up, anti-lookahead.",
        "hypothesis_backlog e PAPEL: nada implementado; expansao de dados "
        "e recomendacao futura (sem baixar agora).",
        "piso 0.005/RiskEngine/ModeGuard intactos; nada autoaplicado.",
    ]
    return RegimeWindowReport(
        symbol=symbol, timeframe=timeframe, rows=len(candles),
        first_timestamp=_iso(getattr(candles[0], "timestamp", None)),
        last_timestamp=_iso(getattr(candles[-1], "timestamp", None)),
        data_source=data_source,
        full_period=full_wr.to_dict() if full_wr else None,
        monthly_windows=tuple(w.to_dict() for w in monthly),
        reference_windows=tuple(w.to_dict() for w in refs),
        stability=tuple(s.to_dict() for s in stability),
        mean_reversion_range_verdict=mr_verdict.to_dict(),
        decision=decision, decision_detail=detail,
        hypothesis_backlog=HYPOTHESIS_BACKLOG, demo_blocked=True,
        demo_authorized=False, partial=partial, notes=tuple(notes))


def _date_range_indices(candles, start_date: str, end_date: str):
    def _parse(v: str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None
    sd = _parse(start_date)
    ed = _parse(end_date)
    if ed is not None and len(end_date.strip()) == 10:
        from datetime import timedelta
        ed = ed + timedelta(days=1)   # date-only end inclusivo
    s_idx = e_idx = None
    for i, c in enumerate(candles):
        ts = getattr(c, "timestamp", None)
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if sd is not None and ts < sd:
            continue
        if ed is not None and ts >= ed:
            continue
        if s_idx is None:
            s_idx = i
        e_idx = i
    return s_idx, e_idx


__all__ = [
    "HYPOTHESIS_BACKLOG",
    "FamilyRegimeStability",
    "MeanReversionRangeVerdict",
    "RegimeWindowReport",
    "WindowFamilyResult",
    "WindowReport",
    "run_regime_window_analysis",
    "split_by_calendar_month",
]
