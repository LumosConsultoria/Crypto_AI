"""
Adapters READ-ONLY de Market Intelligence (FASE 36 Bloco D)
============================================================
Fontes: funding, open interest, orderbook/spread/liquidez, noticias,
polymarket (reusa FASE 34), exchange status, volatilidade/correlacao.

⚠️  TRANSPORTE INJETAVEL (mock-first): sem fetcher => unavailable
    fail-safe. Transporte REAL depende das respostas Q3/Q4 do
    operador (status missing_config no Options Registry).
⚠️  Payload bruto NUNCA passa adiante: cada adapter normaliza um
    dict pequeno e tecnico.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from crypto_trading_bot.market_intelligence.provider_protocol import (
    ContextSlice,
    unavailable_slice,
)

RawFetcher = Callable[[], Mapping[str, Any]]


class _BaseAdapter:
    """Base: fetcher injetavel; falha => unavailable (nunca levanta)."""

    source = "base"
    ttl_seconds = 300.0

    def __init__(
        self, *, raw_fetcher: Optional[RawFetcher] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._fetch_raw = raw_fetcher
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def source_name(self) -> str:
        return self.source

    def fetch(self) -> ContextSlice:
        if self._fetch_raw is None:
            return unavailable_slice(self.source, "no_transport")
        try:
            raw = dict(self._fetch_raw() or {})
        except Exception as e:  # noqa: BLE001
            return unavailable_slice(self.source, type(e).__name__)
        try:
            return self._normalize(raw)
        except Exception as e:  # noqa: BLE001
            return unavailable_slice(
                self.source, f"normalize:{type(e).__name__}",
            )

    def _normalize(self, raw: Mapping[str, Any]) -> ContextSlice:
        raise NotImplementedError


class FundingRateAdapter(_BaseAdapter):
    source = "funding"

    def _normalize(self, raw):
        rate = float(raw.get("funding_rate", 0.0))
        flags = []
        # Funding extremo sugere posicionamento lotado (consultivo).
        if abs(rate) >= 0.0005:
            flags.append("extreme_funding")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), ttl_seconds=self.ttl_seconds,
            confidence=0.8, risk_flags=tuple(flags),
            data={"funding_rate": rate,
                  "next_funding_time": str(
                      raw.get("next_funding_time", ""),
                  )[:32]},
        )


class OpenInterestAdapter(_BaseAdapter):
    source = "open_interest"

    def _normalize(self, raw):
        oi = float(raw.get("open_interest", 0.0))
        change = float(raw.get("change_24h_pct", 0.0))
        flags = []
        if abs(change) >= 15.0:
            flags.append("open_interest_shift")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), confidence=0.7,
            risk_flags=tuple(flags),
            data={"open_interest": oi, "change_24h_pct": change},
        )


class OrderbookAdapter(_BaseAdapter):
    """Orderbook/spread/liquidez agregados."""
    source = "orderbook"
    ttl_seconds = 60.0

    def _normalize(self, raw):
        spread_bps = float(raw.get("spread_bps", 0.0))
        depth = float(raw.get("depth_usd_1pct", 0.0))
        flags = []
        if spread_bps >= 10.0:
            flags.append("wide_spread")
        if 0 < depth < 50000.0:
            flags.append("thin_liquidity")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), ttl_seconds=self.ttl_seconds,
            confidence=0.7, risk_flags=tuple(flags),
            data={"spread_bps": spread_bps,
                  "depth_usd_1pct": depth,
                  "bid": raw.get("bid"), "ask": raw.get("ask")},
        )


class NewsAdapter(_BaseAdapter):
    """Noticias: adapter ABSTRATO mockavel (Q4: sem fonte real)."""
    source = "news"
    ttl_seconds = 900.0

    def _normalize(self, raw):
        headlines = [
            str(h)[:140] for h in (raw.get("headlines") or [])[:10]
        ]
        sentiment = str(raw.get("sentiment", "neutral"))
        flags = []
        if sentiment in ("very_negative", "panic"):
            flags.append("negative_news_sentiment")
        if raw.get("high_impact_event"):
            flags.append("high_impact_news_event")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), ttl_seconds=self.ttl_seconds,
            confidence=0.5, conclusive=bool(headlines),
            risk_flags=tuple(flags),
            data={"headlines": headlines, "sentiment": sentiment},
        )


class PolymarketAdapter(_BaseAdapter):
    """Reusa a FASE 34 (read-only) como fonte de MI."""
    source = "polymarket"

    def __init__(self, *, client: Any = None,
                 clock: Optional[Callable[[], datetime]] = None):
        super().__init__(raw_fetcher=None, clock=clock)
        self._client = client

    def fetch(self) -> ContextSlice:
        if self._client is None:
            return unavailable_slice(self.source, "no_transport")
        try:
            events = self._client.fetch_events()
        except Exception as e:  # noqa: BLE001
            return unavailable_slice(self.source, type(e).__name__)
        if not events:
            return unavailable_slice(self.source, "no_events")
        from crypto_trading_bot.prediction_markets import (
            build_prediction_context,
        )
        ctx = build_prediction_context(
            events=events, mode="read_only",
            fetched_at=self._clock(), now=self._clock(),
        )
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(),
            stale=ctx.stale, confidence=0.6,
            risk_flags=tuple(ctx.risk_flags),
            data={"events_considered": ctx.events_considered,
                  "summary": ctx.summary},
        )


class ExchangeStatusAdapter(_BaseAdapter):
    source = "exchange_status"
    ttl_seconds = 120.0

    def _normalize(self, raw):
        status = str(raw.get("status", "unknown")).lower()
        flags = []
        if status not in ("normal", "ok"):
            flags.append("exchange_degraded")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), ttl_seconds=self.ttl_seconds,
            confidence=0.9, risk_flags=tuple(flags),
            data={"status": status},
        )


class VolatilityCorrelationAdapter(_BaseAdapter):
    source = "liquidity_correlation"

    def _normalize(self, raw):
        vol_pct = float(raw.get("realized_vol_pct", 0.0))
        corr = raw.get("btc_correlation")
        flags = []
        if vol_pct >= 5.0:
            flags.append("elevated_volatility")
        return ContextSlice(
            source=self.source, available=True,
            fetched_at=self._clock(), confidence=0.6,
            risk_flags=tuple(flags),
            data={"realized_vol_pct": vol_pct,
                  "btc_correlation": corr},
        )


__all__ = [
    "ExchangeStatusAdapter",
    "FundingRateAdapter",
    "NewsAdapter",
    "OpenInterestAdapter",
    "OrderbookAdapter",
    "PolymarketAdapter",
    "RawFetcher",
    "VolatilityCorrelationAdapter",
]
