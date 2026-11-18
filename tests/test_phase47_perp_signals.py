"""
FASE 47 — perp_signals: funding/OI alinhados CAUSAL + percentil + eventos.
100% OFFLINE. Anti-lookahead (asof por close_time; percentil/variacao so
janela passada). Funding no PnL: long paga rate>0, short recebe; so eventos
dentro de (entry, exit]. Sem rede/ordem/secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.perp_signals import (
    TimePoint,
    align_asof,
    build_perp_features,
    causal_pct_change,
    causal_percentile_rank,
    funding_pnl_adjustment,
    load_funding,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(n, step_min):
    out = []
    tf = f"{step_min}m" if step_min < 60 else "1h"
    for i in range(n):
        ts = _D0 + timedelta(minutes=step_min * i)
        out.append(Candle(symbol="BTCUSDT", timeframe=tf, timestamp=ts,
                          open=100.0, high=101.0, low=99.0, close=100.0,
                          volume=10.0))
    return out


class TestAlignAsof:

    def test_causal_last_point_at_or_before_close(self):
        # candles 1h; ponto de funding em t=+30min e t=+90min
        candles = _candles(3, 60)   # closes em 60,120,180 min
        pts = [TimePoint(_D0 + timedelta(minutes=30), 0.01),
               TimePoint(_D0 + timedelta(minutes=90), 0.02)]
        aligned = align_asof(candles, pts, interval_minutes=60)
        # candle0 close=60 => so o ponto de 30 (0.01)
        assert aligned[0] == 0.01
        # candle1 close=120 => ponto de 90 (0.02)
        assert aligned[1] == 0.02
        assert aligned[2] == 0.02

    def test_no_lookahead_future_point_excluded(self):
        candles = _candles(2, 60)        # closes 60, 120
        pts = [TimePoint(_D0 + timedelta(minutes=200), 0.05)]  # futuro
        aligned = align_asof(candles, pts, interval_minutes=60)
        assert aligned == [None, None]   # nenhum ponto <= close


class TestCausalFeatures:

    def test_percentile_rank_uses_only_past(self):
        series = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        ranks = causal_percentile_rank(series, window=4)
        # ultimo valor (6) e o maior vs janela passada => rank alto
        assert ranks[-1] == pytest.approx(1.0)
        # warmup inicial => None
        assert ranks[0] is None

    def test_pct_change(self):
        series = [100.0, None, 110.0, 121.0]
        ch = causal_pct_change(series, k=2)
        assert ch[0] is None
        assert ch[2] == pytest.approx(0.10)   # (110-100)/100


class TestFundingPnL:

    def test_long_pays_when_rate_positive(self):
        events = [TimePoint(_D0 + timedelta(hours=8), 0.01)]
        adj = funding_pnl_adjustment(
            _D0 + timedelta(hours=1), _D0 + timedelta(hours=10),
            notional_usd=1000.0, side="buy", funding_events=events)
        # long paga: -0.01 * 1000 = -10
        assert adj == pytest.approx(-10.0)

    def test_short_receives_when_rate_positive(self):
        events = [TimePoint(_D0 + timedelta(hours=8), 0.01)]
        adj = funding_pnl_adjustment(
            _D0 + timedelta(hours=1), _D0 + timedelta(hours=10),
            notional_usd=1000.0, side="sell", funding_events=events)
        assert adj == pytest.approx(10.0)

    def test_no_event_crossed_is_zero(self):
        events = [TimePoint(_D0 + timedelta(hours=20), 0.01)]
        adj = funding_pnl_adjustment(
            _D0 + timedelta(hours=1), _D0 + timedelta(hours=3),
            notional_usd=1000.0, side="buy", funding_events=events)
        assert adj == 0.0


class TestBuildFeatures:

    def test_coverage_and_load(self):
        rows = [{"timestamp": (_D0 + timedelta(hours=8 * i)).isoformat(),
                 "funding_rate": 0.01} for i in range(3)]
        fpts = load_funding(rows)
        assert len(fpts) == 3
        candles = _candles(60, 60)
        feats = build_perp_features(candles, interval_minutes=60,
                                    funding_points=fpts)
        cov = feats.coverage()
        assert cov["funding"]["present"] >= 1
        assert cov["funding_events"] == 3
