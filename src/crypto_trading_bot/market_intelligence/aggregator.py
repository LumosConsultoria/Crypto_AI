"""
MarketIntelligence Aggregator (FASE 36 Bloco D)
================================================
Agrega fontes read-only em UM snapshot consultivo com
used/not_used/stale/unavailable por fonte + cache TTL.

⚠️  Gate ENV proprio: ENABLE_MARKET_INTELLIGENCE (default OFF).
⚠️  Fonte ausente/stale NUNCA bloqueia o pipeline; apenas registra.
    Flags so REDUZEM permissao (via IA consultiva/manual review).
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Sequence

from crypto_trading_bot.market_intelligence.provider_protocol import (
    ContextSlice,
)


ENV_MARKET_INTELLIGENCE = "ENABLE_MARKET_INTELLIGENCE"


def market_intelligence_gate_enabled() -> bool:
    return os.environ.get(
        ENV_MARKET_INTELLIGENCE, "",
    ).strip().lower() in ("true", "1", "yes")


class MarketIntelligenceAggregator:
    """Agrega providers com cache TTL por fonte.

    Args:
        providers: sequencia de MarketContextProvider (adapters).
        clock: injetavel para testes.
    """

    def __init__(
        self,
        *,
        providers: Sequence,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._providers = list(providers)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cache: Dict[str, ContextSlice] = {}

    def _now(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _get_slice(self, provider) -> ContextSlice:
        """Cache TTL: refetch apenas quando expirado."""
        name = provider.source_name
        now = self._now()
        cached = self._cache.get(name)
        if cached is not None and cached.available and \
                cached.age_seconds(now) <= cached.ttl_seconds:
            return cached
        try:
            sl = provider.fetch()
        except Exception as e:  # noqa: BLE001
            from crypto_trading_bot.market_intelligence \
                .provider_protocol import unavailable_slice
            sl = unavailable_slice(name, type(e).__name__)
        self._cache[name] = sl
        return sl

    def snapshot(self) -> dict:
        """MarketIntelligenceSnapshot consultivo (dict sanitizado).

        Compativel com o Decision Trace (sources_used/stale/
        unavailable/risk_flags/inconclusive).
        """
        now = self._now()
        used: List[str] = []
        stale: List[str] = []
        unavailable: List[str] = []
        flags: List[str] = []
        slices: Dict[str, dict] = {}
        inconclusive = False

        for provider in self._providers:
            sl = self._get_slice(provider)
            slices[sl.source] = sl.to_dict()
            if not sl.available:
                unavailable.append(sl.source)
                continue
            is_stale = sl.stale or (
                sl.age_seconds(now) > sl.ttl_seconds
            )
            used.append(sl.source)
            if is_stale:
                stale.append(sl.source)
            if not sl.conclusive:
                inconclusive = True
            flags.extend(sl.risk_flags)

        summary = None
        if flags:
            summary = (
                f"Market intelligence: {len(flags)} risk flag(s) "
                f"em {len(used)} fonte(s)."
            )
        elif used:
            summary = (
                f"{len(used)} fonte(s) de contexto sem risk flags."
            )

        return {
            "schema": "market_intelligence_snapshot_v1",
            "generated_at": now.isoformat(),
            "sources_used": used,
            "sources_stale": stale,
            "sources_unavailable": unavailable,
            "risk_flags": sorted(set(flags)),
            "inconclusive": inconclusive,
            "summary": summary,
            "slices": slices,
        }


__all__ = [
    "ENV_MARKET_INTELLIGENCE",
    "MarketIntelligenceAggregator",
    "market_intelligence_gate_enabled",
]
