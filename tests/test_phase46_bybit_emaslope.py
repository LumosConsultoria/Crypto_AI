"""
FASE 46 — Bybit Linear + EMA-slope. Testes 100% OFFLINE, deterministicos.
Direcao 1h por EMA-slope (causal/anti-lookahead); alinhamento causal a TF
de execucao; sizing derivado da RiskConfig (sob caps); ablacao 5m (B) so
roda se A sobreviver ao DEV. Sem rede/ordem/secret. Piso 0.005 nao alterado.
O provider real Bybit NUNCA e chamado em teste.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.htf_direction import (
    align_direction_to_exec,
    ema_slope_direction,
)
from crypto_trading_bot.research.edge_research_phase46 import (
    _sizing_from_riskconfig,
    run_edge_research46,
)
from crypto_trading_bot.research.htf_regime_filter import _ts_key

_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(n, step_min, price_fn):
    out = []
    tf = f"{step_min}m" if step_min < 60 else "1h"
    for i in range(n):
        px = float(price_fn(i))
        ts = _START + timedelta(minutes=step_min * i)
        out.append(Candle(symbol="BTCUSDT", timeframe=tf, timestamp=ts,
                          open=px, high=px + 0.5, low=px - 0.5, close=px,
                          volume=100.0))
    return out


# --------------------------- EMA-slope direction --------------------------

class TestEmaSlopeDirection:

    def test_uptrend_is_trend_up(self):
        c1h = _candles(120, 60, lambda i: 100.0 + i)   # subindo
        d = ema_slope_direction(c1h, ema_period=50, slope_k=6,
                                threshold=0.001)
        assert d[-1] == "trend_up"

    def test_downtrend_is_trend_down(self):
        c1h = _candles(120, 60, lambda i: 100.0 + (120 - i))  # caindo
        d = ema_slope_direction(c1h, ema_period=50, slope_k=6,
                                threshold=0.001)
        assert d[-1] == "trend_down"

    def test_flat_is_none(self):
        c1h = _candles(120, 60, lambda i: 100.0)       # plano
        d = ema_slope_direction(c1h, ema_period=50, slope_k=6,
                                threshold=0.001)
        assert d[-1] is None

    def test_warmup_is_none(self):
        c1h = _candles(120, 60, lambda i: 100.0 + i)
        d = ema_slope_direction(c1h, ema_period=50, slope_k=6)
        assert d[0] is None and d[5] is None   # i < slope_k

    def test_causal_no_lookahead(self):
        # direcao no indice i nao muda ao truncar o futuro (usa so <=i).
        c1h = _candles(120, 60, lambda i: 100.0 + i)
        full = ema_slope_direction(c1h, ema_period=50, slope_k=6)
        i = 80
        truncated = ema_slope_direction(c1h[:i + 1], ema_period=50, slope_k=6)
        assert truncated[i] == full[i]


# --------------------------- alinhamento causal ---------------------------

class TestAlignDirection:

    def test_exec_uses_last_closed_1h(self):
        c1h = _candles(5, 60, lambda i: 100.0 + i)
        dir_1h = ["trend_up"] * 5
        c15 = _candles(20, 15, lambda i: 100.0)
        amap = align_direction_to_exec(c15, c1h, dir_1h,
                                       low_interval_minutes=15)
        # 15m idx3 decision=+60min == close 1h0 => usa dir do 1h0
        assert amap[_ts_key(c15[3].timestamp)] == "trend_up"
        # 15m idx2 decision=+45 < 60 => nenhum 1h fechado => None
        assert amap[_ts_key(c15[2].timestamp)] is None


# --------------------------- sizing RiskConfig ----------------------------

class TestSizing:

    def test_derived_under_caps(self):
        from crypto_trading_bot.config.risk_config import get_risk_config
        rc = get_risk_config()
        s = _sizing_from_riskconfig(5000.0)
        size = s["position_size_usd"]
        # derivado de margin * max_position_size_pct * capital
        assert size == pytest.approx(0.90 * rc.max_position_size_pct * 5000.0)
        # sob o cap de posicao e de exposicao
        assert size <= rc.max_position_size_pct * 5000.0
        assert size <= rc.max_exposure_per_asset_pct * 5000.0
        assert s["derivation"]["margin"] == 0.90


# --------------------------- ablacao B so apos A --------------------------

class TestAblationControl:

    def test_b_skipped_when_a_early_stops(self):
        # candles PLANOS => sem setups => A DEV 0 trades => insufficient_sample
        # => B (ablacao 5m) NAO deve rodar.
        c1h = _candles(400, 60, lambda i: 100.0)
        c15 = _candles(1600, 15, lambda i: 100.0)
        c5 = _candles(4800, 5, lambda i: 100.0)
        rep = run_edge_research46(
            c5, c15, c1h, dev=("2025-01-01", "2025-01-15"),
            val=("2025-01-15", "2025-01-20"), oos=("2025-01-20", "2025-01-25"),
            wf_folds=2, run_oos=False)
        d = rep.to_dict()
        h = d["hypotheses"][0]
        assert h["variants"]["A"]["early_stop"] is not None     # A parou
        assert "skipped" in h["variants"]["B"]                  # B nao rodou
        assert d["overall_verdict"] == "REJEITAR"
        assert d["strategy_promoted"] is False
