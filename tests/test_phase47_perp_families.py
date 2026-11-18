"""
FASE 47 — familias perp F1 (funding-extreme fade) e F2 (OI-confirmed
momentum). 100% OFFLINE, deterministico. Gate = sinal perpetual (funding/OI),
NAO so preco (diferente das rejeitadas). Anti-lookahead; piso 0,5% via HOLD
(below_floor). Sem rede/ordem/secret. Provider real nunca em teste.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.perp_families import (
    PerpSetupStrategy,
    detect_f1_funding_fade,
    detect_f2_oi_momentum,
)
from crypto_trading_bot.research.htf_regime_filter import _ts_key

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _ramp_up(n=90, base=100.0, flat=60, slope=0.8):
    """Base estavel + rampa de alta (gera breakout e percent_b alto)."""
    out = []
    for i in range(n):
        px = base if i < flat else base + slope * (i - flat)
        ts = _D0 + timedelta(minutes=15 * i)
        out.append(Candle(symbol="BTCUSDT", timeframe="15m", timestamp=ts,
                          open=px - 0.2, high=px + 0.6, low=px - 0.6,
                          close=px, volume=10.0))
    return out


def _ramp_down(n=90, base=200.0, flat=60, slope=0.8):
    out = []
    for i in range(n):
        px = base if i < flat else base - slope * (i - flat)
        ts = _D0 + timedelta(minutes=15 * i)
        out.append(Candle(symbol="BTCUSDT", timeframe="15m", timestamp=ts,
                          open=px + 0.2, high=px + 0.6, low=px - 0.6,
                          close=px, volume=10.0))
    return out


class TestF2OIMomentum:

    def test_breakout_confirmed_by_oi_expansion(self):
        candles = _ramp_up()
        oi_change = [0.02] * len(candles)         # expansao em todo lugar
        setups = detect_f2_oi_momentum(candles, oi_change)
        assert len(setups) >= 1
        assert all(s.direction == "long" for s in setups)

    def test_no_oi_expansion_skips_divergence(self):
        candles = _ramp_up()
        oi_change = [0.0] * len(candles)          # sem dinheiro novo
        setups = detect_f2_oi_momentum(candles, oi_change)
        assert setups == []

    def test_oi_none_skips(self):
        candles = _ramp_up()
        oi_change = [None] * len(candles)
        assert detect_f2_oi_momentum(candles, oi_change) == []


class TestF1FundingFade:

    def test_high_funding_plus_stretch_up_fades_short(self):
        candles = _ramp_up()
        fp = [0.95] * len(candles)                # longs lotados
        setups = detect_f1_funding_fade(candles, fp)
        assert len(setups) >= 1
        assert all(s.direction == "short" for s in setups)
        # stop ACIMA da entrada (fade short)
        assert all(s.stop > s.entry_ref for s in setups)

    def test_low_funding_plus_stretch_down_fades_long(self):
        candles = _ramp_down()
        fp = [0.05] * len(candles)                # shorts lotados
        setups = detect_f1_funding_fade(candles, fp)
        assert len(setups) >= 1
        assert all(s.direction == "long" for s in setups)

    def test_neutral_funding_no_setup(self):
        candles = _ramp_up()
        fp = [0.5] * len(candles)                 # sem extremo
        assert detect_f1_funding_fade(candles, fp) == []

    def test_funding_none_skips(self):
        candles = _ramp_up()
        assert detect_f1_funding_fade(candles, [None] * len(candles)) == []


class TestPerpSetupStrategy:

    def test_emits_buy_at_setup_ts(self):
        candles = _ramp_up()
        oi_change = [0.02] * len(candles)
        setups = detect_f2_oi_momentum(candles, oi_change)
        assert setups
        strat = PerpSetupStrategy(setups=setups, family_id="F2",
                                  position_size_usd=2500.0)
        s0 = setups[0]
        import pandas as pd
        feats = {"symbol": "BTCUSDT",
                 "timestamps": pd.Series([s0.open_ts]),
                 "last_close": s0.entry_ref}
        sig = strat.evaluate(feats)
        assert sig.action.value == "buy"

    def test_below_floor_holds(self):
        # setup com stop muito proximo => below_floor => HOLD
        import pandas as pd
        from crypto_trading_bot.research.mtf_setups import Setup
        ts = _D0
        s = Setup(idx=0, open_ts=ts, close_ts=ts + timedelta(minutes=15),
                  direction="long", entry_ref=100.0, stop=99.9,
                  target=100.2, stop_dist_pct=0.001, below_floor=True,
                  atr=1.0, setup_id="F2_0")
        strat = PerpSetupStrategy(setups=[s], family_id="F2",
                                  position_size_usd=2500.0)
        feats = {"symbol": "BTCUSDT", "timestamps": pd.Series([ts]),
                 "last_close": 100.0}
        sig = strat.evaluate(feats)
        assert strat.blocked_below_floor == 1
        assert sig.action.value == "hold"        # below_floor => HOLD
