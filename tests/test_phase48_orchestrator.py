"""
FASE 48 — orquestrador cost-aware. 100% OFFLINE, sintetico. Integra resample
4h/1d + F3/F4 + effective_config + standard_report (verdict 4 eixos) +
diagnostico de custo + decisao. OOS preservado (so DEV+VAL). Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.edge_research_phase48 import (
    run_edge_research48,
)
from crypto_trading_bot.research.perp_signals import load_funding

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles_1h(n=4000):
    out = []
    px = 100.0
    for i in range(n):
        px = max(20.0, px + math.sin(i / 50.0) * 0.6 + 0.02)
        ts = _D0 + timedelta(hours=i)
        out.append(Candle(symbol="BTCUSDT", timeframe="1h", timestamp=ts,
                          open=px - 0.3, high=px + 0.9, low=px - 0.9,
                          close=px, volume=100.0))
    return out


def _funding(n_days=170):
    return load_funding([
        {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
         "funding_rate": 0.0001 * (1 if k % 2 else -1)}
        for k in range(n_days * 3)])


class TestOrchestrator48:

    def _run(self):
        return run_edge_research48(
            _candles_1h(), funding_points=_funding(),
            dev=("2025-01-01", "2025-04-01"),
            val=("2025-04-01", "2025-05-01"),
            oos=("2025-05-01", "2025-06-01"), wf_folds=2, run_val=True)

    def test_structure_and_cost_diagnosis(self):
        d = self._run().to_dict()
        assert "cost_diagnosis" in d
        assert d["cost_diagnosis"]["round_trip_cost_bps"] == 26.0
        fams = {f["family"] for f in d["families"]}
        assert "F3_htf_trend_continuation" in fams
        assert "F4_vol_expansion_mtf" in fams
        assert d["demo_blocked"] and d["live_blocked"]
        assert d["strategy_promoted"] is False

    def test_standard_report_and_4axis_verdict(self):
        d = self._run().to_dict()
        f0 = d["families"][0]["block"]["dev"]["standard_report"]
        for sec in ("strategy_metrics", "temporal_breakdown",
                    "hyro_simulation", "verdict"):
            assert sec in f0
        assert set(f0["verdict"]) == {"edge_estatistico", "robustez_temporal",
                                      "hyro_challenge", "standard_trader",
                                      "bot_completo_E"}
        assert "monthly_table" in f0["temporal_breakdown"]

    def test_decision_in_set(self):
        d = self._run().to_dict()
        assert d["overall_decision"] in ("PROMOVER", "REFINAR", "REJEITAR")
        for f in d["families"]:
            assert f["decision"] in ("PROMOVER", "REFINAR", "REJEITAR")

    def test_oos_not_present_in_blocks(self):
        # OOS preservado: o orquestrador NAO avalia OOS (so dev/val)
        d = self._run().to_dict()
        for f in d["families"]:
            assert "oos" not in f["block"]
