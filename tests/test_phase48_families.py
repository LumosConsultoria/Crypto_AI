"""
FASE 48 — resampler causal + familias cost-aware F3 (HTF trend continuation) e
F4 (vol-expansion continuation multi-TF). 100% OFFLINE, deterministico. Stops
LARGOS (>= min_stop_dist) e alvos grandes (R alto). Anti-lookahead. Provider
real nunca em teste.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.cost_aware_families import (
    detect_f3_htf_trend_continuation,
    detect_f4_vol_expansion_continuation,
)
from crypto_trading_bot.research.htf_regime_filter import _ts_key
from crypto_trading_bot.research.timeframe_resample import resample

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class TestResample:

    def test_1h_to_4h_aggregation(self):
        c1h = []
        for i in range(8):
            px = 100.0 + i
            c1h.append(Candle(symbol="BTCUSDT", timeframe="1h",
                              timestamp=_D0 + timedelta(hours=i),
                              open=px, high=px + 2, low=px - 1,
                              close=px + 0.5, volume=10.0))
        c4h = resample(c1h, factor_minutes=240, base_minutes=60)
        assert len(c4h) == 2                       # 8 -> 2 buckets completos
        b0 = c4h[0]
        assert b0.open == 100.0                    # primeiro
        assert b0.close == 103.5                   # ultimo (i=3 close=103.5)
        assert b0.high == max(100 + 2, 103 + 2)    # max high
        assert b0.volume == 40.0                   # soma

    def test_incomplete_bucket_dropped(self):
        c1h = [Candle(symbol="BTCUSDT", timeframe="1h",
                      timestamp=_D0 + timedelta(hours=i), open=100, high=101,
                      low=99, close=100, volume=1.0) for i in range(6)]
        c4h = resample(c1h, factor_minutes=240, base_minutes=60)
        assert len(c4h) == 1            # 6 1h => 1 bucket completo (4) + 2 drop


def _trend_4h(n=120, base=1000.0, slope=3.0):
    # base alto p/ que o stop Donchian-10 caia em [1,5%, 5%] (teto do
    # RiskEngine) e gere setups executaveis. slope > offset p/ romper o canal.
    out = []
    for i in range(n):
        px = base + slope * i
        out.append(Candle(symbol="BTCUSDT", timeframe="4h",
                          timestamp=_D0 + timedelta(hours=4 * i),
                          open=px - 1, high=px + 1.5, low=px - 1.5,
                          close=px, volume=100.0))
    return out


class TestF3:

    def test_strong_uptrend_emits_long_with_wide_stop(self):
        setups = detect_f3_htf_trend_continuation(_trend_4h())
        assert len(setups) >= 1
        assert all(s.direction == "long" for s in setups)
        # cost-aware: stops largos (>= min_stop_dist 1,5%)
        assert all(s.stop_dist_pct >= 0.015 for s in setups)
        # alvo grande (~3R): dist alvo ~ 3x dist stop
        s = setups[0]
        assert (s.target - s.entry_ref) > 2.5 * (s.entry_ref - s.stop)

    def test_flat_market_no_setup(self):
        flat = [Candle(symbol="BTCUSDT", timeframe="4h",
                       timestamp=_D0 + timedelta(hours=4 * i),
                       open=100, high=100.5, low=99.5, close=100, volume=10.0)
                for i in range(120)]
        assert detect_f3_htf_trend_continuation(flat) == []


def _squeeze_then_expand(n=130):
    """Alta vol -> squeeze (baixa vol RELATIVA) -> expansao + rompimento up.
    O periodo inicial de alta vol faz o squeeze registrar percentil BAIXO."""
    out = []
    px = 100.0
    for i in range(n):
        if i < 45:
            # alta volatilidade (ranges largos), preco oscilando
            px = 100.0 + (3.0 if i % 2 else -3.0)
            hi, lo = px + 4.0, px - 4.0
        elif i < 95:
            # squeeze: ranges estreitos (baixa vol relativa ao inicio)
            px = 100.0 + (0.05 if i % 2 else -0.05)
            hi, lo = px + 0.2, px - 0.2
        else:
            # expansao + rompimento p/ cima
            px = 100.0 + (i - 94) * 2.5
            hi, lo = px + 2.0, px - 1.2
        out.append(Candle(symbol="BTCUSDT", timeframe="4h",
                          timestamp=_D0 + timedelta(hours=4 * i),
                          open=px - 0.1, high=hi, low=lo, close=px,
                          volume=100.0))
    return out


class TestF4:

    # squeeze_pctile relaxado p/ o fixture sintetico (default 0,25 = dados
    # reais com volatilidade mais variada).
    _P = {"squeeze_pctile": 0.6}

    def test_squeeze_expansion_emits_setup(self):
        setups = detect_f4_vol_expansion_continuation(
            _squeeze_then_expand(), params=self._P)
        assert len(setups) >= 1
        assert all(s.stop_dist_pct >= 0.015 for s in setups)

    def test_mtf_daily_filter_blocks_opposing(self):
        candles = _squeeze_then_expand()
        # direcao diaria CONTRARIA (trend_down) em todos => bloqueia longs
        dmap = {_ts_key(c.timestamp): "trend_down" for c in candles}
        setups = detect_f4_vol_expansion_continuation(
            candles, daily_direction_map=dmap, params=self._P)
        assert all(s.direction == "short" for s in setups) or setups == []
