"""
PredictionContextAdapter (FASE 32/34)
======================================
Adapta PredictionMarketContext (FASE 34, read-only) para o payload
sanitizado consumido pela IA (FASE 32).

⚠️  Read-only: o adapter apenas LE o contexto e produz um dict
    consultivo. Nunca altera sinal/risco/perfil/estrategia.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from crypto_trading_bot.ai_assistant.context_builder import sanitize_for_ai


def adapt_prediction_context_for_ai(
    prediction_context: Optional[Any],
) -> Optional[Dict[str, Any]]:
    """Converte PredictionMarketContext -> dict sanitizado para a IA.

    Aceita o objeto (duck-typed com to_dict()) ou dict ja serializado.
    Retorna None quando contexto ausente/desabilitado — a IA opera
    sem contexto de prediction nesses casos.
    """
    if prediction_context is None:
        return None
    if isinstance(prediction_context, dict):
        data = dict(prediction_context)
    else:
        to_dict = getattr(prediction_context, "to_dict", None)
        if not callable(to_dict):
            return None
        try:
            data = to_dict()
        except Exception:  # noqa: BLE001
            return None
    if not data.get("enabled", False):
        return None
    # Reduz eventos ao essencial consultivo (titulo/categoria/prob/flag).
    events = []
    for ev in (data.get("btc_relevant_events") or [])[:10]:
        if not isinstance(ev, dict):
            continue
        events.append({
            "event_title": ev.get("event_title"),
            "category": ev.get("category"),
            "probability": ev.get("probability"),
            "probability_change_24h": ev.get("probability_change_24h"),
            "volume": ev.get("volume"),
            "risk_flag": ev.get("risk_flag"),
        })
    adapted = {
        "provider": data.get("provider"),
        "mode": data.get("mode"),
        "stale": bool(data.get("stale", False)),
        "age_seconds": data.get("age_seconds"),
        "risk_flags": list(data.get("risk_flags") or []),
        "summary": data.get("summary"),
        "events_considered": data.get("events_considered", 0),
        "btc_relevant_events": events,
    }
    return sanitize_for_ai(adapted)


__all__ = ["adapt_prediction_context_for_ai"]
