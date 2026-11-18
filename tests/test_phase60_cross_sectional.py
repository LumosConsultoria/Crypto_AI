"""
FASE 60 — multi-asset cross-sectional. 100% OFFLINE, deterministico. Verifica
alinhamento do universo, backtest 1-posicao (sem basket), detectores (selecao
<=1/barra, stop no cap), orquestrador (dual-profile, gate, OOS intocado). Sem
rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _series(sym, n, base, drift=0.0, amp=20.0, phase=0.0):
    out = []
    for i in range(n):
        px = base * (1 + drift * i) + math.sin(i / 25.0 + phase) * amp
        out.append(Candle(symbol=sym, timeframe="5m",
                          timestamp=_D0 + timedelta(minutes=5 * i),
                          open=px - 1, high=px + 4, low=px - 4, close=px,
                          volume=100.0))
    return out


def _universe(n=400):
    return {
        "BTCUSDT": _series("BTCUSDT", n, 60000, 0.0002, 300, 0.0),
        "ETHUSDT": _series("ETHUSDT", n, 3000, 0.0001, 20, 1.0),
        "SOLUSDT": _series("SOLUSDT", n, 150, 0.0003, 4, 2.0),
        "BNBUSDT": _series("BNBUSDT", n, 600, 0.00005, 6, 3.0),
        "XRPUSDT": _series("XRPUSDT", n, 2.0, 0.0001, 0.04, 0.5),
    }


class TestUniverse:

    def test_alignment_and_returns(self):
        from crypto_trading_bot.research.cross_sectional import Universe
        u = Universe(_universe(300))
        assert u.n == 300 and len(u.symbols) == 5
        r = u.ret("BTCUSDT", 50, 12)
        assert r is not None

    def test_backtest_one_position_no_basket(self):
        from crypto_trading_bot.research.cross_sectional import (
            Universe, mk_xsetup, run_xs_backtest)
        u = Universe(_universe(200))
        # dois setups sobrepostos em ativos diferentes => o 2o e ignorado
        ts0 = u.timestamps[30]
        c0 = u.closes["ETHUSDT"][30]
        s1 = mk_xsetup(ts0, "ETHUSDT", 30, "long", c0, c0 * 0.98, 1.5)
        c1 = u.closes["SOLUSDT"][35]
        s2 = mk_xsetup(u.timestamps[35], "SOLUSDT", 35, "long", c1, c1 * 0.98,
                       1.5)
        rep = run_xs_backtest(u, [s1, s2], max_holding=24)
        # 1 posicao: s2 (idx35) cai dentro do hold de s1 (30..54) => ignorado
        assert len(rep.trades) == 1 and rep.trades[0].symbol == "ETHUSDT"


class TestDetectors:

    def test_detectors_emit_at_most_one_per_bar_and_cap(self):
        from crypto_trading_bot.research.cross_sectional import Universe
        from crypto_trading_bot.research.cross_sectional_families import (
            DETECTORS)
        u = Universe(_universe(500))
        for name, det in DETECTORS.items():
            setups = det(u)
            idxs = [s.idx for s in setups]
            assert len(idxs) == len(set(idxs)), f"{name}: >1 setup/barra"
            for s in setups:
                assert 0.005 <= s.stop_dist_pct <= 0.05


class TestOrchestrator60:

    def test_runs_dual_profile_no_oos(self):
        from crypto_trading_bot.research.edge_research_phase60 import (
            run_edge_research60)
        d = run_edge_research60(
            _universe(3000), dev=("2025-01-01", "2025-01-08"),
            val=("2025-01-08", "2025-01-11")).to_dict()
        assert d["decision"] in ("CANDIDATA_PENDENTE_APROVACAO_OOS",
                                 "NENHUMA_CANDIDATA")
        assert d["loop"]["oos_consulted"] is False
        assert d["strategy_promoted"] is False
        assert len(d["ranking"]) == 3
        for b in d["per_hypothesis"].values():
            assert "dev_gate" in b and "sensitivity_1pct_separate" in b
            assert "dev_hyro_attempts" in b and "dev_monthly_close" in b
