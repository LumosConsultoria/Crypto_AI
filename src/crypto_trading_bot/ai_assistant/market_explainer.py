"""
MarketExplainer (FASE 32)
==========================
Explicacoes DETERMINISTICAS (sem LLM, sem rede) sobre o estado do
ciclo: por que HOLD, resumo do sinal, comparacao long vs short.

⚠️  Output e TEXTO consultivo para operador/relatorio. Nunca altera
    sinal/risco. Implementacoes com LLM real (fase futura) devem
    respeitar o mesmo contrato consultivo.
"""

from __future__ import annotations

from typing import Any, Mapping


_HOLD_EXPLANATIONS = {
    "insufficient_candles": (
        "Dados insuficientes: a estrategia exige mais candles do que o "
        "disponivel para calcular EMAs/RSI com confianca."
    ),
    "ema_unavailable": (
        "EMAs indisponiveis (NaN) — series curtas ou dados invalidos."
    ),
    "no_uptrend": (
        "Sem tendencia de alta: EMA rapida nao esta acima da EMA lenta."
    ),
    "no_downtrend": (
        "Sem tendencia de baixa: EMA rapida nao esta abaixo da EMA lenta."
    ),
    "no_pullback_zone": (
        "Preco fora da zona de pullback entre as EMAs."
    ),
    "rsi_overbought": "RSI sobrecomprado: entrada long bloqueada.",
    "rsi_oversold": "RSI sobrevendido: entrada short bloqueada.",
    "position_already_open": "Ja existe posicao aberta; sem nova entrada.",
    "data_quality_failed": "Qualidade de dados reprovada (preco invalido).",
    "no_valid_long_or_short_setup": (
        "Nenhum setup valido em nenhum dos lados neste ciclo."
    ),
    "strategy_inactive": "Estrategia inativa (estado nao-running).",
}


def explain_hold(signal_snapshot: Mapping[str, Any]) -> str:
    """Explica em linguagem clara por que o ciclo ficou em HOLD."""
    reason = str(signal_snapshot.get("hold_reason") or "unknown")
    base = _HOLD_EXPLANATIONS.get(
        reason, f"HOLD por razao nao mapeada: {reason}."
    )
    failed_long = signal_snapshot.get("failed_conditions_long") or []
    failed_short = signal_snapshot.get("failed_conditions_short") or []
    parts = [base]
    if failed_long:
        parts.append(f"Condicoes long reprovadas: {list(failed_long)}.")
    if failed_short:
        parts.append(f"Condicoes short reprovadas: {list(failed_short)}.")
    return " ".join(parts)[:400]


def summarize_signal(signal_snapshot: Mapping[str, Any]) -> str:
    """Resumo tecnico curto do sinal avaliado."""
    side = str(signal_snapshot.get("signal_side") or "hold")
    sym = signal_snapshot.get("symbol", "?")
    ema_f = signal_snapshot.get("ema_fast_value")
    ema_s = signal_snapshot.get("ema_slow_value")
    rsi = signal_snapshot.get("rsi_value")
    close = signal_snapshot.get("last_close")
    return (
        f"{sym}: side={side} close={close} ema_fast={ema_f} "
        f"ema_slow={ema_s} rsi={rsi}"
    )[:300]


def compare_long_short(signal_snapshot: Mapping[str, Any]) -> str:
    """Comparacao consultiva das condicoes long vs short do ciclo."""
    lc = signal_snapshot.get("long_conditions") or {}
    sc = signal_snapshot.get("short_conditions") or {}
    long_met = sum(1 for v in lc.values() if v is True)
    short_met = sum(1 for v in sc.values() if v is True)
    return (
        f"long_conditions_met={long_met}/{len(lc) or 0}; "
        f"short_conditions_met={short_met}/{len(sc) or 0}"
    )


__all__ = ["compare_long_short", "explain_hold", "summarize_signal"]
