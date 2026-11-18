"""
PolymarketReadonlyClient (FASE 34)
===================================
Client READ-ONLY de prediction markets (Polymarket).

⚠️  REGRAS ABSOLUTAS:
    - READ-ONLY: zero aposta, zero ordem, zero integracao financeira,
      zero conta real, zero API key real.
    - Transporte INJETAVEL: producao futura pode injetar um fetcher
      HTTP read-only; TESTES injetam fixtures/mocks (zero rede).
    - Sem transporte injetado, fetch retorna lista vazia (fail-safe).
    - Nenhum header/secret eh aceito, armazenado ou repassado.
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, Optional, Sequence

from crypto_trading_bot.prediction_markets.market_event_model import (
    MarketEvent,
)
from crypto_trading_bot.prediction_markets.prediction_signal_normalizer \
    import normalize_raw_events


PROVIDER_ID = "polymarket_readonly"

# Assinatura do transporte injetavel: () -> lista de payloads brutos.
RawFetcher = Callable[[], Sequence[Mapping[str, Any]]]


class PolymarketReadonlyClient:
    """Client read-only com transporte injetavel.

    Args:
        raw_fetcher: callable sem argumentos que retorna payloads
            brutos (list[dict]). Em teste: fixture/mock. Sem fetcher,
            fetch_events() retorna [] (fail-safe, nunca levanta).
    """

    def __init__(self, *, raw_fetcher: Optional[RawFetcher] = None) -> None:
        if raw_fetcher is not None and not callable(raw_fetcher):
            raise TypeError("raw_fetcher deve ser callable ou None")
        self._raw_fetcher = raw_fetcher
        self._fetch_failures = 0

    @property
    def provider_id(self) -> str:
        return PROVIDER_ID

    @property
    def fetch_failures(self) -> int:
        return self._fetch_failures

    def fetch_events(self) -> List[MarketEvent]:
        """Busca e normaliza eventos. Read-only. Nunca levanta.

        Sem fetcher injetado OU em caso de erro do fetcher, retorna []
        e incrementa fetch_failures — o ecossistema segue sem contexto
        (prediction_context_unavailable).
        """
        if self._raw_fetcher is None:
            return []
        try:
            raw = self._raw_fetcher()
        except Exception:  # noqa: BLE001
            self._fetch_failures += 1
            return []
        if not isinstance(raw, (list, tuple)):
            self._fetch_failures += 1
            return []
        return normalize_raw_events(list(raw))

    # ------------------------------------------------------------------
    # Defesa em profundidade: QUALQUER tentativa de execucao falha.
    # ------------------------------------------------------------------

    def place_bet(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(
            "PolymarketReadonlyClient e READ-ONLY: apostas/ordens sao "
            "proibidas nesta macrofase (FASE 34)."
        )

    def place_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError(
            "PolymarketReadonlyClient e READ-ONLY: apostas/ordens sao "
            "proibidas nesta macrofase (FASE 34)."
        )


__all__ = ["PROVIDER_ID", "PolymarketReadonlyClient", "RawFetcher"]
