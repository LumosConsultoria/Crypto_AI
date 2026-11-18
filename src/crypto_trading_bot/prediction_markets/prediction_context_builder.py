"""
PredictionContextBuilder (FASE 34)
===================================
Constroi PredictionMarketContext consolidado a partir de MarketEvents
normalizados.

⚠️  READ-ONLY/ADVISORY: o contexto NUNCA gera BUY/SELL, NUNCA altera
    TradingSignal/RiskResult/perfil/estrategia, NUNCA executa.
    Apenas enriquece IA (advisory) e relatorios.
⚠️  Frozen, JSON-serializavel, sem secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from crypto_trading_bot.prediction_markets.market_event_model import (
    MarketEvent,
)


_VALID_MODES = ("disabled", "read_only", "advisory")
_DEFAULT_MAX_AGE_SECONDS = 300.0
_BTC_RELEVANT_THRESHOLD = 0.5


@dataclass(frozen=True)
class PredictionMarketContext:
    """Contexto consolidado de prediction markets. Consultivo."""

    enabled: bool
    provider: str
    mode: str                                  # disabled|read_only|advisory
    btc_relevant_events: Tuple[MarketEvent, ...] = field(
        default_factory=tuple
    )
    risk_flags: Tuple[str, ...] = field(default_factory=tuple)
    stale: bool = False
    age_seconds: float = 0.0
    summary: Optional[str] = None
    events_considered: int = 0

    def __post_init__(self) -> None:
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode invalido: {self.mode!r}; aceitos: {_VALID_MODES}"
            )
        if not isinstance(self.btc_relevant_events, tuple):
            object.__setattr__(
                self, "btc_relevant_events",
                tuple(self.btc_relevant_events),
            )
        if not isinstance(self.risk_flags, tuple):
            object.__setattr__(
                self, "risk_flags", tuple(self.risk_flags),
            )

    @property
    def has_critical_flags(self) -> bool:
        return bool(self.risk_flags)

    def to_dict(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "provider": self.provider,
            "mode": self.mode,
            "events_considered": int(self.events_considered),
            "btc_relevant_events": [
                e.to_dict() for e in self.btc_relevant_events
            ],
            "risk_flags": list(self.risk_flags),
            "stale": bool(self.stale),
            "age_seconds": float(self.age_seconds),
            "summary": self.summary,
        }


def disabled_context(provider: str = "none") -> PredictionMarketContext:
    """Contexto desabilitado (perfil com prediction_context_mode=disabled)."""
    return PredictionMarketContext(
        enabled=False, provider=provider, mode="disabled",
    )


def build_prediction_context(
    *,
    events: Sequence[MarketEvent],
    provider: str = "polymarket_readonly",
    mode: str = "read_only",
    fetched_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    max_age_seconds: float = _DEFAULT_MAX_AGE_SECONDS,
) -> PredictionMarketContext:
    """Consolida eventos normalizados em um contexto consultivo.

    stale=True quando a idade do snapshot excede max_age_seconds —
    consumidores (IA/report) devem tratar contexto stale como alerta,
    nunca como dado confiavel.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = 0.0
    if fetched_at is not None:
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - fetched_at).total_seconds())
    stale = age > max_age_seconds

    relevant = tuple(
        e for e in events
        if e.btc_relevance_score >= _BTC_RELEVANT_THRESHOLD
        or e.category == "crypto"
    )
    flags = tuple(sorted({
        e.risk_flag for e in relevant if e.risk_flag is not None
    }))

    summary: Optional[str] = None
    if flags:
        summary = (
            "Prediction markets indicate elevated macro/event "
            f"uncertainty ({len(flags)} risk flag(s), "
            f"{len(relevant)} BTC-relevant event(s))."
        )
    elif relevant:
        summary = (
            f"{len(relevant)} BTC-relevant prediction market event(s); "
            "no risk flags raised."
        )

    return PredictionMarketContext(
        enabled=True,
        provider=provider,
        mode=mode,
        btc_relevant_events=relevant,
        risk_flags=flags,
        stale=stale,
        age_seconds=age,
        summary=summary,
        events_considered=len(events),
    )


__all__ = [
    "PredictionMarketContext",
    "build_prediction_context",
    "disabled_context",
]
