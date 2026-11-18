"""
Backtest Operational Runner (FASE 37 Parte C/H/I)
=================================================
Executa um backtest OPERACIONAL com paridade de demo (RiskEngine
soberano, custos, perfil, estrategia validada) porem SEM execucao real.
Reaproveita o motor validado (`evaluate_strategy` -> BacktestEngine) para
a matematica de trades e adiciona a camada operacional:

  * Estrategia validada contra registry + perfil (Parte C).
  * Decision Trace por trade executado (Parte H), com diagnostico SL.
  * Disponibilidade de contexto externo resolvida SEM look-ahead e SEM
    inventar (Parte E) — agregada por kind no relatorio.
  * Relatorio que distingue enabled vs context_available vs
    decision_impact (Parte F/I).

⚠️  ZERO ordem real, ZERO API, ZERO secret. Execucao 100% simulada.
⚠️  O contexto externo eh AUDITADO (disponibilidade), mas NAO altera a
    decisao do motor validado nesta versao: `decision_impact=0` por
    construcao (jamais inventado). Ver nota no relatorio.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Callable, List, Optional, Sequence

from crypto_trading_bot.backtest_operational.context_availability import (
    CONTEXT_KINDS,
    ContextAvailability,
    ContextDataset,
    resolve_context,
)
from crypto_trading_bot.backtest_operational.execution_context import (
    BacktestContextError,
    BacktestExecutionContext,
)
from crypto_trading_bot.backtest_operational.report import (
    BacktestOperationalReport,
    ContextAvailabilitySummary,
)
from crypto_trading_bot.backtest_operational.strategy_registry import (
    resolve_strategy_spec,
)
from crypto_trading_bot.decision_trace.trace_model import (
    DecisionTraceEntry,
    FinalDecision,
)

_CTX_TO_TRACE_FLAG = {
    "ai": "ai_used",
    "market_intelligence": "market_intelligence_used",
    "news": "news_used",
    "funding": "funding_used",
    "open_interest": "open_interest_used",
    "orderbook": "orderbook_used",
}


class BacktestRunnerError(Exception):
    """Erro de execucao do backtest operacional."""


def _required(ctx: BacktestExecutionContext, kind: str) -> bool:
    return kind in (ctx.required_context_kinds or ())


def run_operational_backtest(
    ctx: BacktestExecutionContext,
    candles: Sequence[Any],
    *,
    symbol: str,
    timeframe: str,
    context_dataset: Optional[ContextDataset] = None,
    profile_allowed: Optional[Sequence[str]] = None,
    registry: Any = None,
    source_type: str = "csv",
    dataset_checksum: Optional[str] = None,
    min_candles: int = 50,
    max_decision_traces: int = 500,
    progress_every: int = 0,
    on_progress: Optional[Callable[[int, int], None]] = None,
    precompute_features: bool = True,
    backtest_progress_every: int = 0,
    on_backtest_progress: Optional[Callable[[dict], None]] = None,
) -> BacktestOperationalReport:
    """Roda o backtest operacional e retorna o relatorio consolidado.

    FASE 37.1: usa o motor validado com precompute O(n) (identico, sem
    look-ahead) e heartbeat durante o loop pesado. KeyboardInterrupt
    produz relatorio PARCIAL sanitizado (nunca traceback cru).
    """
    if ctx.capital_usd <= 0:
        raise BacktestRunnerError(
            "capital_usd obrigatorio (> 0); informe --capital (sem "
            "default inventado)."
        )
    if not candles:
        raise BacktestRunnerError("nenhum candle fornecido")

    spec = resolve_strategy_spec(
        ctx.strategy, profile_allowed=profile_allowed, registry=registry,
    )

    # Custos de execucao (bps -> fracao). Defaults 0 (disabled).
    cost_cfg = None
    if ctx.fees_bps > 0 or ctx.slippage_bps > 0:
        from crypto_trading_bot.backtesting.execution_costs import (
            ExecutionCostConfig,
        )
        cost_cfg = ExecutionCostConfig(
            fee_pct=ctx.fees_bps / 10000.0,
            slippage_pct=ctx.slippage_bps / 10000.0,
        )

    # --- Motor validado (RiskEngine soberano aplica o piso) ---
    # Constroi o engine diretamente (espelha evaluate_strategy single-run)
    # para acessar progress + relatorio parcial no interrupt.
    from crypto_trading_bot.backtesting import BacktestEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    strategy = spec.factory(dict(spec.default_config))
    engine = BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=ctx.capital_usd),
        feature_engine=FeatureEngine(),
        initial_capital=ctx.capital_usd,
        min_candles=min_candles,
        symbol=symbol,
        execution_cost_config=cost_cfg,
    )

    import time
    backtest_interrupted = False
    _t0 = time.monotonic()
    try:
        rep = engine.run(
            list(candles),
            precompute_features=precompute_features,
            progress_every=backtest_progress_every,
            progress_callback=on_backtest_progress,
        )
    except KeyboardInterrupt:
        # Relatorio PARCIAL (trades fechados ate aqui); nunca traceback cru.
        backtest_interrupted = True
        rep = engine.build_partial_report()
    elapsed_seconds = round(time.monotonic() - _t0, 3)

    # --- Disponibilidade de contexto (anti look-ahead) ---
    if backtest_interrupted:
        # Saida rapida: nao varre contexto; so reflete os toggles.
        avail_summaries = [
            ContextAvailabilitySummary(
                kind=k, enabled=(k in ctx.enabled_context_kinds()))
            for k in CONTEXT_KINDS
        ]
    else:
        avail_summaries = _aggregate_context_availability(
            ctx, candles, context_dataset, min_candles,
            progress_every, on_progress,
        )

    # --- Decision traces por trade executado (Parte H) ---
    traces = _build_trade_traces(
        ctx, rep, symbol, timeframe, context_dataset,
        max_decision_traces,
    )

    warnings: List[str] = []
    notes: List[str] = [
        "context_external_consultivo_sem_efeito_na_decisao_v1: contextos "
        "sao resolvidos/auditados (anti look-ahead), mas NAO alteram a "
        "decisao do motor validado nesta versao; decision_impact=0 por "
        "construcao (jamais inventado).",
        "execucao 100% simulada; nenhuma ordem real foi enviada.",
    ]
    synthetic = source_type in ("synthetic_fake", "synthetic")
    if synthetic:
        warnings.append(
            "dados sinteticos: metricas sao ilustrativas, NAO refletem "
            "mercado real."
        )
    candles_processed = None
    if backtest_interrupted:
        candles_processed = int(engine._run_progress.get("i", 0) or 0) + 1
        warnings.append(
            f"backtest INTERROMPIDO (Ctrl+C) ~candle {candles_processed}/"
            f"{len(candles)}; relatorio PARCIAL (so trades fechados)."
        )
        notes.append(
            "relatorio parcial: posicao aberta nao foi fechada; contexto "
            "nao varrido. Nada autoaplicado."
        )
    # Bloqueio por contexto obrigatorio indisponivel.
    for s in avail_summaries:
        if s.blocked_count > 0:
            warnings.append(
                f"required_context_unavailable: '{s.kind}' obrigatorio "
                f"indisponivel em {s.blocked_count} ponto(s) de decisao."
            )

    first_ts = _iso(candles[0].timestamp)
    last_ts = _iso(candles[-1].timestamp)

    return BacktestOperationalReport(
        strategy=ctx.strategy,
        profile=ctx.profile,
        symbol=symbol,
        timeframe=timeframe,
        rows=len(candles),
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        source_type=source_type,
        dataset_checksum=dataset_checksum,
        execution_context=ctx.to_dict(),
        real_execution_allowed=False,
        total_trades=rep.total_trades,
        winning_trades=rep.winning_trades,
        losing_trades=rep.losing_trades,
        win_rate_pct=rep.win_rate,
        total_pnl_usd=rep.total_pnl_usd,
        max_drawdown_pct=rep.max_drawdown_pct,
        avg_win_usd=rep.avg_win_usd,
        avg_loss_usd=rep.avg_loss_usd,
        profit_factor=rep.profit_factor,
        expectancy_usd=rep.expectancy_usd,
        risk_blocked_count=rep.risk_blocked_count,
        blocked_reasons_summary=dict(
            getattr(rep, "risk_blocked_reasons", {}) or {}),
        final_capital=rep.final_capital,
        total_fees_usd=rep.total_fees_usd,
        total_slippage_usd=rep.total_slippage_usd,
        context_availability=tuple(avail_summaries),
        decision_traces=tuple(t.to_dict() for t in traces),
        decision_trace_count=len(traces),
        partial=backtest_interrupted,
        interrupted=backtest_interrupted,
        candles_processed=candles_processed,
        elapsed_seconds=elapsed_seconds,
        synthetic_data_warning=synthetic,
        warnings=tuple(warnings),
        notes=tuple(notes),
    )


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aggregate_context_availability(
    ctx, candles, dataset, min_candles, progress_every, on_progress,
) -> List[ContextAvailabilitySummary]:
    counts = {
        k: {"dp": 0, "avail": 0, "impact": 0, "unavail": 0,
            "stale": 0, "blocked": 0}
        for k in CONTEXT_KINDS
    }
    enabled = {k: (k in ctx.enabled_context_kinds()) for k in CONTEXT_KINDS}
    total = len(candles)
    start = min(min_candles, total)
    for i in range(start, total):
        ts = candles[i].timestamp
        for k in CONTEXT_KINDS:
            c = counts[k]
            c["dp"] += 1
            av: ContextAvailability = resolve_context(
                kind=k, enabled=enabled[k], dataset=dataset,
                current_ts=ts, required=_required(ctx, k),
                allow_missing=ctx.allow_missing_context,
            )
            if not av.enabled:
                continue
            if av.blocked:
                c["blocked"] += 1
            if av.context_available:
                c["avail"] += 1
                if av.stale:
                    c["stale"] += 1
                if av.decision_impact:
                    c["impact"] += 1
            else:
                c["unavail"] += 1
        if progress_every and on_progress and \
                (i - start + 1) % progress_every == 0:
            on_progress(i - start + 1, total - start)

    return [
        ContextAvailabilitySummary(
            kind=k, enabled=enabled[k],
            decision_points=counts[k]["dp"],
            context_available_count=counts[k]["avail"],
            decision_impact_count=counts[k]["impact"],
            unavailable_count=counts[k]["unavail"],
            stale_count=counts[k]["stale"],
            blocked_count=counts[k]["blocked"],
        )
        for k in CONTEXT_KINDS
    ]


def _build_trade_traces(
    ctx, rep, symbol, timeframe, dataset, max_traces,
) -> List[DecisionTraceEntry]:
    traces: List[DecisionTraceEntry] = []
    for i, tr in enumerate(rep.trades[:max_traces]):
        entry = float(tr.entry_price)
        sl = float(tr.stop_loss_price)
        planned_sl_pct = (
            round(abs(entry - sl) / entry, 6) if entry else None
        )
        ctx_fields = _trace_context_fields(ctx, tr.entry_time, dataset)
        close_reason = (
            tr.close_reason.value if tr.close_reason is not None else None
        )
        traces.append(DecisionTraceEntry(
            trace_id=f"bt-{i}",
            cycle_idx=int(tr.entry_candle_idx),
            timestamp=tr.entry_time,
            strategy_name=ctx.strategy,
            profile_name=ctx.profile,
            symbol=symbol,
            timeframe=timeframe,
            candle_price=entry,
            signal_side=tr.side,
            risk_decision="approved",
            risk_reason="risk_engine_approved_simulated",
            planned_sl=sl,
            planned_tp=(
                float(tr.take_profit_price)
                if tr.take_profit_price is not None else None
            ),
            qty=None,
            notional_usd=float(tr.position_size_usd),
            leverage=ctx.leverage,
            final_decision=FinalDecision.ENTER,
            final_reason=f"executed {tr.side}; close={close_reason}",
            realized_pnl=(
                float(tr.pnl_usd) if tr.pnl_usd is not None else None
            ),
            trade_idx=i,
            planned_sl_pct=planned_sl_pct,
            min_sl_pct_required=ctx.min_stop_loss_pct,
            sl_gap_to_min_pct=(
                round(planned_sl_pct - ctx.min_stop_loss_pct, 6)
                if planned_sl_pct is not None else None
            ),
            **ctx_fields,
        ))
    return traces


def _trace_context_fields(ctx, ts, dataset) -> dict:
    """Marca quais contextos estavam disponiveis no instante do trade.

    Honesto: como o motor validado NAO consome contexto, marcamos
    used=False com motivo; disponibilidade aparece no resumo agregado.
    """
    fields: dict = {}
    for k in CONTEXT_KINDS:
        enabled = k in ctx.enabled_context_kinds()
        flag = _CTX_TO_TRACE_FLAG.get(k)
        if flag is None:  # polymarket nao tem flag dedicada no trace
            continue
        if not enabled:
            fields[flag] = False
            continue
        av = resolve_context(
            kind=k, enabled=True, dataset=dataset, current_ts=ts,
            required=_required(ctx, k),
            allow_missing=ctx.allow_missing_context,
        )
        # disponivel porem nao consumido pelo motor -> used=False.
        fields[flag] = False
    # Motivos agregados de IA/MI nao usados.
    if "ai_used" in fields and not fields["ai_used"]:
        fields["ai_not_used_reason"] = (
            "context_available_not_consumed_by_engine"
            if "ai" in ctx.enabled_context_kinds() else "disabled"
        )
    fields["mi_not_used_reason"] = (
        "context_available_not_consumed_by_engine"
        if ctx.enable_market_intelligence else "disabled"
    )
    return fields


__all__ = [
    "BacktestRunnerError",
    "run_operational_backtest",
]
