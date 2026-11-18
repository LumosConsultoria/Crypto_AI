"""
FASE 49 — Signal Diagnostic Lab. 100% OFFLINE, deterministico. Estatisticas
(forward returns, Spearman IC, quantis, net apos custo, verdict), features
causais e orquestrador. Sem rede/ordem; OOS preservado (lab roda no slice
dado). Sem alterar modulo compartilhado.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.signal_diagnostics import (
    diagnose_feature,
    forward_returns,
    quantile_analysis,
    spearman,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class TestStats:

    def test_forward_returns_and_boundary(self):
        closes = [100.0, 110.0, 121.0, 133.1]
        fr = forward_returns(closes, horizon=1)
        assert fr[0] == pytest.approx(0.10)
        assert fr[-1] is None                  # alvo fora => None (nao OOS)

    def test_spearman_monotonic(self):
        a = list(range(50)); b = [x * 2.0 for x in a]
        assert spearman(a, b) == pytest.approx(1.0)
        assert spearman(a, list(reversed(b))) == pytest.approx(-1.0)

    def test_quantile_top_minus_bottom(self):
        # feature crescente => fwd crescente => top>bottom
        fx = list(range(500))
        fy = [x * 0.0001 for x in range(500)]
        q = quantile_analysis(fx, fy, n_quantiles=5, cost_pct=0.0026)
        assert q["top_minus_bottom"] > 0
        assert q["buckets"][-1]["mean_fwd_ret"] > q["buckets"][0][
            "mean_fwd_ret"]

    def test_net_is_direction_agnostic_negative_ic(self):
        # IC NEGATIVO: feature alta => fwd negativo. O net deve capturar o
        # |mean| extremo (operar short no topo), nao penalizar pelo sinal.
        fx = list(range(500))
        fy = [-(x - 250) * 0.0002 for x in range(500)]  # decrescente
        q = quantile_analysis(fx, fy, n_quantiles=5, cost_pct=0.0026)
        # top quantil tem mean bem negativo => |mean| - custo > 0
        assert q["net_top_extreme_after_cost"] > 0
        assert q["best_single_side_net_after_cost"] > 0


def _months_ts(n):
    # ~ n pontos espalhados em ~6 meses
    return [_D0 + timedelta(hours=6 * i) for i in range(n)]


class TestDiagnoseFeature:

    def test_real_relation(self):
        n = 800
        rng = random.Random(7)
        feature = [rng.uniform(-1, 1) for _ in range(n)]
        # fwd fortemente ligado a feature + ruido pequeno; spread > custo
        fwd = [0.02 * f + rng.gauss(0, 0.002) for f in feature]
        ts = _months_ts(n)
        d = diagnose_feature("f", feature, fwd, timestamps=ts)
        assert d["verdict"] == "real_relation"
        assert abs(d["ic_spearman"]) >= 0.05
        assert d["net_best_after_cost"] > 0

    def test_pure_noise_is_not_real_relation(self):
        n = 2000
        rng = random.Random(11)
        feature = [rng.gauss(0, 1) for _ in range(n)]
        fwd = [rng.gauss(0, 0.01) for _ in range(n)]   # independente
        d = diagnose_feature("f", feature, fwd, timestamps=_months_ts(n))
        # ruido NUNCA deve ser classificado como relacao real
        assert d["verdict"] != "real_relation"
        assert abs(d["ic_spearman"]) < 0.05

    def test_insufficient_sample(self):
        feature = [float(i) for i in range(50)]
        fwd = [0.001 * i for i in range(50)]
        d = diagnose_feature("f", feature, fwd, timestamps=_months_ts(50))
        assert d["verdict"] == "insufficient_sample"


def _candles_1h(n=900):
    out = []
    px = 1000.0
    for i in range(n):
        px = max(100.0, px + math.sin(i / 40.0) * 3.0 + 0.1)
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1, high=px + 2, low=px - 2, close=px,
                          volume=100.0 + i % 7))
    return out


class TestFeatureLibrary:

    def test_builds_causal_features(self):
        from crypto_trading_bot.research.feature_library import (
            build_feature_library)
        from crypto_trading_bot.research.perp_signals import (
            load_funding, load_open_interest)
        c = _candles_1h()
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0001} for k in range(120)])
        oi = load_open_interest([
            {"timestamp": (_D0 + timedelta(hours=i)).isoformat(),
             "open_interest": 1000.0 + i} for i in range(900)])
        feats, regime, closes = build_feature_library(
            c, funding_points=fund, oi_points=oi, base_minutes=60)
        # features-chave presentes e alinhadas
        for k in ("ema50_slope_1h", "donchian_pos_20", "atr_pct",
                  "funding_rate", "funding_pctile", "oi_change",
                  "price_oi_divergence", "trend_4h_slope", "hour_of_day"):
            assert k in feats and len(feats[k]) == len(c)
        assert len(closes) == len(c)
        assert set(regime.values()) <= {"lowvol", "midvol", "highvol"}


class TestOrchestrator:

    def test_lab_report_structure(self):
        from crypto_trading_bot.research.edge_research_phase49 import (
            run_signal_lab)
        rep = run_signal_lab(_candles_1h(), horizons={"4h": 4, "24h": 24}
                             ).to_dict()
        assert rep["demo_blocked"] and rep["live_blocked"]
        assert rep["strategy_promoted"] is False
        assert "diagnosis" in rep and "proposal" in rep
        assert isinstance(rep["proposal"]["has_signal"], bool)
        # cada feature tem verdict por horizonte
        f0 = rep["features"][0]
        assert "verdict_by_horizon" in f0 and "by_horizon" in f0
