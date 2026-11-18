"""
Tests - paper_feed.synthetic (FASE 25 Bloco 3)
================================================
100% offline. ZERO network. ZERO download. ZERO secret.

Cobre:
    - build_synthetic_trending_feed produz adapter valido.
    - build_synthetic_ranging_feed produz adapter valido.
    - build_synthetic_trend_pullback_feed produz fases distintas
      (warm-up, pullback, continuacao).
    - parametros invalidos rejeitados.
    - feed_type correto em cada construtor.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.paper_feed import (
    PaperFeedType,
    build_synthetic_ranging_feed,
    build_synthetic_trend_pullback_feed,
    build_synthetic_trending_feed,
)


class TestSyntheticTrendingFeed:

    def test_default_construction(self):
        feed = build_synthetic_trending_feed(
            symbol="BTCUSDT", timeframe="15", n=100,
        )
        assert feed.feed_type == PaperFeedType.SYNTHETIC_TRENDING
        assert feed.symbol == "BTCUSDT"
        assert feed.timeframe == "15"
        assert feed.n_candles == 100

    def test_arbitrary_symbols_ok(self):
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            feed = build_synthetic_trending_feed(symbol=sym, n=80)
            assert feed.symbol == sym

    def test_n_must_be_positive(self):
        with pytest.raises(ValueError):
            build_synthetic_trending_feed(n=0)
        with pytest.raises(ValueError):
            build_synthetic_trending_feed(n=-5)


class TestSyntheticRangingFeed:

    def test_default_construction(self):
        feed = build_synthetic_ranging_feed(symbol="BTCUSDT", n=100)
        assert feed.feed_type == PaperFeedType.SYNTHETIC_RANGING
        assert feed.n_candles == 100

    def test_n_must_be_positive(self):
        with pytest.raises(ValueError):
            build_synthetic_ranging_feed(n=0)


class TestSyntheticTrendPullbackFeed:

    def test_construction_with_three_phases(self):
        feed = build_synthetic_trend_pullback_feed(
            symbol="BTCUSDT", timeframe="15",
            base_price=65000.0,
            n_uptrend_warmup=80, n_pullback=8, n_continuation=30,
        )
        assert feed.feed_type == PaperFeedType.SYNTHETIC_TRENDING
        assert feed.n_candles == 80 + 8 + 30

    def test_pullback_phase_decreases_price(self):
        feed = build_synthetic_trend_pullback_feed(
            n_uptrend_warmup=50, n_pullback=10, n_continuation=10,
            uptrend_pct_per_candle=0.002,
            pullback_pct_per_candle=-0.004,
            continuation_pct_per_candle=0.002,
        )
        # Final do warmup vs final do pullback
        warmup_end = feed.candles[49].close
        pullback_end = feed.candles[59].close
        assert pullback_end < warmup_end, (
            f"pullback nao caiu: warmup_end={warmup_end} "
            f"pullback_end={pullback_end}"
        )
        # Continuacao recupera
        continuation_end = feed.candles[-1].close
        assert continuation_end > pullback_end

    def test_warmup_too_small_rejected(self):
        with pytest.raises(ValueError, match="n_uptrend_warmup"):
            build_synthetic_trend_pullback_feed(
                n_uptrend_warmup=10, n_pullback=5, n_continuation=5,
            )

    def test_chronological_order(self):
        feed = build_synthetic_trend_pullback_feed(
            n_uptrend_warmup=60, n_pullback=5, n_continuation=10,
        )
        for i in range(1, feed.n_candles):
            assert feed.candles[i].timestamp > feed.candles[i - 1].timestamp


class TestSourceDescriptionsAreInformative:

    def test_trending_describes_params(self):
        feed = build_synthetic_trending_feed(n=80, base_price=50000.0)
        desc = feed.source_description
        assert "synthetic" in desc
        assert "trending" in desc
        assert "80" in desc

    def test_ranging_describes_params(self):
        feed = build_synthetic_ranging_feed(n=80, center_price=50000.0)
        desc = feed.source_description
        assert "ranging" in desc

    def test_trend_pullback_describes_three_phases(self):
        feed = build_synthetic_trend_pullback_feed(
            n_uptrend_warmup=60, n_pullback=7, n_continuation=20,
        )
        desc = feed.source_description
        assert "warmup" in desc
        assert "pullback" in desc


def _executable_lines(src: str) -> str:
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


class TestModuleHasNoNetworkOrSecrets:

    def test_synthetic_module_no_network_imports(self):
        from pathlib import Path
        path = Path(__file__).parent.parent / "src" / \
            "crypto_trading_bot" / "paper_feed" / "synthetic.py"
        exe = _executable_lines(path.read_text(encoding="utf-8"))
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests",
                    "BybitClient(", "BybitDemoExecutor(",
                    "HistoricalDataService("):
            assert tok not in exe, f"forbidden in synthetic: {tok}"
