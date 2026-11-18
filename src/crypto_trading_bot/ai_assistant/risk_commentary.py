"""
RiskCommentary (FASE 32)
=========================
Comentarios DETERMINISTICOS sobre risco do ciclo. CONSULTIVO.

⚠️  NUNCA altera RiskResult. Se o RiskEngine reprovou, o comentario
    apenas explica; a reprovacao permanece soberana.
"""

from __future__ import annotations

from typing import Any, List, Mapping


def build_risk_commentary(
    *,
    risk_summary: Mapping[str, Any],
    signal_snapshot: Mapping[str, Any],
    prediction_context: Mapping[str, Any] | None = None,
) -> List[str]:
    """Gera lista de comentarios/warnings consultivos sobre risco."""
    notes: List[str] = []

    approved = bool(risk_summary.get("approved", False))
    if not approved:
        notes.append(
            "RiskEngine reprovou o sinal — decisao soberana mantida: "
            + str(risk_summary.get("reason", ""))[:120]
        )

    rsi = signal_snapshot.get("rsi_value")
    if isinstance(rsi, (int, float)):
        if rsi >= 80:
            notes.append(
                f"RSI extremo ({rsi}): risco de reversao elevado."
            )
        elif rsi <= 20:
            notes.append(
                f"RSI extremo ({rsi}): risco de reversao elevado."
            )

    atr = signal_snapshot.get("atr_value")
    close = signal_snapshot.get("last_close")
    if isinstance(atr, (int, float)) and isinstance(close, (int, float)) \
            and close > 0:
        atr_pct = (atr / close) * 100.0
        if atr_pct > 2.0:
            notes.append(
                f"Volatilidade incomum: ATR {atr_pct:.2f}% do preco."
            )

    if prediction_context:
        flags = prediction_context.get("risk_flags") or []
        if flags:
            notes.append(
                "Prediction markets sinalizam risco macro: "
                f"{list(flags)[:4]}"
            )
        if prediction_context.get("stale"):
            notes.append(
                "Contexto de prediction markets esta STALE — tratar "
                "como alerta, nao como dado confiavel."
            )

    return notes


__all__ = ["build_risk_commentary"]
