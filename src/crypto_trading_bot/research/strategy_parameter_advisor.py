"""
Strategy Parameter Research Advisor (FASE 29.x)
================================================
Avalia configuracoes de parametros (grid) sobre candles historicos,
ranqueia por robustez e sugere manter/ajustar/trocar — SEM jamais
alterar a configuracao real automaticamente e SEM enviar ordem.

⚠️  RESEARCH/OFFLINE/PAPER apenas. ZERO rede. ZERO ordem. ZERO IA/LLM.
⚠️  Avalia LONG e SHORT SEPARADAMENTE (Parte H).
⚠️  Preferir robustez/consistencia a lucro isolado. Penalizar drawdown
    alto, instabilidade e excesso de sinais. Nunca trocar so por mais
    trades.
⚠️  Reusa evaluate_strategy (backtest determinISTIco) da FASE 3F.
⚠️  NUNCA muta default_config das estrategias.

A sugestao eh CONSULTIVA: operador aprova manualmente. Demo real
continua usando a estrategia/config explicitamente informada no CLI.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# --------------------------------------------------------------------------
# Thresholds de robustez (research) - editaveis, documentados.
# --------------------------------------------------------------------------

# Minimo de trades para considerar uma config "avaliavel". Abaixo disso
# eh ruido estatistico -> insufficient_data.
MIN_TRADES_FOR_ROBUSTNESS = 5

# Profit factor minimo para considerar habilitar um lado.
MIN_PROFIT_FACTOR_ENABLE = 1.2

# Drawdown maximo aceitavel (% do capital, valor absoluto). Acima penaliza.
MAX_ACCEPTABLE_DRAWDOWN_PCT = 25.0

# Win rate minimo informativo (nao bloqueante isolado).
MIN_WIN_RATE_INFO = 35.0

# Trades/dia acima disso sugere overtrading -> penaliza.
MAX_TRADES_PER_DAY_SOFT = 20.0


@dataclass(frozen=True)
class ParameterEvalResult:
    """Resultado de UMA config avaliada (um lado).

    FASE 33: campos extras ADITIVOS (defaults retrocompativeis):
    avg_rr, consecutive_losses, trades_per_day, zero_trade_windows,
    time_in_market_pct, stability, in/out-of-sample PF e
    overfitting_warning.
    """
    side: str                       # "long" | "short"
    config: Mapping[str, Any]
    total_trades: int
    win_rate: float
    profit_factor: Optional[float]
    expectancy_usd: float
    total_pnl_usd: float
    max_drawdown_pct: float
    avg_win_usd: float
    avg_loss_usd: float
    robustness_score: float
    warnings: Tuple[str, ...] = ()
    # FASE 33 - metricas adicionais (aditivas)
    avg_rr: float = 0.0
    consecutive_losses: int = 0
    trades_per_day: float = 0.0
    zero_trade_windows: int = 0
    time_in_market_pct: float = 0.0
    stability: Optional[float] = None
    in_sample_profit_factor: Optional[float] = None
    out_of_sample_profit_factor: Optional[float] = None
    overfitting_warning: bool = False

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "config": dict(self.config),
            "total_trades": int(self.total_trades),
            "win_rate": float(self.win_rate),
            "profit_factor": self.profit_factor,
            "expectancy_usd": float(self.expectancy_usd),
            "total_pnl_usd": float(self.total_pnl_usd),
            "max_drawdown_pct": float(self.max_drawdown_pct),
            "avg_win_usd": float(self.avg_win_usd),
            "avg_loss_usd": float(self.avg_loss_usd),
            "robustness_score": round(float(self.robustness_score), 4),
            "warnings": list(self.warnings),
            # FASE 33 - aditivos
            "avg_rr": round(float(self.avg_rr), 4),
            "consecutive_losses": int(self.consecutive_losses),
            "trades_per_day": round(float(self.trades_per_day), 4),
            "zero_trade_windows": int(self.zero_trade_windows),
            "time_in_market_pct": round(
                float(self.time_in_market_pct), 4,
            ),
            "stability": self.stability,
            "in_sample_profit_factor": self.in_sample_profit_factor,
            "out_of_sample_profit_factor":
                self.out_of_sample_profit_factor,
            "overfitting_warning": bool(self.overfitting_warning),
        }


@dataclass(frozen=True)
class SideRecommendation:
    """Recomendacao para um lado (long ou short)."""
    side: str
    enabled_recommendation: bool
    recommended_config: Optional[Mapping[str, Any]]
    reason: str
    ranking: Tuple[ParameterEvalResult, ...] = ()

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "enabled_recommendation": bool(self.enabled_recommendation),
            "recommended_config": (
                dict(self.recommended_config)
                if self.recommended_config is not None else None
            ),
            "reason": self.reason,
            "ranking": [r.to_dict() for r in self.ranking],
            # FASE 33 - bloco performance do melhor resultado (spec JSON)
            "performance": (
                self.ranking[0].to_dict() if self.ranking else {}
            ),
        }


@dataclass(frozen=True)
class AdvisorReport:
    """Relatorio consolidado do advisor."""
    symbol: str
    timeframe: str
    evaluated_at: datetime
    current_strategy: str
    candidate_strategy: str
    current_config: Mapping[str, Any]
    recommendation: str          # keep | adjust | switch_candidate | insufficient_data
    long: SideRecommendation
    short: SideRecommendation
    combined_recommendation: str  # long_only|short_only|long_short|keep_current|insufficient_data
    warnings: Tuple[str, ...] = ()
    candles_evaluated: int = 0
    # FASE 33 - aditivos
    profile: str = ""
    strategy_comparison: Tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict:
        long_d = self.long.to_dict()
        short_d = self.short.to_dict()
        # Ranking combinado top-level (spec FASE 33).
        combined_ranking = sorted(
            (long_d.get("ranking") or [])
            + (short_d.get("ranking") or []),
            key=lambda r: -float(r.get("robustness_score", 0.0)),
        )
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "evaluated_at": self.evaluated_at.isoformat(),
            "profile": self.profile,
            "current_strategy": self.current_strategy,
            "candidate_strategy": self.candidate_strategy,
            "current_config": dict(self.current_config),
            "recommendation": self.recommendation,
            "candles_evaluated": int(self.candles_evaluated),
            "long": long_d,
            "short": short_d,
            "combined": {
                "recommendation": self.combined_recommendation,
            },
            "warnings": list(self.warnings),
            "ranking": combined_ranking,
            "strategy_comparison": [
                dict(s) for s in self.strategy_comparison
            ],
        }

    def human_summary(self) -> str:
        lines = [
            "=" * 72,
            "  STRATEGY PARAMETER ADVISOR (research/offline)",
            "  Sugestao CONSULTIVA. NAO altera execucao real.",
            "=" * 72,
            f"  symbol:               {self.symbol}",
            f"  timeframe:            {self.timeframe}",
            f"  candles_evaluated:    {self.candles_evaluated}",
            f"  current_strategy:     {self.current_strategy}",
            f"  candidate_strategy:   {self.candidate_strategy}",
            f"  recommendation:       {self.recommendation}",
            f"  combined:             {self.combined_recommendation}",
            "-" * 72,
            f"  LONG enabled_recommendation: "
            f"{self.long.enabled_recommendation}",
            f"    reason: {self.long.reason}",
            f"  SHORT enabled_recommendation: "
            f"{self.short.enabled_recommendation}",
            f"    reason: {self.short.reason}",
            "=" * 72,
            "  AVISO: backtest NAO garante performance futura.",
            "  Demo real so muda apos aprovacao manual explicita.",
            "=" * 72,
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Grids default (Parte H)
# --------------------------------------------------------------------------

def default_long_grid() -> List[Dict[str, Any]]:
    """Grade LONG: EMA pairs x RSI overbought x pullback tolerance."""
    ema_pairs = [(9, 21), (12, 26), (20, 50), (21, 55)]
    rsi_overbought = [65.0, 70.0, 75.0]
    atr_tol = [0.0, 0.2]
    grid = []
    for (ef, es), rob, k in itertools.product(
        ema_pairs, rsi_overbought, atr_tol,
    ):
        grid.append({
            "ema_fast_period": ef, "ema_slow_period": es,
            "rsi_long_overbought": rob,
            "pullback_atr_tolerance_k": k,
            "enable_long": True, "enable_short": False,
        })
    return grid


def default_short_grid() -> List[Dict[str, Any]]:
    """Grade SHORT: EMA pairs x RSI oversold x pullback tolerance."""
    ema_pairs = [(9, 21), (12, 26), (20, 50), (21, 55)]
    rsi_oversold = [25.0, 30.0, 35.0]
    atr_tol = [0.0, 0.2]
    grid = []
    for (ef, es), ros, k in itertools.product(
        ema_pairs, rsi_oversold, atr_tol,
    ):
        grid.append({
            "ema_fast_period": ef, "ema_slow_period": es,
            "rsi_short_oversold": ros,
            "pullback_atr_tolerance_k": k,
            "enable_long": False, "enable_short": True,
        })
    return grid


# --------------------------------------------------------------------------
# Robustness scoring (Parte C - preferir robustez)
# --------------------------------------------------------------------------

def _compute_robustness_score(
    *, total_trades: int, win_rate: float,
    profit_factor: Optional[float], expectancy_usd: float,
    max_drawdown_pct: float, trades_per_day: float,
) -> Tuple[float, List[str]]:
    """Score consultivo de robustez. NAO eh composite de performance:
    penaliza drawdown, overtrading e amostra pequena; recompensa PF e
    expectancy positiva com consistencia.

    Retorna (score, warnings). score>0 nao garante recomendacao.
    """
    warnings: List[str] = []
    if total_trades < MIN_TRADES_FOR_ROBUSTNESS:
        warnings.append("insufficient_trades")
        return (0.0, warnings)

    pf = profit_factor if profit_factor is not None else 0.0
    # Base: PF acima de 1 contribui; abaixo penaliza.
    score = (pf - 1.0) * 2.0
    # Expectancy positiva por trade contribui suavemente.
    score += max(-1.0, min(1.0, expectancy_usd / 50.0))
    # Win rate informativo.
    if win_rate < MIN_WIN_RATE_INFO:
        warnings.append("low_win_rate")
        score -= 0.3
    # Drawdown alto penaliza forte.
    dd_abs = abs(max_drawdown_pct)
    if dd_abs > MAX_ACCEPTABLE_DRAWDOWN_PCT:
        warnings.append("high_drawdown")
        score -= (dd_abs - MAX_ACCEPTABLE_DRAWDOWN_PCT) / 10.0
    # Overtrading penaliza.
    if trades_per_day > MAX_TRADES_PER_DAY_SOFT:
        warnings.append("possible_overtrading")
        score -= 0.5
    return (round(score, 4), warnings)


# --------------------------------------------------------------------------
# FASE 33 - metricas extras, in/out-of-sample e overfitting
# --------------------------------------------------------------------------

# Overfitting: in-sample bom mas out-of-sample degrada forte.
OVERFITTING_IN_PF_MIN = 1.3
OVERFITTING_OUT_PF_MAX = 1.0
OVERFITTING_RATIO = 2.0   # in_pf > ratio * out_pf tambem alerta
IN_SAMPLE_FRACTION = 0.7
ZERO_TRADE_WINDOW_COUNT = 4


def _extra_metrics_from_report(rep, *, span_days: float,
                               n_candles: int) -> dict:
    """Extrai metricas FASE 33 de um BacktestReport (defensivo)."""
    trades = list(getattr(rep, "trades", []) or [])
    avg_win = float(getattr(rep, "avg_win_usd", 0.0) or 0.0)
    avg_loss = float(getattr(rep, "avg_loss_usd", 0.0) or 0.0)
    avg_rr = (avg_win / abs(avg_loss)) if avg_loss else 0.0

    max_consec = 0
    cur = 0
    for t in trades:
        pnl = getattr(t, "pnl_usd", None)
        if pnl is not None and pnl < 0:
            cur += 1
            max_consec = max(max_consec, cur)
        else:
            cur = 0

    # zero_trade_windows: janelas (quartis do range) sem entrada.
    zero_windows = 0
    if n_candles > 0:
        window = max(1, n_candles // ZERO_TRADE_WINDOW_COUNT)
        entry_idxs = [
            int(getattr(t, "entry_candle_idx", -1)) for t in trades
        ]
        for w in range(ZERO_TRADE_WINDOW_COUNT):
            lo, hi = w * window, (w + 1) * window
            if not any(lo <= idx < hi for idx in entry_idxs if idx >= 0):
                zero_windows += 1

    # time_in_market: fracao de candles com posicao aberta.
    in_market = 0
    for t in trades:
        e = getattr(t, "entry_candle_idx", None)
        x = getattr(t, "exit_candle_idx", None)
        if e is not None and x is not None and x >= e:
            in_market += (x - e)
    time_in_market_pct = (
        (in_market / n_candles) * 100.0 if n_candles else 0.0
    )

    total_trades = int(getattr(rep, "total_trades", 0) or 0)
    trades_per_day = total_trades / span_days if span_days > 0 else 0.0

    return {
        "avg_rr": avg_rr,
        "consecutive_losses": max_consec,
        "trades_per_day": trades_per_day,
        "zero_trade_windows": zero_windows,
        "time_in_market_pct": time_in_market_pct,
    }


def detect_overfitting(
    in_sample_pf: Optional[float], out_of_sample_pf: Optional[float],
) -> bool:
    """True quando in-sample promete e out-of-sample degrada.

    Penaliza configs que so funcionam no trecho de ajuste — preferir
    robustez/consistencia a lucro isolado.
    """
    if in_sample_pf is None:
        return False
    if in_sample_pf < OVERFITTING_IN_PF_MIN:
        return False
    if out_of_sample_pf is None:
        return True   # bom in-sample e SEM evidencia out-of-sample
    if out_of_sample_pf < OVERFITTING_OUT_PF_MAX:
        return True
    return in_sample_pf > OVERFITTING_RATIO * out_of_sample_pf


def stability_score(
    in_sample_pf: Optional[float], out_of_sample_pf: Optional[float],
) -> Optional[float]:
    """Razao out/in clampada em [0,1]. 1.0 = perfeitamente estavel."""
    if not in_sample_pf or in_sample_pf <= 0:
        return None
    if out_of_sample_pf is None:
        return None
    return round(max(0.0, min(1.0, out_of_sample_pf / in_sample_pf)), 4)


def _evaluate_in_out_sample(
    *, spec, candles: Sequence, config: Mapping[str, Any],
    initial_capital: float, min_candles: int, symbol: str,
    execution_cost_config=None,
) -> Tuple[Optional[float], Optional[float]]:
    """PF in-sample (70%) e out-of-sample (30%). Defensivo: None se
    o trecho for curto demais para o backtest."""
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    n = len(candles)
    split = int(n * IN_SAMPLE_FRACTION)
    results: list = [None, None]
    for i, sl in enumerate((slice(0, split), slice(split, n))):
        segment = list(candles[sl])
        if len(segment) < (min_candles + 5):
            continue
        try:
            ev = evaluate_strategy(
                spec=spec, candles=segment,
                config_override=dict(config),
                initial_capital=initial_capital,
                min_candles=min_candles, symbol=symbol,
                execution_cost_config=execution_cost_config,
            )
            results[i] = getattr(ev.single_report, "profit_factor", None)
        except Exception:  # noqa: BLE001
            results[i] = None
    return results[0], results[1]


def compare_strategies(
    *,
    candles: Sequence,
    strategy_names: Sequence[str] = (
        "trend_pullback", "trend_pullback_bidirectional",
        "volatility_breakout",
    ),
    initial_capital: float = 5000.0,
    min_candles: int = 60,
    symbol: str = "BTCUSDT",
    execution_cost_config=None,
) -> List[dict]:
    """Compara estrategias registradas (config default) por robustez.

    CONSULTIVO: nunca altera config real nem envia ordem. Ranking
    deterministico por robustness_score.
    """
    from crypto_trading_bot.challenge_readiness.strategy_factory import (
        build_strategy_spec,
    )
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    span_days = _candles_span_days(candles)
    rows: List[dict] = []
    for name in strategy_names:
        try:
            spec = build_strategy_spec(name)
            ev = evaluate_strategy(
                spec=spec, candles=list(candles),
                config_override=dict(spec.default_config),
                initial_capital=initial_capital,
                min_candles=min_candles, symbol=symbol,
                execution_cost_config=execution_cost_config,
            )
        except Exception as e:  # noqa: BLE001
            rows.append({
                "strategy": name, "error": type(e).__name__,
                "robustness_score": 0.0, "total_trades": 0,
            })
            continue
        rep = ev.single_report
        total_trades = int(getattr(rep, "total_trades", 0) or 0)
        pf = getattr(rep, "profit_factor", None)
        score, warns = _compute_robustness_score(
            total_trades=total_trades,
            win_rate=float(getattr(rep, "win_rate", 0.0) or 0.0),
            profit_factor=pf,
            expectancy_usd=float(
                getattr(rep, "expectancy_usd", 0.0) or 0.0
            ),
            max_drawdown_pct=float(
                getattr(rep, "max_drawdown_pct", 0.0) or 0.0
            ),
            trades_per_day=(
                total_trades / span_days if span_days > 0 else 0.0
            ),
        )
        rows.append({
            "strategy": name,
            "total_trades": total_trades,
            "win_rate": float(getattr(rep, "win_rate", 0.0) or 0.0),
            "profit_factor": pf,
            "total_pnl_usd": float(
                getattr(rep, "total_pnl_usd", 0.0) or 0.0
            ),
            "max_drawdown_pct": float(
                getattr(rep, "max_drawdown_pct", 0.0) or 0.0
            ),
            "robustness_score": score,
            "warnings": list(warns),
        })
    rows.sort(key=lambda r: -float(r.get("robustness_score", 0.0)))
    return rows


# --------------------------------------------------------------------------
# Core: avaliar um grid de um lado
# --------------------------------------------------------------------------

def _candles_span_days(candles: Sequence) -> float:
    if len(candles) < 2:
        return 1.0
    try:
        start = candles[0].timestamp
        end = candles[-1].timestamp
        secs = (end - start).total_seconds()
        return max(1.0 / 24.0, secs / 86400.0)
    except Exception:  # noqa: BLE001
        return 1.0


def _evaluate_side_grid(
    *, side: str, grid: Sequence[Mapping[str, Any]],
    candles: Sequence, initial_capital: float, min_candles: int,
    symbol: str, execution_cost_config=None,
) -> List[ParameterEvalResult]:
    """Avalia cada config do grid via evaluate_strategy (backtest)."""
    # Lazy imports - nao puxa rede.
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    from crypto_trading_bot.strategies.trend_pullback_bidirectional_strategy \
        import build_trend_pullback_bidirectional_spec

    spec = build_trend_pullback_bidirectional_spec()
    span_days = _candles_span_days(candles)
    results: List[ParameterEvalResult] = []

    for config in grid:
        try:
            ev = evaluate_strategy(
                spec=spec, candles=list(candles),
                config_override=dict(config),
                initial_capital=initial_capital,
                min_candles=min_candles, symbol=symbol,
                execution_cost_config=execution_cost_config,
            )
        except Exception:  # noqa: BLE001
            # Config invalida/erro -> ignora (nao quebra advisor).
            continue
        rep = ev.single_report
        total_trades = int(getattr(rep, "total_trades", 0) or 0)
        win_rate = float(getattr(rep, "win_rate", 0.0) or 0.0)
        pf = getattr(rep, "profit_factor", None)
        expectancy = float(getattr(rep, "expectancy_usd", 0.0) or 0.0)
        total_pnl = float(getattr(rep, "total_pnl_usd", 0.0) or 0.0)
        max_dd_pct = float(getattr(rep, "max_drawdown_pct", 0.0) or 0.0)
        avg_win = float(getattr(rep, "avg_win_usd", 0.0) or 0.0)
        avg_loss = float(getattr(rep, "avg_loss_usd", 0.0) or 0.0)
        trades_per_day = total_trades / span_days if span_days > 0 else 0.0

        score, warns = _compute_robustness_score(
            total_trades=total_trades, win_rate=win_rate,
            profit_factor=pf, expectancy_usd=expectancy,
            max_drawdown_pct=max_dd_pct, trades_per_day=trades_per_day,
        )
        extra = _extra_metrics_from_report(
            rep, span_days=span_days, n_candles=len(candles),
        )
        results.append(ParameterEvalResult(
            side=side, config=MappingProxyType(dict(config)),
            total_trades=total_trades, win_rate=win_rate,
            profit_factor=pf, expectancy_usd=expectancy,
            total_pnl_usd=total_pnl, max_drawdown_pct=max_dd_pct,
            avg_win_usd=avg_win, avg_loss_usd=avg_loss,
            robustness_score=score, warnings=tuple(warns),
            **extra,
        ))

    # Ranking determinISTIco: score desc, depois pf desc, depois trades.
    results.sort(
        key=lambda r: (
            -r.robustness_score,
            -(r.profit_factor or 0.0),
            -r.total_trades,
        )
    )
    return results


def _build_side_recommendation(
    side: str, ranking: List[ParameterEvalResult],
) -> SideRecommendation:
    if not ranking:
        return SideRecommendation(
            side=side, enabled_recommendation=False,
            recommended_config=None,
            reason="no_configs_evaluated",
            ranking=(),
        )
    best = ranking[0]
    # Habilita lado SE robustez positiva + PF aceitavel + amostra OK +
    # drawdown sob controle.
    pf_ok = (best.profit_factor or 0.0) >= MIN_PROFIT_FACTOR_ENABLE
    sample_ok = best.total_trades >= MIN_TRADES_FOR_ROBUSTNESS
    dd_ok = abs(best.max_drawdown_pct) <= MAX_ACCEPTABLE_DRAWDOWN_PCT
    score_ok = best.robustness_score > 0.0

    if not sample_ok:
        return SideRecommendation(
            side=side, enabled_recommendation=False,
            recommended_config=None,
            reason=(
                f"insufficient_data: best config teve "
                f"{best.total_trades} trades (< "
                f"{MIN_TRADES_FOR_ROBUSTNESS})"
            ),
            ranking=tuple(ranking),
        )
    if pf_ok and dd_ok and score_ok:
        reason = (
            f"{side} estavel: PF={best.profit_factor}, "
            f"trades={best.total_trades}, "
            f"dd={best.max_drawdown_pct:.2f}%, "
            f"score={best.robustness_score}"
        )
        return SideRecommendation(
            side=side, enabled_recommendation=True,
            recommended_config=best.config,
            reason=reason, ranking=tuple(ranking),
        )
    reasons = []
    if not pf_ok:
        reasons.append(
            f"profit_factor {best.profit_factor} < "
            f"{MIN_PROFIT_FACTOR_ENABLE}"
        )
    if not dd_ok:
        reasons.append(
            f"drawdown {best.max_drawdown_pct:.2f}% alto"
        )
    if not score_ok:
        reasons.append(f"robustness_score {best.robustness_score} <= 0")
    return SideRecommendation(
        side=side, enabled_recommendation=False,
        recommended_config=None,
        reason="; ".join(reasons),
        ranking=tuple(ranking),
    )


# --------------------------------------------------------------------------
# API principal
# --------------------------------------------------------------------------

def _enrich_best_with_in_out_sample(
    ranking: List[ParameterEvalResult], *, candles: Sequence,
    initial_capital: float, min_candles: int, symbol: str,
    execution_cost_config=None,
) -> List[ParameterEvalResult]:
    """FASE 33: avalia in/out-of-sample APENAS na melhor config do
    lado (custo controlado) e anexa overfitting_warning/stability."""
    if not ranking:
        return ranking
    from dataclasses import replace as dc_replace
    from crypto_trading_bot.strategies \
        .trend_pullback_bidirectional_strategy import (
            build_trend_pullback_bidirectional_spec,
        )
    spec = build_trend_pullback_bidirectional_spec()
    best = ranking[0]
    in_pf, out_pf = _evaluate_in_out_sample(
        spec=spec, candles=candles, config=best.config,
        initial_capital=initial_capital, min_candles=min_candles,
        symbol=symbol, execution_cost_config=execution_cost_config,
    )
    overfit = detect_overfitting(in_pf, out_pf)
    warns = best.warnings + (
        ("overfitting_warning",) if overfit else ()
    )
    score = best.robustness_score - (1.0 if overfit else 0.0)
    enriched = dc_replace(
        best,
        in_sample_profit_factor=in_pf,
        out_of_sample_profit_factor=out_pf,
        overfitting_warning=overfit,
        stability=stability_score(in_pf, out_pf),
        warnings=warns,
        robustness_score=round(score, 4),
    )
    return [enriched] + list(ranking[1:])


def run_parameter_advisor(
    *,
    candles: Sequence,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    current_strategy: str = "trend_pullback",
    current_config: Optional[Mapping[str, Any]] = None,
    long_grid: Optional[Sequence[Mapping[str, Any]]] = None,
    short_grid: Optional[Sequence[Mapping[str, Any]]] = None,
    initial_capital: float = 5000.0,
    min_candles: int = 60,
    execution_cost_config=None,
    now: Optional[datetime] = None,
    profile: str = "",
    include_strategy_comparison: bool = False,
    evaluate_out_of_sample: bool = True,
) -> AdvisorReport:
    """Roda o advisor sobre candles, ranqueando LONG e SHORT separados.

    NAO altera execucao real. NAO envia ordem. NAO muta defaults.

    FASE 33 (aditivo): profile (metadata consultiva no JSON),
    include_strategy_comparison (compara estrategias registradas) e
    in/out-of-sample + overfitting_warning na melhor config por lado.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    long_grid = list(long_grid) if long_grid is not None \
        else default_long_grid()
    short_grid = list(short_grid) if short_grid is not None \
        else default_short_grid()
    candles_evaluated = len(candles)

    warnings: List[str] = []
    if candles_evaluated < (min_candles + MIN_TRADES_FOR_ROBUSTNESS):
        warnings.append("low_candle_count_for_research")

    long_ranking = _evaluate_side_grid(
        side="long", grid=long_grid, candles=candles,
        initial_capital=initial_capital, min_candles=min_candles,
        symbol=symbol, execution_cost_config=execution_cost_config,
    )
    short_ranking = _evaluate_side_grid(
        side="short", grid=short_grid, candles=candles,
        initial_capital=initial_capital, min_candles=min_candles,
        symbol=symbol, execution_cost_config=execution_cost_config,
    )
    if evaluate_out_of_sample:
        long_ranking = _enrich_best_with_in_out_sample(
            long_ranking, candles=candles,
            initial_capital=initial_capital, min_candles=min_candles,
            symbol=symbol, execution_cost_config=execution_cost_config,
        )
        short_ranking = _enrich_best_with_in_out_sample(
            short_ranking, candles=candles,
            initial_capital=initial_capital, min_candles=min_candles,
            symbol=symbol, execution_cost_config=execution_cost_config,
        )
        for rk in (long_ranking, short_ranking):
            if rk and rk[0].overfitting_warning:
                warnings.append(f"overfitting_suspected_{rk[0].side}")

    long_rec = _build_side_recommendation("long", long_ranking)
    short_rec = _build_side_recommendation("short", short_ranking)

    # Combined + overall recommendation.
    long_ok = long_rec.enabled_recommendation
    short_ok = short_rec.enabled_recommendation
    any_data = bool(long_ranking) or bool(short_ranking)
    any_sample = any(
        r.total_trades >= MIN_TRADES_FOR_ROBUSTNESS
        for r in (list(long_ranking) + list(short_ranking))
    )

    if not any_data or not any_sample:
        combined = "insufficient_data"
        overall = "insufficient_data"
    elif long_ok and short_ok:
        combined = "long_short"
        overall = "switch_candidate"
    elif long_ok and not short_ok:
        combined = "long_only"
        # current strategy ja eh long-only; manter se config igual.
        overall = "adjust"
    elif short_ok and not long_ok:
        combined = "short_only"
        overall = "switch_candidate"
    else:
        combined = "keep_current"
        overall = "keep"

    comparison: Tuple[Mapping[str, Any], ...] = ()
    if include_strategy_comparison:
        comparison = tuple(
            MappingProxyType(row) for row in compare_strategies(
                candles=candles, initial_capital=initial_capital,
                min_candles=min_candles, symbol=symbol,
                execution_cost_config=execution_cost_config,
            )
        )

    return AdvisorReport(
        symbol=symbol, timeframe=timeframe, evaluated_at=now,
        current_strategy=current_strategy,
        candidate_strategy="trend_pullback_bidirectional",
        current_config=MappingProxyType(dict(current_config or {})),
        recommendation=overall,
        long=long_rec, short=short_rec,
        combined_recommendation=combined,
        warnings=tuple(warnings),
        candles_evaluated=candles_evaluated,
        profile=profile,
        strategy_comparison=comparison,
    )


__all__ = [
    "MIN_TRADES_FOR_ROBUSTNESS",
    "MIN_PROFIT_FACTOR_ENABLE",
    "MAX_ACCEPTABLE_DRAWDOWN_PCT",
    "ParameterEvalResult",
    "SideRecommendation",
    "AdvisorReport",
    "default_long_grid",
    "default_short_grid",
    "run_parameter_advisor",
    # FASE 33 - aditivos
    "compare_strategies",
    "detect_overfitting",
    "stability_score",
]
