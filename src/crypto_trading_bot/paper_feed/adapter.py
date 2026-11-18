"""
PaperFeedAdapter - adaptador de feed paper offline (FASE 25 Bloco 2)
======================================================================
Frozen dataclass que carrega uma lista pre-definida de Candle e expoe
metadata para auditoria. NAO baixa dados. NAO chama rede. NAO importa
BybitClient/httpx/requests.

USO:
    from crypto_trading_bot.paper_feed import (
        PaperFeedAdapter, PaperFeedType,
    )
    from crypto_trading_bot.paper_feed.synthetic import (
        build_synthetic_trending_feed,
    )

    feed = build_synthetic_trending_feed(
        symbol="BTCUSDT", timeframe="15", n=200,
    )
    # feed.candles eh List[Candle], feed.feed_type eh PaperFeedType.

SEGURANCA:
    - NAO importa crypto_trading_bot.exchange.bybit_client.
    - NAO importa BybitDemoExecutor / BybitTestnetExecutor.
    - NAO importa httpx, requests, urllib.
    - NAO le .env.
    - NAO expoe API key/secret/signature.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.paper_feed.types import PaperFeedType


@dataclass(frozen=True)
class PaperFeedAdapter:
    """Wrapper imutavel sobre uma lista de Candle para feed paper.

    Atributos:
        candles:             tupla imutavel de Candle em ordem cronologica.
        feed_type:           PaperFeedType (auditavel em result/UI snapshot).
        source_description:  string curta descrevendo a origem.
        symbol:              symbol validado (todas as candles coerentes).
        timeframe:           timeframe validado (todas as candles coerentes).

    Garantias:
        - candles eh tupla nao-vazia.
        - Symbol e timeframe consistentes em TODAS as candles.
        - Ordem cronologica preservada (timestamp[i+1] > timestamp[i]).
    """

    candles: Tuple[Candle, ...]
    feed_type: PaperFeedType
    source_description: str
    symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        if not isinstance(self.feed_type, PaperFeedType):
            raise TypeError(
                "feed_type deve ser PaperFeedType; "
                f"recebido {type(self.feed_type).__name__}"
            )
        if not isinstance(self.source_description, str):
            raise TypeError("source_description deve ser string")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError(
                f"symbol deve ser string nao-vazia; recebido {self.symbol!r}"
            )
        if not isinstance(self.timeframe, str) or not self.timeframe.strip():
            raise ValueError(
                f"timeframe deve ser string nao-vazia; recebido {self.timeframe!r}"
            )
        # Normaliza candles para tupla.
        candles = tuple(self.candles)
        object.__setattr__(self, "candles", candles)
        if len(candles) == 0:
            raise ValueError("PaperFeedAdapter requer pelo menos 1 candle")
        # Valida symbol/timeframe consistentes em todas as candles.
        for i, c in enumerate(candles):
            if c.symbol != self.symbol:
                raise ValueError(
                    f"candle[{i}].symbol={c.symbol!r} != adapter.symbol="
                    f"{self.symbol!r}"
                )
            if c.timeframe != self.timeframe:
                raise ValueError(
                    f"candle[{i}].timeframe={c.timeframe!r} != adapter."
                    f"timeframe={self.timeframe!r}"
                )
        # Valida ordem cronologica estrita.
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i - 1].timestamp:
                raise ValueError(
                    f"candles fora de ordem cronologica em [{i}]: "
                    f"ts[{i-1}]={candles[i-1].timestamp.isoformat()} "
                    f"ts[{i}]={candles[i].timestamp.isoformat()}"
                )

    @property
    def n_candles(self) -> int:
        return len(self.candles)

    def to_dict_summary(self) -> dict:
        """Resumo serializavel para relatorio. SEM secrets."""
        first = self.candles[0]
        last = self.candles[-1]
        return {
            "feed_type": self.feed_type.value,
            "source_description": self.source_description,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "n_candles": self.n_candles,
            "first_close": float(first.close),
            "last_close": float(last.close),
            "first_timestamp": first.timestamp.isoformat(),
            "last_timestamp": last.timestamp.isoformat(),
        }
