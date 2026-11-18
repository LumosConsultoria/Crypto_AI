"""
SL Calibration Advisor (FASE 36 pos-demo 3)
============================================
Compara, OFFLINE, os tres caminhos de calibracao do stop loss frente
ao piso do RiskEngine (min_stop_loss_pct), SEM baixar o piso e SEM
otimizacao cega por P&L:

    1. Conservador  - manter estrategia; aguardar regime de maior vol.
    2. Moderado     - min_stop_loss_pct na estrategia (rejeicao tecnica
                      pre-RiskEngine) e/ou plan_risk_aware_stop.
    3. Arrojado     - aumentar stop_atr_multiplier (1.5/1.6/1.75/2.0).

⚠️  A parte DECISION-GRADE (SL% x piso, taxa de rejeicao, risco USD)
    e DETERMINISTICA: depende so do ATR, nao de dataset historico.
⚠️  Metricas de trade (win_rate/P&L/drawdown) vem do BacktestEngine.
    Em dados SINTETICOS sao ILUSTRATIVAS (mecanismo), NUNCA evidencia
    de performance — exigem walk-forward em dados reais.
⚠️  ZERO rede, ZERO ordem. Reusa evaluate_strategy + plan_risk_aware_stop.
"""

from __future__ import annotations

import math
from typing import (
    Any, Callable, Dict, List, Mapping, Optional, Sequence,
)


_DEFAULT_MULTIPLIERS = (1.5, 1.6, 1.75, 2.0)


