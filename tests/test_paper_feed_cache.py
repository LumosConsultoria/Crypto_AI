"""
Tests - paper_feed.build_cache_feed (FASE 25 Bloco 3)
======================================================
100% offline. ZERO network. cache eh LOCAL ONLY; cache miss falha
sem download.

Cobre:
    - cache hit retorna PaperFeedAdapter com feed_type=CACHE.
    - cache miss levanta DataCacheError.
    - DataCache injetavel (tmp_path) garante isolamento.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.data.data_cache import DataCache, DataCacheError
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.paper_feed import (
    PaperFeedType,
    build_cache_feed,
)


def _make_candles(n: int, *, symbol: str = "BTCUSDT", timeframe: str = "15"):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=int(timeframe))
    candles = []
    price = 65000.0
    for i in range(n):
        candles.append(Candle(
            symbol=symbol, timeframe=timeframe,
            timestamp=start + interval * i,
            open=round(price, 2),
            high=round(price * 1.001, 2),
            low=round(price * 0.999, 2),
            close=round(price * 1.0005, 2),
            volume=100.0,
        ))
        price *= 1.0005
    return candles


class TestCacheHit:

    def test_returns_adapter_with_cache_feed_type(self, tmp_path):
        cache = DataCache(base_dir=tmp_path)
        candles = _make_candles(80)
        cache.save(candles)
        feed = build_cache_feed(
            symbol="BTCUSDT", timeframe="15", cache=cache,
        )
        assert feed.feed_type == PaperFeedType.CACHE
        assert feed.symbol == "BTCUSDT"
        assert feed.timeframe == "15"
        assert feed.n_candles == 80

    def test_source_description_contains_path(self, tmp_path):
        cache = DataCache(base_dir=tmp_path)
        candles = _make_candles(50)
        cache.save(candles)
        feed = build_cache_feed(
            symbol="BTCUSDT", timeframe="15", cache=cache,
        )
        assert "cache" in feed.source_description.lower()


class TestCacheMissFailsClearly:

    def test_cache_miss_raises_datacacheerror_no_download(self, tmp_path):
        cache = DataCache(base_dir=tmp_path)  # vazio
        with pytest.raises(DataCacheError):
            build_cache_feed(
                symbol="BTCUSDT", timeframe="15", cache=cache,
            )

    def test_default_cache_uses_data_historical(self):
        # Sem arquivo, sem download. Se arquivo NAO existir em
        # data/historical/, deve falhar com DataCacheError.
        # Garantia: nao chama rede, falha explicita.
        import os
        from pathlib import Path
        default_path = Path("data/historical/NONEXISTENT_15.csv")
        if default_path.exists():
            pytest.skip("test requires NONEXISTENT_15.csv absent (locally)")
        with pytest.raises(DataCacheError):
            build_cache_feed(symbol="NONEXISTENT", timeframe="15")
