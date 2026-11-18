"""
FASE 62 — H1 variance_ratio_regime_switch_1h. 100% OFFLINE, deterministico.
Verifica: formula VR causal/anti-lookahead; switch momentum/MR/neutro; entrada
no candle seguinte; stop no cap; orquestrador (VAL so se DEV passar; OOS
intocado; ranking 0,5%; 1% sensibilidade; orders_emitted=0). Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(closes):
    out = []
    for i, c in enumerate(closes):
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=c, high=c + abs(c) * 0.004,
                          low=c - abs(c) * 0.004, close=c, volume=100.0))
    return out


class TestVarianceRatio:

    def test_causal_truncation_invariance(self):
        from crypto_trading_bot.research.variance_ratio_family import (
            variance_ratio)
        closes = [100 + math.sin(i / 3.0) * 5 + i * 0.1 for i in range(120)]
        i = 80
        full = variance_ratio(closes, i, 24, 2)
        trunc = variance_ratio(closes[:i + 1], i, 24, 2)   # remove futuro
        assert full is not None and full == trunc          # so usa <= i

    def test_alternating_is_mean_reverting_vr_below_1(self):
        from crypto_trading_bot.research.variance_ratio_family import (
            variance_ratio)
        closes = [100.0 + (1.0 if i % 2 else -1.0) for i in range(60)]
        vr = variance_ratio(closes, 50, 24, 2)
        assert vr is not None and vr < 0.9          # oscilacao => MR (VR<1)

    def test_trending_vr_above_alternating(self):
        from crypto_trading_bot.research.variance_ratio_family import (
            variance_ratio)
        trend = [100.0 * (1.004 ** i) + math.sin(i) * 0.3 for i in range(60)]
        alt = [100.0 + (1.0 if i % 2 else -1.0) for i in range(60)]
        assert variance_ratio(trend, 50, 24, 2) > variance_ratio(alt, 50, 24, 2)


class TestDetector:

    def test_neutral_zone_no_setup(self):
        # serie ~ random walk suave => VR perto de 1 (zona neutra) em muitos i
        from crypto_trading_bot.research.variance_ratio_family import (
            detect_variance_ratio_regime_switch, variance_ratio)
        closes = [100.0 + math.sin(i / 11.0) * 2 for i in range(200)]
        c = _candles(closes)
        setups = detect_variance_ratio_regime_switch(c)
        # nenhum setup deve cair em i com 0,90<VR<1,10 (zona neutra)
        for s in setups:
            i = s.idx - 1                            # sinal = idx-1 (entrada e=i+1)
            vr = variance_ratio(closes, i, 24, 2)
            assert vr is not None and (vr >= 1.10 or vr <= 0.90)
            assert 0.005 <= s.stop_dist_pct <= 0.05

    def test_entry_is_next_candle(self):
        from crypto_trading_bot.research.variance_ratio_family import (
            detect_variance_ratio_regime_switch)
        closes = [100.0 + (1.0 if i % 2 else -1.0) for i in range(120)]
        c = _candles(closes)
        setups = detect_variance_ratio_regime_switch(c)
        # entry_ref deve ser o close do candle de ENTRADA (idx), nao do sinal
        for s in setups[:5]:
            assert abs(s.entry_ref - closes[s.idx]) < 1e-6


class TestOrchestrator62:

    def _run(self):
        from crypto_trading_bot.research.edge_research_phase62 import (
            run_edge_research62)
        # serie longa alternando regimes p/ gerar setups
        closes = [60000.0 * (1 + 0.0002 * i) + math.sin(i / 5.0) * 400
                  + math.sin(i / 1.7) * 150 for i in range(4000)]
        return run_edge_research62(
            _candles(closes), dev=("2025-01-01", "2025-03-01"),
            val=("2025-03-01", "2025-04-01"), wf_folds=2).to_dict()

    def test_dev_dual_profile_no_oos(self):
        d = self._run()
        assert d["decision"] in ("CANDIDATA_PENDENTE_APROVACAO_OOS", "REJEITAR")
        assert d["orders_emitted"] == 0
        assert d["confirmations"]["oos_consulted"] is False
        assert d["confirmations"]["ranking_decision_uses_only_0_5pct"] is True
        assert d["confirmations"]["one_pct_is_sensitivity_only"] is True
        h = d["hypothesis"]
        assert "gate" in h["dev"] and "sensitivity_1pct_separate" in h
        assert "variance_ratio_formula" in h
        # se DEV falhou, VAL nao roda
        if d["decision"] == "REJEITAR" and "val" not in h:
            assert d["confirmations"]["val_not_consulted_because_dev_failed"]
