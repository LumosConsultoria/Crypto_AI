"""
FASE 53 (re-escopo) — detectores normais + orquestrador via research loop.
100% OFFLINE, deterministico. Verifica deteccao (direcao/stop dentro do cap),
dual-profile por standard_report e que o loop NAO toca OOS. Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles_1h(n=2400, base=1000.0):
    out = []
    for i in range(n):
        px = base + math.sin(i / 40.0) * 25.0 + math.sin(i / 6.0) * 6.0
        vol = 100.0 + (500.0 if i % 200 == 0 else (i % 11))   # picos de volume
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1.5, high=px + 5, low=px - 5, close=px,
                          volume=vol))
    return out


class TestDetectors:

    def test_volume_climax_emits_reversal_within_cap(self):
        from crypto_trading_bot.research.normal_families import (
            detect_volume_climax_reversal)
        setups = detect_volume_climax_reversal(_candles_1h())
        assert setups, "picos de volume devem gerar setups"
        for s in setups:
            assert s.direction in ("long", "short")
            assert 0.005 <= s.stop_dist_pct <= 0.05      # piso/cap respeitados

    def test_seasonality_causal_buckets(self):
        from crypto_trading_bot.research.normal_families import (
            detect_seasonality_session_bias)
        # min_samples baixo p/ disparar no fixture sintetico
        setups = detect_seasonality_session_bias(
            _candles_1h(), params={"min_samples": 5})
        assert isinstance(setups, list)
        for s in setups:
            assert 0.005 <= s.stop_dist_pct <= 0.05

    def test_oi_divergence_needs_oi_falling(self):
        from crypto_trading_bot.research.normal_families import (
            detect_oi_divergence_exhaustion)
        c = _candles_1h()
        oc_down = [-0.01] * len(c)        # OI sempre caindo => pode disparar
        oc_none = [None] * len(c)
        assert detect_oi_divergence_exhaustion(c, oc_none) == []
        s_down = detect_oi_divergence_exhaustion(c, oc_down)
        for s in s_down:
            assert 0.005 <= s.stop_dist_pct <= 0.05


class TestOrchestrator53:

    def _run(self):
        from crypto_trading_bot.research.edge_research_phase53 import (
            run_edge_research53)
        from crypto_trading_bot.research.perp_signals import (
            load_funding, load_open_interest)
        c = _candles_1h()
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0006 * math.sin(k / 4.0)}
            for k in range(len(c) // 8 + 2)])
        oi = load_open_interest([
            {"timestamp": (_D0 + timedelta(hours=i)).isoformat(),
             "open_interest": 1000.0 + 50.0 * math.sin(i / 30.0)}
            for i in range(len(c))])
        return run_edge_research53(
            c, funding_points=fund, oi_points=oi,
            dev=("2025-01-01", "2025-03-01"),
            val=("2025-03-01", "2025-04-01"), wf_folds=2)

    def test_loop_runs_dual_profile_no_oos(self):
        d = self._run().to_dict()
        assert d["decision"] in ("CANDIDATA_PENDENTE_APROVACAO_OOS",
                                 "NENHUMA_CANDIDATA_DEV_VAL")
        assert d["loop"]["oos_consulted"] is False
        assert d["strategy_promoted"] is False
        # cada hipotese testada tem classificacao DEV + analise 1% separada
        for name, b in d["per_hypothesis"].items():
            assert "dev_classification" in b
            assert "trader_padrao_1pct_dev" in b
        # standard_report dual-profile presente (5 verdicts)
        for b in d["per_hypothesis"].values():
            v = b.get("dev_verdict") or {}
            if v:
                assert "hyro_challenge" in v and "standard_trader" in v
