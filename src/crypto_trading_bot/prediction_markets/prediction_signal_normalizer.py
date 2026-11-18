"""
PredictionSignalNormalizer (FASE 34)
=====================================
Normaliza payloads brutos (dict) de prediction markets em MarketEvent.

⚠️  PURO/OFFLINE: nao chama rede. Recebe dicts ja obtidos por um
    client read-only (ou fixtures em teste) e valida/normaliza.
⚠️  Payload bruto NUNCA eh repassado adiante: apenas campos
    normalizados e seguros saem daqui (sem headers/secrets).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional

from crypto_trading_bot.prediction_markets.market_event_model import (
    MarketEvent,
)
from crypto_trading_bot.prediction_markets.prediction_market_risk_flags \
    import derive_risk_flags, highest_priority_flag


_CATEGORY_KEYWORDS = {
    "fed": "fed", "rate": "rates", "juro": "rates",
    "inflation": "inflation", "inflacao": "inflation",
    "cpi": "cpi", "payroll": "payroll", "etf": "etf",
    "regulation": "regulation", "regulacao": "regulation", "sec ": "regulation",
    "election": "election", "eleicao": "election",
    "war": "war", "guerra": "war",
    "bitcoin": "crypto", "btc": "crypto", "crypto": "crypto",
}


def _infer_category(title: str, explicit: Optional[str]) -> str:
    if explicit:
        return str(explicit).strip().lower()
    low = f" {title.lower()} "
    for keyword, category in _CATEGORY_KEYWORDS.items():
        if keyword in low:
            return category
    return "other"


def _parse_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def normalize_raw_event(raw: Mapping[str, Any]) -> Optional[MarketEvent]:
    """Normaliza UM payload bruto em MarketEvent.

    Retorna None para payloads invalidos/incompletos (nunca levanta
    por dado ruim de terceiro; o ecossistema segue sem o evento).
    """
    try:
        market_id = str(raw.get("market_id") or raw.get("id") or "").strip()
        title = str(
            raw.get("event_title") or raw.get("title") or
            raw.get("question") or ""
        ).strip()
        if not market_id or not title:
            return None
        probability = float(
            raw.get("probability", raw.get("price", 0.0)) or 0.0
        )
        probability = min(1.0, max(0.0, probability))
        category = _infer_category(title, raw.get("category"))
        btc_rel = float(raw.get("btc_relevance_score", 0.0) or 0.0)
        if category == "crypto" and btc_rel == 0.0:
            btc_rel = 0.8
        event = MarketEvent(
            market_id=market_id,
            event_title=title[:200],
            category=category,
            outcome=str(raw.get("outcome", "yes"))[:80],
            probability=probability,
            probability_change_1h=float(
                raw.get("probability_change_1h", 0.0) or 0.0
            ),
            probability_change_24h=float(
                raw.get("probability_change_24h", 0.0) or 0.0
            ),
            volume=max(0.0, float(raw.get("volume", 0.0) or 0.0)),
            liquidity=max(0.0, float(raw.get("liquidity", 0.0) or 0.0)),
            spread=max(0.0, float(raw.get("spread", 0.0) or 0.0)),
            last_updated=_parse_ts(raw.get("last_updated")),
            relevance_score=min(1.0, max(0.0, float(
                raw.get("relevance_score", 0.0) or 0.0
            ))),
            btc_relevance_score=min(1.0, max(0.0, btc_rel)),
            risk_flag=None,
            summary=str(raw.get("summary", ""))[:200],
        )
    except (ValueError, TypeError):
        return None
    # Deriva risk_flag de maior prioridade
    flags = derive_risk_flags(event)
    top = highest_priority_flag(flags)
    if top is not None:
        from dataclasses import replace
        event = replace(event, risk_flag=top)
    return event


def normalize_raw_events(
    raw_events: List[Mapping[str, Any]],
) -> List[MarketEvent]:
    """Normaliza lista de payloads, descartando invalidos."""
    out: List[MarketEvent] = []
    for raw in raw_events or []:
        if not isinstance(raw, Mapping):
            continue
        event = normalize_raw_event(raw)
        if event is not None:
            out.append(event)
    return out


__all__ = ["normalize_raw_event", "normalize_raw_events"]
