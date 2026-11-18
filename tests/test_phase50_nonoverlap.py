"""
FASE 50 — validacao NAO-sobreposta. 100% OFFLINE, deterministico. Janelas
disjuntas por offset; net da hipotese mean-reversion (direcao FIXA); verdict
de sobrevivencia TRAVADO. Sinal real sobrevive; ruido = artefato. Sem rede.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.research.nonoverlap_validation import (
    nonoverlap_indices,
    realized_mean_reversion,
    survival_verdict,
    validate_signal,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class TestIndices:

    def test_disjoint_and_count(self):
        idx = nonoverlap_indices(1000, horizon=72, offset=0)
        # disjuntos: diferenca consecutiva == horizonte
        assert all(idx[i + 1] - idx[i] == 72 for i in range(len(idx) - 1))
        assert idx[0] == 0 and idx[-1] + 72 < 1000

    def test_offset_shifts(self):
        idx = nonoverlap_indices(1000, horizon=72, offset=24)
        assert idx[0] == 24


class TestRealized:

    def test_mean_reversion_positive_net(self):
        # feature alta => fwd negativo => short no topo lucra
        rng = random.Random(3)
        fx = [rng.uniform(-1, 1) for _ in range(300)]
        fy = [-0.02 * x + rng.gauss(0, 0.002) for x in fx]
        r = realized_mean_reversion(fx, fy, cost_pct=0.0026)
        assert r["net_after_cost"] > 0
        assert r["hit_rate"] > 0.5

    def test_noise_net_negative_after_cost(self):
        rng = random.Random(5)
        fx = [rng.gauss(0, 1) for _ in range(300)]
        fy = [rng.gauss(0, 0.01) for _ in range(300)]   # independente
        r = realized_mean_reversion(fx, fy, cost_pct=0.0026)
        assert r["net_after_cost"] < 0    # so paga custo => negativo


def _ts(n):
    return [_D0 + timedelta(hours=i) for i in range(n)]


class TestValidateAndSurvival:

    def _signal(self, n=3000, seed=7, strength=0.02, noise=0.002):
        rng = random.Random(seed)
        feat = [rng.uniform(-1, 1) for _ in range(n)]
        # alvo mean-reverting: feature alta agora => retorno futuro negativo
        fwd = [-strength * feat[i] + rng.gauss(0, noise) for i in range(n)]
        return feat, fwd

    def test_real_signal_survives(self):
        feat, fwd = self._signal()
        agg = validate_signal(feat, fwd, n=len(feat), horizon=72,
                              offsets=[0, 24, 48], timestamps=_ts(len(feat)))
        v, checks = survival_verdict(agg)
        assert agg["mean_net_after_cost"] > 0
        assert agg["frac_offsets_net_positive"] == 1.0
        assert v == "survived"

    def test_noise_is_artifact(self):
        rng = random.Random(99)
        n = 3000
        feat = [rng.gauss(0, 1) for _ in range(n)]
        fwd = [rng.gauss(0, 0.01) for _ in range(n)]
        agg = validate_signal(feat, fwd, n=n, horizon=72, offsets=[0, 24, 48],
                              timestamps=_ts(n))
        v, checks = survival_verdict(agg)
        assert v in ("artifact_of_overlap", "weak_unstable",
                     "insufficient_sample")
        assert v != "survived"

    def test_insufficient_sample(self):
        feat, fwd = self._signal(n=300)
        agg = validate_signal(feat, fwd, n=300, horizon=168, offsets=[0, 24],
                              timestamps=_ts(300))
        v, checks = survival_verdict(agg)
        assert v == "insufficient_sample"


class TestOrchestrator:

    def test_report_structure(self):
        import math
        from crypto_trading_bot.exchange.base_exchange import Candle
        from crypto_trading_bot.research.edge_research_phase50 import (
            run_nonoverlap_validation)
        from crypto_trading_bot.research.perp_signals import (
            load_funding, load_open_interest)
        c = [Candle(symbol="BTCUSDT", timeframe="1h",
                    timestamp=_D0 + timedelta(hours=i),
                    open=1000 + math.sin(i / 30) * 5, high=1006, low=994,
                    close=1000 + math.sin(i / 30) * 5, volume=100.0)
             for i in range(2500)]
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0001 * (1 if k % 3 else -1)} for k in range(320)])
        oi = load_open_interest([
            {"timestamp": (_D0 + timedelta(hours=i)).isoformat(),
             "open_interest": 1000.0 + i} for i in range(2500)])
        rep = run_nonoverlap_validation(c, funding_points=fund,
                                        oi_points=oi).to_dict()
        assert rep["demo_blocked"] and rep["strategy_promoted"] is False
        assert "survival_criterion" in rep
        assert rep["decision"]["verdict"] in ("PROPOR_HIPOTESE_FASE51",
                                              "REJEITAR")
        # side-by-side presente
        s0 = rep["signals"][0]["by_horizon"]
        any_h = next(iter(s0.values()))
        assert "side_by_side" in any_h and "overlapping_net" in \
            any_h["side_by_side"]
