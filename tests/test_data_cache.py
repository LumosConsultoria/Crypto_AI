"""
Testes do DataCache — FASE 3G
================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.
⚠️  Testes usam tmp_path do pytest — NUNCA tocam data/historical/ real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from crypto_trading_bot.data.data_cache import DataCache, DataCacheError
from crypto_trading_bot.exchange.base_exchange import Candle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_INTERVAL = timedelta(minutes=15)


def _candle(
    i: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=_TS0 + _INTERVAL * i,
        open=65000.0 + i,
        high=65100.0 + i,
        low=64900.0 + i,
        close=65050.0 + i,
        volume=1000.0,
    )


def _candles(n: int = 5, **kw) -> List[Candle]:
    return [_candle(i, **kw) for i in range(n)]


# ---------------------------------------------------------------------------
# path_for
# ---------------------------------------------------------------------------

class TestDataCachePathFor:

    def test_path_for_symbol_timeframe(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        p = cache.path_for("BTCUSDT", "15")
        assert p == tmp_path / "BTCUSDT_15.csv"

    def test_path_for_invalid_symbol_raises(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        with pytest.raises(ValueError):
            cache.path_for("", "15")

    def test_path_for_invalid_timeframe_raises(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        with pytest.raises(ValueError):
            cache.path_for("BTCUSDT", "")


# ---------------------------------------------------------------------------
# exists
# ---------------------------------------------------------------------------

class TestDataCacheExists:

    def test_exists_returns_false_for_missing(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        assert cache.exists("BTCUSDT", "15") is False

    def test_exists_returns_true_after_save(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(3))
        assert cache.exists("BTCUSDT", "15") is True


# ---------------------------------------------------------------------------
# save + load roundtrip
# ---------------------------------------------------------------------------

class TestDataCacheRoundtrip:

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        original = _candles(10)
        cache.save(original)
        restored = cache.load("BTCUSDT", "15")
        assert len(restored) == len(original)
        for o, r in zip(original, restored):
            assert o.symbol == r.symbol
            assert o.timeframe == r.timeframe
            assert o.timestamp == r.timestamp
            assert abs(o.open - r.open) < 1e-6
            assert abs(o.high - r.high) < 1e-6
            assert abs(o.low - r.low) < 1e-6
            assert abs(o.close - r.close) < 1e-6
            assert abs(o.volume - r.volume) < 1e-6

    def test_save_creates_directory_if_missing(self, tmp_path: Path):
        nested = tmp_path / "nested" / "deep" / "dir"
        cache = DataCache(base_dir=nested)
        assert not nested.exists()
        cache.save(_candles(3))
        assert nested.exists()

    def test_load_preserves_chronological_order(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        # Embaralha intencionalmente — save deveria persistir e load reordenar
        original = _candles(5)
        # Reverte a ordem antes de salvar
        cache.save(list(reversed(original)))
        restored = cache.load("BTCUSDT", "15")
        # load_candles_from_csv ordena por timestamp internamente
        for i in range(1, len(restored)):
            assert restored[i].timestamp > restored[i - 1].timestamp


# ---------------------------------------------------------------------------
# Save validation (consistência de symbol/timeframe)
# ---------------------------------------------------------------------------

class TestDataCacheSaveValidation:

    def test_save_empty_raises(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        with pytest.raises(ValueError, match="vazia"):
            cache.save([])

    def test_save_inconsistent_symbol_raises(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        candles = _candles(3)
        candles[2] = _candle(2, symbol="ETHUSDT")
        with pytest.raises(ValueError, match="symbol"):
            cache.save(candles)

    def test_save_inconsistent_timeframe_raises(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        candles = _candles(3)
        candles[2] = _candle(2, timeframe="60")
        with pytest.raises(ValueError, match="timeframe"):
            cache.save(candles)


# ---------------------------------------------------------------------------
# Load missing
# ---------------------------------------------------------------------------

class TestDataCacheLoadMissing:

    def test_load_nonexistent_raises_cache_error(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        with pytest.raises(DataCacheError):
            cache.load("BTCUSDT", "15")


# ---------------------------------------------------------------------------
# Base dir default não é tocado em testes
# ---------------------------------------------------------------------------

class TestDataCacheTestsDoNotTouchRealCache:

    def test_constructor_with_tmp_path_does_not_touch_default(self, tmp_path: Path):
        """
        Documenta que testes SEMPRE usam tmp_path. Verificação simples:
        base_dir é o tmp_path passado.
        """
        cache = DataCache(base_dir=tmp_path)
        assert cache.base_dir == tmp_path
        # base_dir default NUNCA é "data/historical" nestes testes
        assert "data/historical" not in str(cache.base_dir).replace("\\", "/")
