"""
Timeframe Research (FASE 40)
============================
Orquestra a ULTIMA tentativa research: avalia a hipotese
`range_mean_reversion_vwap_bollinger_research` (e controles) em MULTIPLOS
timeframes, comparando por ROBUSTEZ (nao por PnL). Decide entre seguir a
pesquisa (promover/continuar) ou ENCERRAR e seguir para infra operacional.

Por timeframe:
  * garante o dataset canonico (local; ou fetch PUBLICO read-only SOMENTE
    com fetch_missing + allow_network); roda data_readiness; usa SO se
    readiness=ready;
  * roda `run_regime_window_analysis` (full + mensal + reference, params
    FIXOS) com focus_family = hipotese FASE 40.

⚠️  Inviolaveis: demo SEMPRE bloqueada (baixar dados NAO libera demo);
    fetch SO publico read-only e SO com as 2 flags; sem overwrite sem
    force; testes 100% offline (FakeHistoricalProvider); piso 0.005/
    RiskEngine/ModeGuard intactos; sem promover ao registry; nunca por
    PnL isolado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

FOCUS_FAMILY = "range_mean_reversion_vwap_bollinger_research"
# Controles negativos (familias atuais) p/ comparar contra a hipotese.
DEFAULT_FAMILIES_FASE40 = (
    FOCUS_FAMILY,
    "trend_pullback_bidirectional",
)

MIN_PF_PROMOTE = 1.2
MIN_SIGN_CONSISTENCY = 0.6


class TimeframeResearchError(Exception):
    pass


@dataclass(frozen=True)
class TimeframeDatasetStatus:
    timeframe: str
    dataset_path: str
    status: str          # ready_local|fetched_ready|gated_missing_dataset|dataset_not_ready
    readiness_status: Optional[str]
    rows: Optional[int]
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe, "dataset_path": self.dataset_path,
            "status": self.status, "readiness_status": self.readiness_status,
            "rows": self.rows, "note": self.note,
        }


@dataclass(frozen=True)
class TimeframeResult:
    timeframe: str
    dataset: Mapping[str, Any]
    evaluated: bool
    window_report: Optional[Mapping[str, Any]]   # RegimeWindowReport.to_dict
    focus_verdict: Optional[str]                 # verdict do mean_reversion-in-range da hipotese
    focus_decision: Optional[str]                # decisao da janela

    def to_dict(self) -> dict:
        return {
            "timeframe": self.timeframe, "dataset": dict(self.dataset),
            "evaluated": self.evaluated,
            "window_report": dict(self.window_report)
            if self.window_report else None,
            "focus_verdict": self.focus_verdict,
            "focus_decision": self.focus_decision,
        }


@dataclass(frozen=True)
class FinalResearchReport:
    schema: str = "final_research_attempt_v1"
    symbol: str = ""
    focus_family: str = FOCUS_FAMILY
    timeframes: Tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    timeframe_sensitive: bool = False
    decision: str = "manter_demo_bloqueada"
    decision_detail: str = ""
    demo_blocked: bool = True       # SEMPRE True
    demo_authorized: bool = False   # SEMPRE False
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema, "symbol": self.symbol,
            "focus_family": self.focus_family,
            "timeframes": [dict(t) for t in self.timeframes],
            "timeframe_sensitive": self.timeframe_sensitive,
            "decision": self.decision,
            "decision_detail": self.decision_detail,
            "demo_blocked": self.demo_blocked,
            "demo_authorized": self.demo_authorized,
            "notes": list(self.notes),
        }


def _canonical_path(base_dir: str, symbol: str, tf_label: str) -> Path:
    return (Path(base_dir) / symbol.upper() / tf_label
            / f"{symbol.upper()}_{tf_label}.csv")


def ensure_dataset(
    symbol: str, timeframe: str, *, base_dir: str, start_date: str,
    end_date: str, fetch_missing: bool, allow_network: bool, force: bool,
    provider_name: str = "binance", provider_obj=None, progress=None,
) -> TimeframeDatasetStatus:
    """Garante o dataset canonico do timeframe. Fetch SO publico read-only
    e SO com fetch_missing + allow_network (ou provider_obj injetado em
    teste). data_readiness obrigatorio. Sem overwrite sem force."""
    from crypto_trading_bot.data_readiness import validate_candle_dataset
    from crypto_trading_bot.historical_data import normalize_timeframe

    tf_label, _ = normalize_timeframe(timeframe)
    dest = _canonical_path(base_dir, symbol, tf_label)

    def _readiness(path: Path):
        rep = validate_candle_dataset(
            csv_path=str(path), symbol=symbol.upper(), timeframe=tf_label,
            source="fase40")
        return rep

    if dest.is_file() and not force:
        rep = _readiness(dest)
        ok = not rep.blocks_backtest
        return TimeframeDatasetStatus(
            timeframe=tf_label, dataset_path=str(dest),
            status="ready_local" if ok else "dataset_not_ready",
            readiness_status=rep.readiness_status.value, rows=rep.rows,
            note="dataset local" if ok else "readiness reprovou local")

    # Ausente (ou force): fetch SOMENTE com as 2 flags (ou provider_obj).
    can_fetch = (fetch_missing and allow_network) or provider_obj is not None
    if not can_fetch:
        return TimeframeDatasetStatus(
            timeframe=tf_label, dataset_path=str(dest),
            status="gated_missing_dataset", readiness_status=None,
            rows=None,
            note=("dataset ausente; forneca --fetch-missing-data "
                  "--allow-network para obter via fetcher PUBLICO read-only"))
    if progress:
        progress(f"[{tf_label}] fetch read-only {start_date}..{end_date}")
    from crypto_trading_bot.historical_data import (
        fetch_historical, HistoricalDataError,
    )
    try:
        result = fetch_historical(
            provider=provider_name, symbol=symbol, timeframe=timeframe,
            start_date=start_date, end_date=end_date, base_dir=base_dir,
            force=force, run_readiness=True, provider_obj=provider_obj)
    except HistoricalDataError as e:
        return TimeframeDatasetStatus(
            timeframe=tf_label, dataset_path=str(dest),
            status="dataset_not_ready", readiness_status=None, rows=None,
            note=f"fetch falhou: {e}")
    if result.overwrite_blocked or result.errors:
        return TimeframeDatasetStatus(
            timeframe=tf_label, dataset_path=str(dest),
            status="dataset_not_ready", readiness_status=None, rows=None,
            note="; ".join(result.errors) or "overwrite bloqueado")
    rep = _readiness(Path(result.dataset_path))
    ok = not rep.blocks_backtest
    return TimeframeDatasetStatus(
        timeframe=tf_label, dataset_path=result.dataset_path,
        status="fetched_ready" if ok else "dataset_not_ready",
        readiness_status=rep.readiness_status.value, rows=rep.rows,
        note="fetched + readiness ready" if ok
        else "fetched porem readiness reprovou")


def run_final_research(
    *, symbol: str, timeframes: Sequence[str], start_date: str,
    end_date: str, base_dir: str = "data/historical",
    families: Optional[Sequence[str]] = None, capital: float = 5000.0,
    min_candles: int = 60, regime_lookback: int = 96, wf_folds: int = 5,
    reference_windows: Optional[Sequence[Tuple[str, str, str]]] = None,
    fetch_missing: bool = False, allow_network: bool = False,
    force: bool = False, provider_name: str = "binance", provider_obj=None,
    cost_config=None, min_window_candles: int = 200, progress=None,
) -> FinalResearchReport:
    """Avalia a hipotese FASE 40 em multiplos timeframes e decide."""
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.historical_data import normalize_timeframe
    from crypto_trading_bot.research.regime_window_analysis import (
        run_regime_window_analysis,
    )

    fams = list(families) if families else list(DEFAULT_FAMILIES_FASE40)
    if FOCUS_FAMILY not in fams:
        fams = [FOCUS_FAMILY] + fams
    if not timeframes:
        raise TimeframeResearchError("informe ao menos 1 timeframe")

    tf_results: List[TimeframeResult] = []
    for tf in timeframes:
        tf_label, tf_min = normalize_timeframe(tf)
        if progress:
            progress(f"timeframe {tf_label}: readiness/dataset")
        ds = ensure_dataset(
            symbol, tf, base_dir=base_dir, start_date=start_date,
            end_date=end_date, fetch_missing=fetch_missing,
            allow_network=allow_network, force=force,
            provider_name=provider_name, provider_obj=provider_obj,
            progress=progress)
        if ds.status not in ("ready_local", "fetched_ready"):
            tf_results.append(TimeframeResult(
                timeframe=tf_label, dataset=ds.to_dict(), evaluated=False,
                window_report=None, focus_verdict=None,
                focus_decision=None))
            continue
        candles = load_candles_from_csv(
            ds.dataset_path, symbol=symbol.upper(), timeframe=str(tf_min))
        if progress:
            progress(f"timeframe {tf_label}: regime window analysis")
        rwr = run_regime_window_analysis(
            candles, families=fams, capital=capital,
            min_candles=min_candles, symbol=symbol.upper(),
            timeframe=tf_label, data_source="real",
            regime_lookback=regime_lookback, wf_folds=wf_folds,
            reference_windows=reference_windows, cost_config=cost_config,
            min_window_candles=min_window_candles,
            focus_family=FOCUS_FAMILY, progress=progress)
        d = rwr.to_dict()
        verdict = (d.get("mean_reversion_range_verdict") or {}).get(
            "verdict")
        tf_results.append(TimeframeResult(
            timeframe=tf_label, dataset=ds.to_dict(), evaluated=True,
            window_report=d, focus_verdict=verdict,
            focus_decision=d.get("decision")))

    decision, detail, tf_sensitive = _decide_cross_timeframe(tf_results)

    notes = [
        "demo BLOQUEADA por padrao: baixar dados NAO libera demo; "
        "resultado CONSULTIVO (gates + V1-V12 + readiness + humano).",
        "fetch SO publico read-only e SO com --fetch-missing-data "
        "--allow-network; sem overwrite sem --force; testes 100% offline.",
        "hipotese bidirecional: SHORT e SIMULADO no backtest; execucao "
        "real de short continua gated/bloqueada.",
        "comparacao por ROBUSTEZ/consistencia, nunca por PnL isolado; "
        "params FIXOS, sem grid/tuning por mes/regime/timeframe.",
        "'seguir_para_infra_operacional' encerra a pesquisa por ora; "
        "refino futuro vira backlog (hypothesis_backlog.md).",
        "piso 0.005/RiskEngine/ModeGuard intactos; prototipo fora do "
        "registry operacional.",
    ]
    return FinalResearchReport(
        symbol=symbol.upper(), focus_family=FOCUS_FAMILY,
        timeframes=tuple(t.to_dict() for t in tf_results),
        timeframe_sensitive=tf_sensitive, decision=decision,
        decision_detail=detail, demo_blocked=True, demo_authorized=False,
        notes=tuple(notes))


def _promotable(tf: TimeframeResult) -> bool:
    """A hipotese e promovivel NESTE timeframe? Reusa o veredito + a
    decisao da janela (que ja exige PF/exp/dd/amostra/WF/consistencia)."""
    if not tf.evaluated or tf.window_report is None:
        return False
    return tf.focus_decision == "promover_para_calibracao"


def _decide_cross_timeframe(
    tf_results: Sequence[TimeframeResult],
) -> Tuple[str, str, bool]:
    evaluated = [t for t in tf_results if t.evaluated]
    if not evaluated:
        return ("seguir_para_infra_operacional",
                "nenhum timeframe pronto (dados ausentes/nao-ready). Sem "
                "evidencia de edge => encerrar pesquisa por ora e seguir "
                "para infra/UI/readiness. Demo BLOQUEADA.", False)

    promotable = [t for t in evaluated if _promotable(t)]
    # timeframe_sensitive: promovivel em alguns TF e nao em outros.
    tf_sensitive = 0 < len(promotable) < len(evaluated)

    if promotable and not tf_sensitive:
        tfs = ", ".join(t.timeframe for t in promotable)
        return ("promover_para_calibracao",
                f"hipotese atingiu o gate com consistencia em TODOS os "
                f"timeframes prontos ({tfs}). Encaminhar a FASE 37.4 "
                "(calibracao); NUNCA demo. Demo BLOQUEADA.", False)
    if tf_sensitive:
        ok = ", ".join(t.timeframe for t in promotable)
        return ("continuar_pesquisa",
                f"timeframe_sensitive: edge so em {ok} e ausente nos "
                "demais => manual_review. NAO promover por 1 timeframe "
                "isolado. Demo BLOQUEADA.", True)

    # Nenhum promovivel: ha alguma pista (continuar) ou rejeitar/encerrar?
    any_pista = any(t.focus_verdict == "pista_para_pesquisa"
                    for t in evaluated)
    any_insuf = any(t.focus_verdict == "insuficiencia_amostra"
                    for t in evaluated)
    if any_pista:
        return ("continuar_pesquisa",
                "ha pista (sem robustez plena) em ao menos um timeframe; "
                "porem como esta e a ULTIMA tentativa research planejada, "
                "a pista vira backlog. Demo BLOQUEADA.", False)
    if any_insuf:
        return ("expandir_dataset",
                "limitacao de amostra em timeframe(s); expansao de dados "
                "fica como recomendacao futura (papel). Demo BLOQUEADA.",
                False)
    # ruido/rejeitar em todos => criterio TERMINAL de encerramento.
    return ("seguir_para_infra_operacional",
            "a hipotese NAO atingiu o gate de promocao em nenhum timeframe "
            "pronto (ruido/rejeitar). Criterio terminal: ENCERRAR a "
            "pesquisa estrategica por ora e seguir para infra operacional "
            "(UI/readiness/operator inputs/reports/fluxo). Refino futuro = "
            "backlog. Demo BLOQUEADA.", False)


__all__ = [
    "DEFAULT_FAMILIES_FASE40",
    "FOCUS_FAMILY",
    "FinalResearchReport",
    "TimeframeDatasetStatus",
    "TimeframeResearchError",
    "TimeframeResult",
    "ensure_dataset",
    "run_final_research",
]
