"""
FASE 44 — Strategy Edge Research. Testes 100% OFFLINE, deterministicos.
Cobrem: alinhamento HTF CAUSAL por close_time (anti off-by-one/lookahead),
gating do wrapper, metricas (concentracao sobre gross profit, gross PF,
IC bootstrap) e logica de verdict (criticos/nao-criticos/amostra/early-stop).
Sem rede/ordem/secret. RiskEngine/ModeGuard/piso NAO sao tocados.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.market_regime import classify_regimes
from crypto_trading_bot.research import edge_research_phase44 as er
from crypto_trading_bot.research.htf_regime_filter import (
    HtfRegimeGatedStrategy,
    align_htf_regime,
    allowed_regimes_for,
    select_htf_index_by_close,
    _ts_key,
)
from crypto_trading_bot.strategies.signal_model import (
    StrategyAction,
    StrategySignal,
)

_START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(n, step_min, *, base=100.0):
    """Candles deterministicos com leve oscilacao (suficiente p/ regime)."""
    tf = f"{step_min}m"
    out = []
    for i in range(n):
        px = base + 10.0 * math.sin(i / 7.0) + i * 0.05
        ts = _START + timedelta(minutes=step_min * i)
        out.append(Candle(symbol="BTCUSDT", timeframe=tf, timestamp=ts,
                          open=px, high=px + 1.0, low=px - 1.0, close=px,
                          volume=100.0 + i))
    return out


# --------------------------- alinhamento causal ---------------------------

class TestHtfAlignment:

    def test_causal_close_time_matches_manual(self):
        c15 = _candles(200, 15)
        c5 = _candles(600, 5)
        amap = align_htf_regime(c5, c15, lookback=20)
        # labels NAO sao 1:1 (warmup): mapeia por lab.index
        reg_by_idx = {lab.index: lab.primary_regime
                      for lab in classify_regimes(c15, lookback=20).labels}
        for c in c5:
            decision = c.timestamp + timedelta(minutes=5)
            j = -1
            for k in range(len(c15)):
                if c15[k].timestamp + timedelta(minutes=15) <= decision:
                    j = k
                else:
                    break
            expected = reg_by_idx.get(j) if j >= 0 else None
            assert amap[_ts_key(c.timestamp)] == expected

    def test_off_by_one_boundary_pure_index(self):
        # Logica de selecao por close_time, deterministica (sem regime/dados).
        c15 = _candles(10, 15)
        c5 = _candles(20, 5)
        idxs = select_htf_index_by_close(c5, c15)
        # decision_time(5m i) = open+5min; close(15m j) = open_j+15min.
        assert idxs[0] == -1     # +5  < primeiro close (+15)
        assert idxs[1] == -1     # +10 < +15
        assert idxs[2] == 0      # +15 == close 15m[0] => elegivel (boundary)
        assert idxs[3] == 0      # +20: 15m[1] fecha +30 (ainda nao)
        assert idxs[4] == 0      # +25
        assert idxs[5] == 1      # +30 == close 15m[1] => boundary
        assert idxs[6] == 1      # +35


# --------------------------- gating do wrapper ----------------------------

class _AlwaysBuy:
    name = "always_buy"

    def evaluate(self, features):
        return StrategySignal.buy(symbol="BTCUSDT", strategy_name=self.name,
                                  entry_price=100.0, stop_loss_price=99.0,
                                  position_size_usd=50.0)

    def generate_signal(self, md):
        return None

    def on_signal_approved(self, s):
        pass

    def on_signal_rejected(self, s, r):
        pass

    def on_trade_closed(self, sym, pnl):
        pass

    def reset(self):
        pass


class TestGating:

    def _features(self, ts):
        import pandas as pd
        return {"symbol": "BTCUSDT", "timestamps": pd.Series([ts])}

    def test_allows_in_regime_blocks_off_regime_and_none(self):
        ts0 = _START
        ts1 = _START + timedelta(minutes=5)
        ts2 = _START + timedelta(minutes=10)
        regime_map = {_ts_key(ts0): "range", _ts_key(ts1): "trend_up",
                      _ts_key(ts2): None}
        w = HtfRegimeGatedStrategy(_AlwaysBuy(), regime_map, ("range",))
        assert w.evaluate(self._features(ts0)).action == StrategyAction.BUY
        assert w.evaluate(self._features(ts1)).action == StrategyAction.HOLD
        assert w.evaluate(self._features(ts2)).action == StrategyAction.HOLD
        assert w.blocked_by_htf == 2
        assert w.name == "always_buy_htf15m"

    def test_allowed_regimes_for(self):
        assert "trend_up" in allowed_regimes_for("H1_trend_vol_expansion")
        assert allowed_regimes_for("H2_range_mean_reversion") == ("range",)


# --------------------------- metricas -------------------------------------

class _T:
    def __init__(self, pnl, gross=None, idx=0):
        self.pnl_usd = pnl
        self.gross_pnl_usd = gross if gross is not None else pnl
        self.entry_candle_idx = idx


class _Rep:
    def __init__(self, trades):
        self.trades = trades


class TestMetrics:

    def test_gross_pf(self):
        rep = _Rep([_T(10, 12), _T(-5, -5), _T(20, 22)])
        # gross win=34, gross loss=5 => 6.8
        assert er._gross_pf(rep) == pytest.approx(6.8, rel=1e-3)

    def test_concentration_over_gross_profit(self):
        # 20 vencedores: um gigante + 19 pequenos
        trades = [_T(1000.0)] + [_T(1.0) for _ in range(19)]
        rep = _Rep(trades)
        c = er._concentration(rep)
        # top 5% de 20 = 1 trade (o de 1000); gross=1019 => share ~0.981
        assert c["n_winners"] == 20
        assert c["top5pct_share"] == pytest.approx(1000 / 1019, rel=1e-3)

    def test_bootstrap_ci_deterministic_and_ordered(self):
        ci = er._bootstrap_expectancy_ci([1.0, 2.0, 3.0, 4.0], seed=7)
        assert ci["ci_low"] <= ci["mean"] <= ci["ci_high"]
        ci2 = er._bootstrap_expectancy_ci([1.0, 2.0, 3.0, 4.0], seed=7)
        assert ci == ci2   # deterministico


# --------------------------- verdict --------------------------------------

class TestVerdict:

    def _oos_pass(self):
        return {"total_trades": 150, "total_pnl_usd": 50.0,
                "profit_factor_net": 1.25,
                "expectancy_ci": {"ci_low": 0.05, "mean": 0.3},
                "max_drawdown_pct": -10.0, "return_over_dd": 5.0,
                "concentration": {"top5pct_share": 0.2},
                "regime": {"range": {"sufficient": True}},
                "baseline": {"bh_return_over_dd": 2.0}}

    def test_promote_when_all_critical_and_4_noncritical(self):
        oos = self._oos_pass()
        stressed = {"profit_factor_net": 1.05}
        val = {"monthly": {"sign_consistency": 0.7,
                           "net_excluding_best_month": 10.0}}
        sens = {"stable": True}
        crit = er._critical_gates(oos, stressed)
        noncrit = er._noncritical_gates(oos, val, sens)
        assert all(crit.values())
        assert er._decide(crit, noncrit, sample_ok=True) == \
            "PROMOVER_PARA_PAPER"

    def test_reject_when_critical_fails(self):
        oos = self._oos_pass()
        oos["profit_factor_net"] = 1.0   # falha PF critico
        crit = er._critical_gates(oos, {"profit_factor_net": 1.05})
        noncrit = er._noncritical_gates(oos, {"monthly": {}}, {"stable": True})
        assert er._decide(crit, noncrit, sample_ok=True) == "REJEITAR"

    def test_reject_when_insufficient_sample(self):
        oos = self._oos_pass()
        crit = er._critical_gates(oos, {"profit_factor_net": 1.05})
        noncrit = er._noncritical_gates(oos, {"monthly": {}}, {"stable": True})
        assert er._decide(crit, noncrit, sample_ok=False) == "REJEITAR"

    def test_refine_when_critical_ok_but_noncritical_weak(self):
        oos = self._oos_pass()
        oos["concentration"] = {"top5pct_share": 0.9}     # concentrado
        oos["regime"] = {}                                # sem regime sufic.
        oos["baseline"] = {"bh_return_over_dd": 99.0}     # nao bate baseline
        stressed = {"profit_factor_net": 1.05}
        val = {"monthly": {"sign_consistency": 0.2,
                           "net_excluding_best_month": -5.0}}
        sens = {"stable": False}
        crit = er._critical_gates(oos, stressed)
        noncrit = er._noncritical_gates(oos, val, sens)
        assert all(crit.values())
        assert sum(noncrit.values()) < 4
        assert er._decide(crit, noncrit, sample_ok=True) == \
            "REFINAR_COM_HIPOTESE_ESPECIFICA"

    def test_sample_ok_thresholds(self):
        assert er._sample_ok({"total_trades": 150}, 250, tf="5m") is True
        assert er._sample_ok({"total_trades": 80}, 250, tf="5m") is False
        assert er._sample_ok({"total_trades": 50}, 90, tf="15m") is True


class TestEarlyStop:

    def test_no_edge_dev_stops(self):
        dev = {"profit_factor_net": 0.9, "expectancy_net_usd": -0.1,
               "total_trades": 100, "monthly": {"sign_consistency": 0.5}}
        assert er._early_stop(dev) == "no_edge_dev"

    def test_insufficient_sample_dev(self):
        dev = {"profit_factor_net": 2.0, "expectancy_net_usd": 1.0,
               "total_trades": 10, "monthly": {"sign_consistency": 0.9}}
        assert er._early_stop(dev) == "insufficient_sample_dev"

    def test_concentrated_dev(self):
        dev = {"profit_factor_net": 1.3, "expectancy_net_usd": 0.2,
               "total_trades": 100, "monthly": {"sign_consistency": 0.2}}
        assert er._early_stop(dev) == "profit_concentrated_dev"

    def test_survives(self):
        dev = {"profit_factor_net": 1.3, "expectancy_net_usd": 0.2,
               "total_trades": 100, "monthly": {"sign_consistency": 0.7}}
        assert er._early_stop(dev) is None
