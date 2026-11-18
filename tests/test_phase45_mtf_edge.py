"""
FASE 45 — Multi-TF edge research. Testes 100% OFFLINE, deterministicos.
Causalidade (exec->15m/1h por close_time, anti off-by-one); deteccao de
setups 15m (H1) + stop estrutural + below_floor; gating das variantes A
(15m) e B (5m gatilho na janela). Sem rede/ordem/secret. Piso 0.005 nao
alterado.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.htf_regime_filter import (
    select_htf_index_by_close,
    _ts_key,
)
from crypto_trading_bot.research.mtf_setups import Setup, detect_setups
from crypto_trading_bot.research.mtf_strategy import (
    MtfSetupStrategyA,
    MtfSetupStrategyB,
)
from crypto_trading_bot.strategies.signal_model import StrategyAction

_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _c(ts, o, h, l, cl, tf):
    return Candle(symbol="BTCUSDT", timeframe=tf, timestamp=ts,
                  open=o, high=h, low=l, close=cl, volume=100.0)


# --------------------------- causalidade ----------------------------------

class TestAlignmentMTF:

    def test_5m_to_1h_off_by_one(self):
        c5 = [_c(_START + timedelta(minutes=5 * i), 1, 1, 1, 1, "5m")
              for i in range(40)]
        c1h = [_c(_START + timedelta(minutes=60 * j), 1, 1, 1, 1, "1h")
               for j in range(5)]
        idx = select_htf_index_by_close(c5, c1h, low_interval_minutes=5,
                                        high_interval_minutes=60)
        # decision(5m i)=open+5min; close(1h0)=+60min.
        # 5m index 10 => open=50min, decision=55min < 60 => -1
        assert idx[10] == -1
        # 5m index 11 => open=55, decision=60 == close 1h0 => 0 (boundary)
        assert idx[11] == 0
        # 5m index 12 => decision=65 > 60, <120 => still 0
        assert idx[12] == 0
        # 5m index 23 => open=115, decision=120 == close 1h1 => 1
        assert idx[23] == 1

    def test_15m_to_1h_off_by_one(self):
        c15 = [_c(_START + timedelta(minutes=15 * i), 1, 1, 1, 1, "15m")
               for i in range(20)]
        c1h = [_c(_START + timedelta(minutes=60 * j), 1, 1, 1, 1, "1h")
               for j in range(5)]
        idx = select_htf_index_by_close(c15, c1h, low_interval_minutes=15,
                                        high_interval_minutes=60)
        # 15m idx3 => open=45,decision=60 == close 1h0 => 0
        assert idx[3] == 0
        assert idx[2] == -1     # decision=45 < 60
        assert idx[7] == 1      # open=105,decision=120 == close 1h1


# --------------------------- deteccao de setups ---------------------------

class TestSetupDetection:

    def _flat_then_breakout(self):
        # 60 candles flat (baixa vol) + breakout de alta com expansao de ATR.
        candles = []
        for i in range(60):
            px = 100.0
            ts = _START + timedelta(minutes=15 * i)
            candles.append(_c(ts, px, px + 0.2, px - 0.2, px, "15m"))
        # candle de expansao/rompimento: range grande, fecha acima dos highs
        for k, (rng, cl) in enumerate([(5.0, 105.0), (4.0, 107.0)]):
            ts = _START + timedelta(minutes=15 * (60 + k))
            candles.append(_c(ts, 100.0, cl + 1, 99.0, cl, "15m"))
        return candles

    def test_h1_breakout_long_setup(self):
        candles = self._flat_then_breakout()
        setups = detect_setups(candles, hypothesis="H1_trend_vol_expansion")
        assert len(setups) >= 1
        s = setups[0]
        assert s.direction == "long"
        assert s.stop < s.entry_ref < s.target
        assert s.stop_dist_pct > 0
        assert isinstance(s.below_floor, bool)
        # close_ts = open_ts + 15min (causal)
        assert s.close_ts == s.open_ts + timedelta(minutes=15)

    def test_detect_returns_wellformed_list_h2(self):
        candles = self._flat_then_breakout()
        setups = detect_setups(candles, hypothesis="H2_pullback_continuation")
        assert isinstance(setups, list)
        for s in setups:
            assert s.direction in ("long", "short")
            assert s.stop > 0 and s.entry_ref > 0


# --------------------------- variante A (15m) -----------------------------

def _setup(open_ts, direction="long", entry=100.0, stop=98.0, target=104.0,
           below=False):
    dist = abs(entry - stop) / entry
    return Setup(idx=0, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=15), direction=direction,
                 entry_ref=entry, stop=stop, target=target,
                 stop_dist_pct=(0.002 if below else dist),
                 below_floor=below, atr=1.0, setup_id="S1")


def _feat(ts, last_close=100.0):
    return {"symbol": "BTCUSDT", "timestamps": pd.Series([ts]),
            "last_close": last_close}


class TestVariantA:

    def test_emits_when_regime_aligned(self):
        ts = _START
        s = _setup(ts, "long")
        rmap = {_ts_key(ts): "trend_up"}
        strat = MtfSetupStrategyA(setups=[s], regime_map=rmap,
                                  hypothesis_id="H1", position_size_usd=1000)
        sig = strat.evaluate(_feat(ts))
        assert sig.action == StrategyAction.BUY
        assert sig.stop_loss_price == 98.0 and sig.take_profit_price == 104.0

    def test_blocks_when_regime_not_aligned(self):
        ts = _START
        strat = MtfSetupStrategyA(setups=[_setup(ts, "long")],
                                  regime_map={_ts_key(ts): "trend_down"},
                                  hypothesis_id="H1", position_size_usd=1000)
        assert strat.evaluate(_feat(ts)).action == StrategyAction.HOLD
        assert strat.regime_rejected == 1

    def test_blocks_below_floor(self):
        ts = _START
        strat = MtfSetupStrategyA(
            setups=[_setup(ts, "long", below=True)],
            regime_map={_ts_key(ts): "trend_up"}, hypothesis_id="H1",
            position_size_usd=1000)
        sig = strat.evaluate(_feat(ts))
        assert sig.action == StrategyAction.HOLD
        assert strat.blocked_below_floor == 1
        assert "structural_stop_below_floor" in sig.reason

    def test_no_setup_holds(self):
        ts = _START
        strat = MtfSetupStrategyA(setups=[], regime_map={}, hypothesis_id="H1",
                                  position_size_usd=1000)
        assert strat.evaluate(_feat(ts)).action == StrategyAction.HOLD


# --------------------------- variante B (5m gatilho) ----------------------

class TestVariantB:

    def test_triggers_within_window_after_setup(self):
        setup_close = _START + timedelta(minutes=15)   # setup 15m fecha aqui
        s = _setup(_START, "long", entry=100.0, stop=98.0, target=104.0)
        # regime_map p/ 5m: trend_up em todos
        # 5m candles apos o fechamento do setup
        strat = MtfSetupStrategyB(setups=[s], regime_map={},
                                  hypothesis_id="H1", position_size_usd=1000,
                                  window_candles=6, low_interval_minutes=5)
        # 5m candle cujo decision >= setup_close e dentro da janela; gatilho
        # exige close > entry_ref (100). regime trend_up.
        ts5 = setup_close   # 5m open == setup close; decision=+5min
        strat._regime_map = {_ts_key(ts5): "trend_up"}
        # sem gatilho: close <= entry
        assert strat.evaluate(_feat(ts5, last_close=99.5)).action == \
            StrategyAction.HOLD
        # com gatilho: close > entry
        sig = strat.evaluate(_feat(ts5, last_close=101.0))
        assert sig.action == StrategyAction.BUY
        assert sig.stop_loss_price == 98.0    # stop ESTRUTURAL do 15m
        assert sig.take_profit_price == 104.0

    def test_no_entry_outside_window(self):
        s = _setup(_START, "long", entry=100.0)
        strat = MtfSetupStrategyB(setups=[s], regime_map={},
                                  hypothesis_id="H1", position_size_usd=1000,
                                  window_candles=2, low_interval_minutes=5)
        # muito depois do fechamento do setup (fora da janela de 2*5min)
        far = _START + timedelta(minutes=60)
        strat._regime_map = {_ts_key(far): "trend_up"}
        assert strat.evaluate(_feat(far, last_close=101.0)).action == \
            StrategyAction.HOLD

    def test_regime_blocks_b(self):
        setup_close = _START + timedelta(minutes=15)
        s = _setup(_START, "long", entry=100.0)
        strat = MtfSetupStrategyB(setups=[s], regime_map={},
                                  hypothesis_id="H1", position_size_usd=1000,
                                  window_candles=6, low_interval_minutes=5)
        ts5 = setup_close
        strat._regime_map = {_ts_key(ts5): "trend_down"}   # contra direcao
        assert strat.evaluate(_feat(ts5, last_close=101.0)).action == \
            StrategyAction.HOLD
        assert strat.regime_rejected == 1
