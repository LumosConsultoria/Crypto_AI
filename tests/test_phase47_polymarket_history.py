"""
FASE 47 — Polymarket history: descoberta causal + cobertura + alinhamento +
stance. 100% OFFLINE (fixtures; zero rede). Sem lookahead (mercado deve
existir em t e nao ter resolvido); sem cherry-pick por desfecho;
insufficient_history => shadow. Sem aposta/ordem/secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.prediction_markets.polymarket_history import (
    PolymarketHistory,
    is_btc_eligible,
    load_canonical,
    load_snapshots,
    save_canonical,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _snap(mid, q, ts_h, prob, created_h=-100, resolved_h=None):
    return {"market_id": mid, "question": q, "category": "crypto",
            "created_at": (_D0 + timedelta(hours=created_h)).isoformat(),
            "resolved_at": (_D0 + timedelta(hours=resolved_h)).isoformat()
            if resolved_h is not None else None,
            "timestamp": (_D0 + timedelta(hours=ts_h)).isoformat(),
            "prob_yes": prob}


class TestEligibility:

    def test_btc_term_match(self):
        assert is_btc_eligible("Will Bitcoin hit 100k?", "crypto")
        assert is_btc_eligible("BTC above 90k", "")
        assert not is_btc_eligible("Will ETH flip?", "crypto")

    def test_only_btc_markets_kept(self):
        snaps = load_snapshots([
            _snap("m1", "Bitcoin up?", 1, 0.7),
            _snap("m2", "Ethereum up?", 1, 0.7)])
        h = PolymarketHistory(snaps)
        # so m1 (BTC) entra
        assert h.stance_at(_D0 + timedelta(hours=2)) in (
            "favorable", "elevated_risk")


class TestCausalDiscovery:

    def test_market_created_after_t_excluded(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=5, prob=0.7,
                                      created_h=4)])
        h = PolymarketHistory(snaps)
        # em t=+3h o mercado ainda nao existia (created=+4h)
        assert h.eligible_at(_D0 + timedelta(hours=3)) == []
        # em t=+6h ja existe
        assert len(h.eligible_at(_D0 + timedelta(hours=6))) == 1

    def test_resolved_market_excluded_after_resolution(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=2, prob=0.7,
                                      created_h=-10, resolved_h=5)])
        h = PolymarketHistory(snaps)
        assert len(h.eligible_at(_D0 + timedelta(hours=3))) == 1   # antes
        assert h.eligible_at(_D0 + timedelta(hours=6)) == []       # depois

    def test_no_lookahead_future_snapshot_excluded(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=10, prob=0.7)])
        h = PolymarketHistory(snaps)
        assert h.eligible_at(_D0 + timedelta(hours=5)) == []   # ts futuro


class TestStance:

    def test_not_applicable_when_no_market(self):
        h = PolymarketHistory([])
        assert h.stance_at(_D0) == "not_applicable"

    def test_uncertain_prob_is_elevated_risk(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=1, prob=0.5)])
        h = PolymarketHistory(snaps)
        assert h.stance_at(_D0 + timedelta(hours=2)) == "elevated_risk"

    def test_confident_prob_is_favorable(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=1, prob=0.9)])
        h = PolymarketHistory(snaps)
        assert h.stance_at(_D0 + timedelta(hours=2)) == "favorable"

    def test_align_to_candles(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=0, prob=0.5)])
        h = PolymarketHistory(snaps)
        candles = [Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=1, high=1, low=1, close=1, volume=1)
                   for i in range(3)]
        stances = h.align_to_candles(candles, interval_minutes=60)
        assert len(stances) == 3
        assert "elevated_risk" in stances


class TestCoverage:

    def test_insufficient_history(self):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=1, prob=0.6)])
        h = PolymarketHistory(snaps)
        cov = h.coverage()
        assert cov["verdict"] == "insufficient_history"

    def test_sufficient_history(self):
        rows = []
        for m in range(4):
            for k in range(60):
                rows.append(_snap(f"m{m}", "BTC up?", ts_h=k, prob=0.7))
        h = PolymarketHistory(load_snapshots(rows))
        cov = h.coverage(min_markets=3, min_snapshots=200)
        assert cov["verdict"] == "sufficient"
        assert cov["btc_markets"] == 4


class TestStorage:

    def test_save_load_roundtrip(self, tmp_path):
        snaps = load_snapshots([_snap("m1", "BTC up?", ts_h=1, prob=0.7)])
        p = tmp_path / "pm.json"
        save_canonical(str(p), snaps, meta={"source": "test"})
        loaded = load_canonical(str(p))
        assert len(loaded) == 1 and loaded[0].market_id == "m1"

    def test_traversal_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            save_canonical("../evil.json", [])
