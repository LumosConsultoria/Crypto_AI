"""
FASE 51 — F5 funding-swing MR + orquestrador dual-profile. 100% OFFLINE,
deterministico. Funding extremo => mean-reversion (alto=>short, baixo=>long);
stop em [1,5%,5%]. Orquestrador: 5 verdicts + classification + analise 1% +
OOS preservado. Sem rede/ordem. Provider real nunca em teste.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.funding_swing_family import (
    detect_f5_funding_swing,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles_4h(n=120, base=1000.0):
    out = []
    px = base
    for i in range(n):
        px = base + math.sin(i / 12.0) * 30.0   # oscila ~+-3%
        ts = _D0 + timedelta(hours=4 * i)
        out.append(Candle(symbol="BTCUSDT", timeframe="4h", timestamp=ts,
                          open=px - 2, high=px + 6, low=px - 6, close=px,
                          volume=100.0))
    return out


class TestF5:

    def test_high_funding_emits_short(self):
        candles = _candles_4h()
        fp = [0.9] * len(candles)              # funding alto em todo lugar
        setups = detect_f5_funding_swing(candles, fp)
        assert len(setups) >= 1
        assert all(s.direction == "short" for s in setups)
        assert all(s.stop > s.entry_ref for s in setups)      # stop acima
        assert all(0.015 <= s.stop_dist_pct <= 0.05 for s in setups)

    def test_low_funding_emits_long(self):
        candles = _candles_4h()
        fp = [0.05] * len(candles)
        setups = detect_f5_funding_swing(candles, fp)
        assert len(setups) >= 1
        assert all(s.direction == "long" for s in setups)

    def test_neutral_funding_no_setup(self):
        candles = _candles_4h()
        assert detect_f5_funding_swing(candles, [0.5] * len(candles)) == []

    def test_funding_none_skips(self):
        candles = _candles_4h()
        assert detect_f5_funding_swing(candles, [None] * len(candles)) == []


def _candles_1h(n=4000):
    out = []
    for i in range(n):
        px = 1000.0 + math.sin(i / 60.0) * 25.0
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1, high=px + 3, low=px - 3, close=px,
                          volume=100.0))
    return out


class TestOrchestrator51:

    def _run(self):
        from crypto_trading_bot.research.edge_research_phase51 import (
            run_edge_research51)
        from crypto_trading_bot.research.perp_signals import (
            load_funding, load_open_interest)
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0008 * (1 if (k // 10) % 2 else -1)}
            for k in range(170 * 3)])
        oi = load_open_interest([
            {"timestamp": (_D0 + timedelta(hours=i)).isoformat(),
             "open_interest": 1000.0 + i} for i in range(4000)])
        return run_edge_research51(
            _candles_1h(), funding_points=fund, oi_points=oi,
            dev=("2025-01-01", "2025-04-01"),
            val=("2025-04-01", "2025-05-01"),
            oos=("2025-05-01", "2025-06-01"), wf_folds=2, run_val=True)

    def test_dual_profile_and_classification(self):
        d = self._run().to_dict()
        fam = d["family"]
        sr = fam["dev_05pct"]["standard_report"]
        # dual-profile: 5 verdicts + classification + analise 1%
        assert set(sr["verdict"]) == {"edge_estatistico", "robustez_temporal",
                                      "hyro_challenge", "standard_trader",
                                      "bot_completo_E"}
        assert sr["classification"] in (
            "candidata_paper", "edge_possivel_incompativel_com_challenge",
            "sem_edge_operacional")
        assert "standard_trader_evaluation" in sr
        assert "standard_trader_1pct_analysis" in fam
        assert d["decision"] in ("PROMOVER", "REFINAR", "REJEITAR")
        assert d["demo_blocked"] and d["strategy_promoted"] is False

    def test_oos_not_evaluated(self):
        d = self._run().to_dict()
        # OOS preservado: orquestrador nao avalia OOS
        assert "oos_05pct" not in d["family"]

    def test_final_classification_reflects_dev_and_val(self):
        d = self._run().to_dict()
        fam = d["family"]
        # final_classification (familia) != classification de segmento isolado
        assert "final_classification" in fam
        assert fam["final_classification"] in (
            "candidata_paper", "dev_candidate_val_failed",
            "edge_possivel_incompativel_com_challenge", "sem_edge_operacional")
        assert "dev_classification" in fam and "val_classification" in fam


def test_final_classification_mapping():
    from crypto_trading_bot.research.edge_research_phase51 import (
        _final_classification)
    # DEV candidata mas VAL falhou => dev_candidate_val_failed (caso real F5)
    assert _final_classification("candidata_paper", "sem_edge_operacional",
                                 True, None) == "dev_candidate_val_failed"
    # passa nos dois => candidata_paper
    assert _final_classification("candidata_paper", "candidata_paper",
                                 True, None) == "candidata_paper"
    # DEV ja reprovado => sem_edge_operacional
    assert _final_classification("sem_edge_operacional", None, False,
                                 None) == "sem_edge_operacional"
    # early-stop no DEV => sem_edge_operacional
    assert _final_classification("candidata_paper", None, False,
                                 "no_edge_dev") == "sem_edge_operacional"
