"""
Tests - PaperFeedAdapter (FASE 25 Bloco 2)
============================================
100% offline. ZERO network. ZERO secrets.

Cobre:
    - validacao de symbol/timeframe coerentes em todas as candles;
    - validacao de ordem cronologica;
    - PaperFeedType enum + helpers;
    - to_dict_summary sem secrets.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.paper_feed import (
    PaperFeedAdapter, PaperFeedType,
    is_synthetic, requires_signal_exercise,
)


def _make_candle(
    ts: datetime, *, symbol: str = "BTCUSDT", timeframe: str = "15",
    close: float = 65000.0,
) -> Candle:
    return Candle(
        symbol=symbol, timeframe=timeframe, timestamp=ts,
        open=close * 0.999, high=close * 1.001,
        low=close * 0.998, close=close, volume=100.0,
    )


def _make_candles(n: int, *, symbol: str = "BTCUSDT",
                  timeframe: str = "15") -> list:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=int(timeframe))
    candles = []
    price = 65000.0
    for i in range(n):
        c = _make_candle(
            start + interval * i,
            symbol=symbol, timeframe=timeframe, close=price + i * 10.0,
        )
        candles.append(c)
    return candles


class TestPaperFeedTypeEnum:

    def test_values(self):
        assert PaperFeedType.MOCK_RANDOM_WALK.value == "mock_random_walk"
        assert PaperFeedType.SYNTHETIC_TRENDING.value == "synthetic_trending"
        assert PaperFeedType.SYNTHETIC_RANGING.value == "synthetic_ranging"
        assert PaperFeedType.CACHE.value == "cache"

    def test_requires_signal_exercise_true_for_nonlegacy(self):
        assert requires_signal_exercise(PaperFeedType.SYNTHETIC_TRENDING)
        assert requires_signal_exercise(PaperFeedType.SYNTHETIC_RANGING)
        assert requires_signal_exercise(PaperFeedType.CACHE)

    def test_requires_signal_exercise_false_for_legacy(self):
        assert not requires_signal_exercise(PaperFeedType.MOCK_RANDOM_WALK)

    def test_is_synthetic_only_for_synthetic_types(self):
        assert is_synthetic(PaperFeedType.SYNTHETIC_TRENDING)
        assert is_synthetic(PaperFeedType.SYNTHETIC_RANGING)
        assert not is_synthetic(PaperFeedType.CACHE)
        assert not is_synthetic(PaperFeedType.MOCK_RANDOM_WALK)


class TestPaperFeedAdapterValidation:

    def test_happy_path(self):
        candles = _make_candles(10)
        ad = PaperFeedAdapter(
            candles=tuple(candles),
            feed_type=PaperFeedType.SYNTHETIC_TRENDING,
            source_description="test",
            symbol="BTCUSDT", timeframe="15",
        )
        assert ad.n_candles == 10
        assert ad.feed_type == PaperFeedType.SYNTHETIC_TRENDING

    def test_empty_candles_rejected(self):
        with pytest.raises(ValueError, match="pelo menos 1 candle"):
            PaperFeedAdapter(
                candles=(), feed_type=PaperFeedType.SYNTHETIC_TRENDING,
                source_description="t", symbol="BTC", timeframe="15",
            )

    def test_inconsistent_symbol_rejected(self):
        c1 = _make_candle(
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            symbol="BTCUSDT",
        )
        c2 = _make_candle(
            datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc),
            symbol="ETHUSDT",
        )
        with pytest.raises(ValueError, match="symbol"):
            PaperFeedAdapter(
                candles=(c1, c2),
                feed_type=PaperFeedType.SYNTHETIC_TRENDING,
                source_description="t", symbol="BTCUSDT", timeframe="15",
            )

    def test_inconsistent_timeframe_rejected(self):
        c1 = _make_candle(
            datetime(2024, 1, 1, tzinfo=timezone.utc), timeframe="15",
        )
        c2 = _make_candle(
            datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc), timeframe="30",
        )
        with pytest.raises(ValueError, match="timeframe"):
            PaperFeedAdapter(
                candles=(c1, c2),
                feed_type=PaperFeedType.SYNTHETIC_TRENDING,
                source_description="t", symbol="BTCUSDT", timeframe="15",
            )

    def test_non_chronological_order_rejected(self):
        c1 = _make_candle(datetime(2024, 1, 1, 0, 15, tzinfo=timezone.utc))
        c2 = _make_candle(datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc))
        with pytest.raises(ValueError, match="fora de ordem"):
            PaperFeedAdapter(
                candles=(c1, c2),
                feed_type=PaperFeedType.SYNTHETIC_TRENDING,
                source_description="t", symbol="BTCUSDT", timeframe="15",
            )

    def test_feed_type_must_be_enum(self):
        candles = _make_candles(5)
        with pytest.raises(TypeError, match="feed_type"):
            PaperFeedAdapter(
                candles=tuple(candles), feed_type="synthetic_trending",
                source_description="t", symbol="BTCUSDT", timeframe="15",
            )


class TestSummarySerialization:

    def test_to_dict_summary_has_required_fields(self):
        candles = _make_candles(20)
        ad = PaperFeedAdapter(
            candles=tuple(candles),
            feed_type=PaperFeedType.SYNTHETIC_TRENDING,
            source_description="test n=20",
            symbol="BTCUSDT", timeframe="15",
        )
        d = ad.to_dict_summary()
        assert d["feed_type"] == "synthetic_trending"
        assert d["source_description"] == "test n=20"
        assert d["symbol"] == "BTCUSDT"
        assert d["timeframe"] == "15"
        assert d["n_candles"] == 20
        assert "first_close" in d
        assert "last_close" in d
        assert "first_timestamp" in d
        assert "last_timestamp" in d

    def test_to_dict_summary_no_secrets(self):
        candles = _make_candles(5)
        ad = PaperFeedAdapter(
            candles=tuple(candles),
            feed_type=PaperFeedType.SYNTHETIC_TRENDING,
            source_description="t", symbol="BTCUSDT", timeframe="15",
        )
        d = ad.to_dict_summary()
        text = str(d).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text


def _executable_lines(src: str) -> str:
    """Strip naive de docstrings e comentarios para checagem estrutural."""
    out = []
    in_block = False
    for line in src.splitlines():
        stripped = line.strip()
        if in_block:
            if stripped.endswith('"""') or stripped.endswith("'''"):
                in_block = False
            continue
        if stripped.startswith('"""') or stripped.startswith("'''"):
            if not (stripped.endswith('"""') and len(stripped) > 3):
                in_block = True
            continue
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


class TestModuleHasNoNetworkImports:

    def test_adapter_module_no_network_imports(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "src" / \
            "crypto_trading_bot" / "paper_feed" / "adapter.py"
        exe = _executable_lines(path.read_text(encoding="utf-8"))
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests",
                    "BybitClient(", "BybitDemoExecutor("):
            assert tok not in exe, f"forbidden token in adapter: {tok}"

    def test_types_module_no_network_imports(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "src" / \
            "crypto_trading_bot" / "paper_feed" / "types.py"
        exe = _executable_lines(path.read_text(encoding="utf-8"))
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests",
                    "BybitClient(", "BybitDemoExecutor("):
            assert tok not in exe
