"""
FASE 48 — cost_viability: diagnostico de custo minimo p/ viabilidade liquida.
100% OFFLINE. cost_in_R = round_trip_pct/stop_dist_pct; stops maiores reduzem
custo em R. Empirico a partir de trades. Sem rede/ordem.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from crypto_trading_bot.research.cost_viability import (
    build_cost_diagnosis,
    cost_in_r,
    diagnose_from_trades,
    min_stop_for_cost_in_r,
    round_trip_cost_pct,
    viability_table,
)

# Bybit linear realistic: taker 6 / slippage 5 / spread 2 bps (fracoes)
_RT = round_trip_cost_pct(taker_fee_pct=0.0006, slippage_pct=0.0005,
                          spread_pct=0.0002)


class TestCostMath:

    def test_round_trip_26bps(self):
        assert _RT == pytest.approx(0.0026)        # 26 bps round-trip

    def test_cost_in_r_decreases_with_bigger_stop(self):
        assert cost_in_r(0.005, _RT) == pytest.approx(0.52)
        assert cost_in_r(0.02, _RT) == pytest.approx(0.13)
        assert cost_in_r(0.05, _RT) == pytest.approx(0.052)

    def test_min_stop_for_target_cost_in_r(self):
        # p/ custo <= 0,10R => stop >= 2,6%
        assert min_stop_for_cost_in_r(_RT, 0.10) == pytest.approx(0.026)

    def test_viability_table_notional_and_cost(self):
        t = viability_table(round_trip_pct=_RT, risk_base_usd=25.0,
                            stops=(0.005, 0.02))
        assert t[0]["notional_usd"] == pytest.approx(5000.0)
        assert t[0]["cost_usd_per_trade"] == pytest.approx(13.0)
        assert t[0]["cost_in_r"] == pytest.approx(0.52)
        assert t[1]["notional_usd"] == pytest.approx(1250.0)


class TestEmpirical:

    def test_diagnose_from_trades_cost_destroys_edge(self):
        # emula F2 B DEV: gross ~+0,91/trade, mas notional grande => custo alto
        trades = [SimpleNamespace(position_size_usd=1669.0,
                                  gross_pnl_usd=0.91, pnl_usd=-3.43)
                  for _ in range(82)]
        d = diagnose_from_trades(trades, round_trip_pct=_RT,
                                 risk_base_usd=25.0)
        assert d["trades"] == 82
        assert d["viable"] is False
        assert d["avg_cost_usd_per_trade"] > d["avg_gross_pnl_usd_per_trade"]
        assert "CUSTO destroi" in d["diagnosis"]

    def test_viable_when_gross_exceeds_cost(self):
        trades = [SimpleNamespace(position_size_usd=1000.0,
                                  gross_pnl_usd=10.0, pnl_usd=7.0)
                  for _ in range(20)]
        d = diagnose_from_trades(trades, round_trip_pct=_RT,
                                 risk_base_usd=25.0)
        assert d["viable"] is True


class TestBuildDiagnosis:

    def test_full_diagnosis_structure(self):
        d = build_cost_diagnosis(taker_fee_pct=0.0006, slippage_pct=0.0005,
                                 spread_pct=0.0002, risk_base_usd=25.0,
                                 daily_loss_limit_usd=200.0)
        assert d["round_trip_cost_bps"] == pytest.approx(26.0)
        assert d["min_stop_for_target_cost_in_r"]["min_stop_dist_pct"] \
            == pytest.approx(0.026)
        assert d["max_pure_cost_trades_per_day"] is not None
        assert len(d["viability_table"]) == 5