def _atr_pct_series(candles: Sequence) -> List[float]:
    """ATR%/preco por candle (period 14, via FeatureEngine). Ignora NaN."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.strategies \
        .trend_pullback_bidirectional_strategy import (
            build_trend_pullback_bidirectional_spec,
        )
    spec = build_trend_pullback_bidirectional_spec()
    fe = FeatureEngine.from_strategy_spec(spec)
    feats = fe.compute(list(candles))
    atr_series = feats.get(f"atr_{fe._atr_period}")
    out: List[float] = []
    if atr_series is None:
        return out
    closes = [float(getattr(c, "close", 0.0)) for c in candles]
    n = min(len(closes), len(atr_series))
    for i in range(n):
        try:
            atr = float(atr_series.iloc[i])
        except (IndexError, TypeError, ValueError):
            continue
        close = closes[i]
        if close > 0 and not math.isnan(atr) and atr > 0:
            out.append(atr / close)
    return out


def _pctile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))
    return s[idx]


def _signal_sl_stats(
    atr_pcts: List[float], *, multiplier: float,
    min_stop_loss_pct: float, position_size_usd: float,
) -> dict:
    """Estatistica determinISTIca SL% x piso para um multiplicador.

    Cada candle com ATR valido eh um proxy de 'oportunidade': SL% =
    mult*ATR%. Conta quantos cairiam abaixo do piso (rejeicao tecnica
    stop_loss_below_minimum).
    """
    total = len(atr_pcts)
    sl_pcts = [multiplier * a for a in atr_pcts]
    below = [s for s in sl_pcts if s < min_stop_loss_pct]
    approved = [s for s in sl_pcts if s >= min_stop_loss_pct]
    rej = len(below)
    median_sl = _pctile(sl_pcts, 0.5)
    # risco USD ~ sl_pct * notional (qty = notional/entry).
    median_risk_usd = (
        median_sl * position_size_usd if median_sl is not None else None
    )
    return {
        "stop_atr_multiplier": multiplier,
        "total_signals": total,
        "approved_signals": len(approved),
        "rejected_below_min": rej,
        "rejection_pct": round(rej / total * 100.0, 2) if total else None,
        "median_sl_pct": round(median_sl * 100.0, 4)
        if median_sl is not None else None,
        "min_sl_pct_required": round(min_stop_loss_pct * 100.0, 4),
        "median_risk_usd": round(median_risk_usd, 4)
        if median_risk_usd is not None else None,
    }


def _backtest_variant(
    *, config_override: Mapping[str, Any], candles: Sequence,
    initial_capital: float, min_candles: int, symbol: str,
) -> dict:
    """Roda evaluate_strategy (RiskEngine real, piso aplicado).

    Em dados sinteticos: mecanismo, NAO performance.
    """
    from crypto_trading_bot.research.strategy_research import (
        evaluate_strategy,
    )
    from crypto_trading_bot.strategies \
        .trend_pullback_bidirectional_strategy import (
            build_trend_pullback_bidirectional_spec,
        )
    spec = build_trend_pullback_bidirectional_spec()
    try:
        ev = evaluate_strategy(
            spec=spec, candles=list(candles),
            config_override=dict(config_override),
            initial_capital=initial_capital, min_candles=min_candles,
            symbol=symbol,
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    rep = ev.single_report
    return {
        "total_trades": int(getattr(rep, "total_trades", 0) or 0),
        "risk_blocked_count": int(
            getattr(rep, "risk_blocked_count", 0) or 0
        ),
        "win_rate": float(getattr(rep, "win_rate", 0.0) or 0.0),
        "total_pnl_usd": float(getattr(rep, "total_pnl_usd", 0.0) or 0.0),
        "max_drawdown_pct": float(
            getattr(rep, "max_drawdown_pct", 0.0) or 0.0
        ),
        "avg_win_usd": float(getattr(rep, "avg_win_usd", 0.0) or 0.0),
        "avg_loss_usd": float(getattr(rep, "avg_loss_usd", 0.0) or 0.0),
        "profit_factor": getattr(rep, "profit_factor", None),
        "expectancy_usd": float(
            getattr(rep, "expectancy_usd", 0.0) or 0.0
        ),
    }


def analyze_sl_calibration(
    *,
    candles: Sequence,
    data_source: str = "synthetic",
    min_stop_loss_pct: float = 0.005,
    stop_atr_multipliers: Sequence[float] = _DEFAULT_MULTIPLIERS,
    position_size_usd: float = 200.0,
    risk_reward_ratio: float = 2.0,
    max_risk_per_trade_usd: Optional[float] = None,
    initial_capital: float = 5000.0,
    min_candles: int = 60,
    symbol: str = "BTCUSDT",
    run_backtests: bool = True,
    real_dataset_available: bool = False,
    walk_forward_available: bool = False,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> dict:
    """Compara os 3 caminhos de calibracao SL x piso. Offline.

    data_source: 'synthetic' | 'csv:<path>' | 'real' — rotula a
    confiabilidade das metricas de trade.
    real_dataset_available/walk_forward_available: vindos do Data
    Readiness (FASE 36.x). Sem dataset real validado, NENHUMA
    recomendacao arrojada eh marcada como pronta para uso real.
    max_risk_per_trade_usd: se None, o teste de orcamento e PULADO
    (operator input V2 ausente — NUNCA inventado).
    """
    atr_pcts = _atr_pct_series(candles)
    synthetic = not str(data_source).lower().startswith(
        ("csv", "real"),
    )

    if len(atr_pcts) < max(20, min_candles // 2):
        return {
            "schema": "sl_calibration_v1",
            "status": "insufficient_data",
            "data_source": data_source,
            "candles_with_valid_atr": len(atr_pcts),
            "message": (
                "ATR valido insuficiente para analise. Forneca mais "
                "candles (real via --from-csv) — nenhuma busca por API."
            ),
        }

    atr_summary = {
        "candles_with_valid_atr": len(atr_pcts),
        "median_atr_pct": round((_pctile(atr_pcts, 0.5) or 0.0) * 100, 4),
        "p10_atr_pct": round((_pctile(atr_pcts, 0.1) or 0.0) * 100, 4),
        "p90_atr_pct": round((_pctile(atr_pcts, 0.9) or 0.0) * 100, 4),
        "min_atr_pct": round(min(atr_pcts) * 100, 4),
        "max_atr_pct": round(max(atr_pcts) * 100, 4),
    }

    # --- Estatistica determinISTIca SL% x piso por multiplicador ---
    sl_stats = [
        _signal_sl_stats(
            atr_pcts, multiplier=m,
            min_stop_loss_pct=min_stop_loss_pct,
            position_size_usd=position_size_usd,
        )
        for m in stop_atr_multipliers
    ]
    current = next(
        (s for s in sl_stats if abs(s["stop_atr_multiplier"] - 1.5)
         < 1e-9), sl_stats[0],
    )

    # --- Planner risk-aware na mediana do ATR (Path moderado) ---
    from crypto_trading_bot.strategies \
        .trend_pullback_bidirectional_strategy import plan_risk_aware_stop
    median_atr_pct = (_pctile(atr_pcts, 0.5) or 0.0)
    median_atr_abs = median_atr_pct * 100.0  # ATR abs p/ entry=100? no
    entry_ref = 100.0
    planner = plan_risk_aware_stop(
        side="buy", entry=entry_ref, atr=median_atr_pct * entry_ref,
        stop_atr_multiplier=1.5, risk_reward_ratio=risk_reward_ratio,
        min_stop_loss_pct=min_stop_loss_pct,
        position_size_usd=position_size_usd,
        max_risk_per_trade_usd=max_risk_per_trade_usd,
    )
    # Quantos candles o planner CLAMP-aria ao piso e quantos exigiriam
    # reducao de sizing (so se houver orcamento informado).
    clamp_count = sum(
        1 for a in atr_pcts if 1.5 * a < min_stop_loss_pct
    )
    sizing_reduction_needed = 0
    if max_risk_per_trade_usd is not None:
        # risco no piso = floor * notional (constante p/ todos clamps).
        floor_risk_usd = min_stop_loss_pct * position_size_usd
        if floor_risk_usd > max_risk_per_trade_usd + 1e-9:
            sizing_reduction_needed = clamp_count

    # --- Backtests (mecanismo; sinteticos = ilustrativo) ---
    # ⚠️  PERFORMANCE: cada variante chama BacktestEngine.run, que
    #     recomputa features por janela (O(n^2) no numero de candles).
    #     Com datasets grandes (dezenas de milhares de candles) isto fica
    #     caro -> use --diagnostic-only (run_backtests=False, O(n)) ou
    #     limite os candles (--max-candles / range). A parte
    #     DETERMINISTICA (SL% x piso) acima ja respondeu a pergunta de
    #     calibracao sem rodar backtest.
    backtests: Dict[str, Any] = {}
    backtests_partial = False
    if run_backtests:
        variants: List[tuple] = [
            ("current_1.5", {"stop_atr_multiplier": 1.5}),
            ("strategy_floor_1.5", {
                "stop_atr_multiplier": 1.5,
                "min_stop_loss_pct": min_stop_loss_pct,
            }),
        ]
        for m in stop_atr_multipliers:
            variants.append((f"mult_{m}", {"stop_atr_multiplier": m}))
        total_v = len(variants)
        for idx, (name, override) in enumerate(variants, start=1):
            if progress_callback is not None:
                progress_callback(name, idx, total_v)
            try:
                backtests[name] = _backtest_variant(
                    config_override=override, candles=candles,
                    initial_capital=initial_capital,
                    min_candles=min_candles, symbol=symbol,
                )
            except KeyboardInterrupt:
                # Nunca silencioso: registra parcial e segue para emitir
                # o relatorio determinISTIco ja calculado.
                backtests_partial = True
                backtests[name] = {"error": "interrupted_by_user"}
                backtests["_interrupted_at"] = name
                break

    # --- Menor multiplicador que zera (ou minimiza) rejeicao ---
    smallest_clearing = None
    for s in sorted(sl_stats, key=lambda x: x["stop_atr_multiplier"]):
        if (s["rejection_pct"] or 0) == 0:
            smallest_clearing = s["stop_atr_multiplier"]
            break
    implied_mult_for_floor = (
        round(min_stop_loss_pct / median_atr_pct, 4)
        if median_atr_pct > 0 else None
    )

    # FASE 36.x: o arrojado so fica pronto p/ uso real com dataset
    # real validado E walk-forward disponivel.
    aggressive_ready_for_real = bool(
        real_dataset_available and walk_forward_available
        and not synthetic
    )
    recommendations = _build_recommendations(
        current=current, sl_stats=sl_stats, planner=planner,
        clamp_count=clamp_count, total=len(atr_pcts),
        smallest_clearing=smallest_clearing,
        implied_mult_for_floor=implied_mult_for_floor,
        synthetic=synthetic, max_risk_per_trade_usd=max_risk_per_trade_usd,
        aggressive_ready_for_real=aggressive_ready_for_real,
    )

    return {
        "schema": "sl_calibration_v1",
        "status": "ok",
        "data_source": data_source,
        "real_dataset_available": bool(real_dataset_available),
        "walk_forward_available": bool(walk_forward_available),
        "synthetic_only": bool(synthetic),
        "aggressive_ready_for_real": aggressive_ready_for_real,
        "synthetic_warning": (
            "Dados sinteticos: metricas de trade sao ILUSTRATIVAS "
            "(mecanismo), NAO performance. Walk-forward em dados reais "
            "obrigatorio antes de uso real." if synthetic else None
        ),
        "min_sl_pct_required": round(min_stop_loss_pct * 100.0, 4),
        "atr_summary": atr_summary,
        "implied_multiplier_to_clear_floor": implied_mult_for_floor,
        "smallest_multiplier_clearing_floor": smallest_clearing,
        "sl_stats_by_multiplier": sl_stats,
        "planner_at_median_atr": planner,
        "planner_clamp_count": clamp_count,
        "planner_sizing_reduction_needed": sizing_reduction_needed,
        "budget_check": (
            "skipped: max_risk_per_trade_usd ausente (operator input "
            "V2)" if max_risk_per_trade_usd is None else "applied"
        ),
        "backtests_mechanism_only": backtests,
        "backtests_ran": bool(run_backtests),
        "backtests_partial": backtests_partial,
        "recommendations": recommendations,
        "note": (
            "NAO baixa o piso; NAO autoaplica; recomendacoes exigem "
            "backtest/walk-forward em dados reais antes de uso."
        ),
    }


def _build_recommendations(
    *, current, sl_stats, planner, clamp_count, total,
    smallest_clearing, implied_mult_for_floor, synthetic,
    max_risk_per_trade_usd, aggressive_ready_for_real=False,
) -> list:
    cur_rej = current.get("rejection_pct")
    return [
        {
            "profile": "conservador",
            "action": "wait_higher_volatility_regime",
            "detail": (
                f"Manter estrategia. No regime amostrado, "
                f"{cur_rej}% dos sinais (mult 1.5) ficam abaixo do "
                "piso e seguem bloqueados (zero risco novo). Mais "
                "seguro: aguardar ATR maior."
            ),
            "needs_backtest": True,
            "needs_walk_forward": True,
        },
        {
            "profile": "moderado",
            "action": "enable_strategy_min_stop_loss_pct_or_planner",
            "detail": (
                "Ativar min_stop_loss_pct na estrategia (= piso) para "
                "rejeitar sinais doomed ANTES do RiskEngine (mesma "
                "seletividade do atual, porem com trace explicito). "
                "plan_risk_aware_stop fica como DIAGNOSTICO: na mediana "
                f"do ATR ele clampa o SL ao piso ({planner.get('sl_pct')}%"
                f"), risco_usd~{planner.get('risk_usd')}, "
                f"within_budget={planner.get('within_risk_budget')}."
            ),
            "suggested_min_stop_loss_pct": round(
                current["min_sl_pct_required"] / 100.0, 6,
            ),
            "planner_clamp_count": clamp_count,
            "needs_backtest": True,
            "needs_walk_forward": True,
        },
        {
            "profile": "arrojado",
            "action": "increase_stop_atr_multiplier",
            "detail": (
                "Aumentar stop_atr_multiplier ate o SL cruzar o piso. "
                f"Menor multiplicador que zera a rejeicao na amostra: "
                f"{smallest_clearing}. Multiplicador implicito p/ a "
                f"mediana do ATR: ~{implied_mult_for_floor}. Risco "
                "permanece pequeno, mas SL mais largo muda R:R/expectancy"
                " — exige backtest/walk-forward em dados REAIS."
            ),
            "smallest_multiplier_clearing_floor": smallest_clearing,
            "needs_backtest": True,
            "needs_walk_forward": True,
            "ready_for_real_use": bool(aggressive_ready_for_real),
            "blocked_reason": (
                None if aggressive_ready_for_real
                else "dataset real + walk-forward ausentes "
                     "(FASE 36.x Data Readiness)"
            ),
        },
        {
            "profile": "_safest_for_next_demo",
            "action": (
                "conservador+moderado" if synthetic else "review"
            ),
            "detail": (
                "Mais seguro para a PROXIMA demo: combinar conservador "
                "(aguardar regime) com moderado (ativar "
                "min_stop_loss_pct para trace explicito). Arrojado "
                "(multiplicador maior) so apos walk-forward em dados "
                "reais — ausentes no projeto agora."
            ),
            "needs_backtest": True,
            "needs_walk_forward": True,
        },
    ]


__all__ = ["analyze_sl_calibration"]
