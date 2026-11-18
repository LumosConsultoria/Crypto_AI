"""
MarketEvent - modelo normalizado de evento de prediction market (FASE 34)
==========================================================================
Representa UM evento/outcome de prediction market (ex.: Polymarket)
normalizado para consumo read-only pelo ecossistema.

⚠️  INTELIGENCIA/CONTEXTO/RESEARCH apenas. NUNCA gera BUY/SELL,
    NUNCA autoriza ordem, NUNCA executa aposta.
⚠️  Frozen, JSON-serializavel, ZERO secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


_VALID_CATEGORIES = (
    "macro", "rates", "inflation", "fed", "cpi", "payroll", "etf",
    "regulation", "geopolitics", "election", "war", "crypto", "other",
)


@dataclass(frozen=True)
class MarketEvent:
    """Evento normalizado de prediction market. Read-only."""

    market_id: str
    event_title: str
    category: str
    outcome: str
    probability: float                    # 0..1
    probability_change_1h: float = 0.0    # pontos percentuais
    probability_change_24h: float = 0.0   # pontos percentuais
    volume: float = 0.0
    liquidity: float = 0.0
    spread: float = 0.0
    last_updated: Optional[datetime] = None
    relevance_score: float = 0.0           # 0..1
    btc_relevance_score: float = 0.0       # 0..1
    risk_flag: Optional[str] = None
    summary: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.market_id, str) or not self.market_id.strip():
            raise ValueError("market_id deve ser string nao-vazia")
        if not isinstance(self.event_title, str) or \
                not self.event_title.strip():
            raise ValueError("event_title deve ser string nao-vazia")
        if self.category not in _VALID_CATEGORIES:
            raise ValueError(
                f"category invalida: {self.category!r}; "
                f"aceitas: {list(_VALID_CATEGORIES)}"
            )
        if not (0.0 <= self.probability <= 1.0):
            raise ValueError(
                f"probability em [0,1]: {self.probability}"
            )
        for score_field in ("relevance_score", "btc_relevance_score"):
            val = getattr(self, score_field)
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"{score_field} em [0,1]: {val}")
        if self.volume < 0 or self.liquidity < 0 or self.spread < 0:
            raise ValueError("volume/liquidity/spread devem ser >= 0")
        if self.last_updated is not None and \
                self.last_updated.tzinfo is None:
            object.__setattr__(
                self, "last_updated",
                self.last_updated.replace(tzinfo=timezone.utc),
            )

    def to_dict(self) -> dict:
        return {
            "market_id": self.market_id,
            "event_title": self.event_title,
            "category": self.category,
            "outcome": self.outcome,
            "probability": float(self.probability),
            "probability_change_1h": float(self.probability_change_1h),
            "probability_change_24h": float(self.probability_change_24h),
            "volume": float(self.volume),
            "liquidity": float(self.liquidity),
            "spread": float(self.spread),
            "last_updated": (
                self.last_updated.isoformat()
                if self.last_updated is not None else None
            ),
            "relevance_score": float(self.relevance_score),
            "btc_relevance_score": float(self.btc_relevance_score),
            "risk_flag": self.risk_flag,
            "summary": self.summary,
        }


__all__ = ["MarketEvent"]
