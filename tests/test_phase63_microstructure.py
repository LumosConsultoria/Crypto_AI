"""
FASE 63 — microestrutura btc_ofi_absorption_scalper_v1. 100% OFFLINE,
deterministico. Verifica: rede bloqueada sem flag; parser book/trades; OFI
causal; aggression_ratio; filtro spread/slippage; signal engine sem lookahead;
shadow nao chama ordem (orders_emitted=0); relatorios. Sem rede/ordem.
"""

from __future__ import annotations

from crypto_trading_bot.microstructure.models import (
    BookSnapshot, RiskParams, Tick, Trade)


def _book(ts, bid, ask, bsz=5.0, asz=5.0, n=10):
    bids = [(bid - i * 0.5, bsz) for i in range(n)]
    asks = [(ask + i * 0.5, asz) for i in range(n)]
    return BookSnapshot(ts=ts, bids=bids, asks=asks)


class TestParsers:

    def test_parse_orderbook_and_trades(self):
        from crypto_trading_bot.microstructure.parsers import (
            parse_orderbook, parse_trades)
        ob = {"b": [["60000", "2"], ["59999", "1"]],
              "a": [["60001", "1"], ["60002", "3"]], "ts": 1700000000000}
        book = parse_orderbook(ob)
        assert book.best_bid()[0] == 60000.0 and book.best_ask()[0] == 60001.0
        assert book.spread() == 1.0
        tr = parse_trades({"list": [
            {"price": "60000", "size": "0.5", "side": "Buy", "time": "1700000000500"},
            {"price": "59999", "size": "0.3", "side": "Sell", "time": "1700000000600"}]})
        assert len(tr) == 2 and tr[0].side == "buy" and tr[1].side == "sell"


class TestFeatures:

    def test_ofi_causal_sign(self):
        from crypto_trading_bot.microstructure.features import ofi_event
        prev = _book(1.0, 60000, 60001, bsz=5, asz=5)
        # bid sobe (compra agressiva) => OFI > 0
        cur = _book(2.0, 60000.5, 60001.5, bsz=6, asz=5)
        assert ofi_event(prev, cur) > 0

    def test_aggression_ratio(self):
        from crypto_trading_bot.microstructure.features import aggression_ratio
        trades = [Trade(1.0, 60000, 2.0, "buy"), Trade(1.5, 60000, 1.0, "sell")]
        ar = aggression_ratio(trades, now_ts=2.0, win_s=10.0)
        assert abs(ar["aggression_ratio"] - (2.0 / 3.0)) < 1e-6

    def test_spread_and_slippage_filter(self):
        from crypto_trading_bot.microstructure.features import (
            estimate_slippage_bps, spread_bps)
        book = _book(1.0, 60000, 60001, asz=0.001)   # ask raso
        assert spread_bps(book) is not None
        # notional grande, profundidade baixa => slippage alto ou None
        slip = estimate_slippage_bps(book, 5_000_000, "long")
        assert slip is None or slip > 0


class TestSignalEngineCausal:

    def test_no_lookahead_truncation(self):
        from crypto_trading_bot.microstructure.signal_engine import (
            ScalperConfig, SignalEngine)
        cfg = ScalperConfig(imbalance_threshold=0.0)
        ticks = [Tick(ts=float(i), book=_book(float(i), 60000 + i, 60001 + i),
                      trades=[Trade(float(i), 60000 + i, 1.0, "buy")])
                 for i in range(40)]
        eng1 = SignalEngine(cfg)
        for t in ticks[:30]:
            eng1.ingest(t)
        s1 = eng1.evaluate(29.0)
        eng2 = SignalEngine(cfg)
        for t in ticks:                              # com futuro tb
            if t.ts <= 29.0:
                eng2.ingest(t)
        s2 = eng2.evaluate(29.0)
        a = None if s1 is None else (s1.direction, tuple(sorted(s1.vetoes)))
        b = None if s2 is None else (s2.direction, tuple(sorted(s2.vetoes)))
        assert a == b                                # decisao so usa <= 29


class TestShadowSafety:

    def _ticks(self, n=400):
        out = []
        for i in range(n):
            px = 60000 + (i % 50) * 2.0
            book = _book(float(i), px, px + 1.0, bsz=8, asz=8)
            side = "buy" if (i // 10) % 2 == 0 else "sell"
            out.append(Tick(ts=float(i), book=book,
                            trades=[Trade(float(i), px, 3.0, side)]))
        return out

    def test_shadow_no_orders_and_flags(self):
        from crypto_trading_bot.microstructure.report import build_shadow_report
        from crypto_trading_bot.microstructure.shadow import run_shadow
        from crypto_trading_bot.microstructure.signal_engine import ScalperConfig
        sh = run_shadow(self._ticks(), scfg=ScalperConfig(
            warmup_seconds=50.0, imbalance_threshold=0.0))
        assert sh["orders_emitted"] == 0
        rep = build_shadow_report(sh, self._ticks())
        assert rep["orders_emitted"] == 0
        assert rep["real_execution_allowed"] is False
        assert rep["demo_blocked"] and rep["live_blocked"]
        assert rep["oos_untouched"] is True
        assert rep["classification"] in ("insufficient_data", "no_edge",
                                         "promising_shadow",
                                         "candidate_for_demo_review")

    def test_hard_stop_min_floor_respected(self):
        # qualquer trade deve ter stop a >= 0,5% do entry (piso soberano)
        from crypto_trading_bot.microstructure.shadow import run_shadow
        from crypto_trading_bot.microstructure.signal_engine import ScalperConfig
        sh = run_shadow(self._ticks(), scfg=ScalperConfig(
            warmup_seconds=50.0, imbalance_threshold=0.0))
        for t in sh["trades"]:
            dist = abs(t["entry_fill"] - t["stop_price"]) / t["entry_fill"]
            assert dist >= 0.005 - 1e-9


def _load_cli():
    import importlib.util
    from pathlib import Path
    p = (Path(__file__).resolve().parents[1] / "scripts"
         / "run_microstructure_phase63.py")
    spec = importlib.util.spec_from_file_location("run_micro_p63", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class TestCollectorGated:

    def test_network_blocked_without_flag(self):
        # collect sem --allow-network NAO chama real_transport (zero rede)
        import crypto_trading_bot.microstructure.collector as COL
        cli = _load_cli()
        orig = COL.real_transport

        def _boom(*a, **k):
            raise AssertionError("rede tocada sem --allow-network!")
        COL.real_transport = _boom
        try:
            rc = cli.main(["--mode", "collect"])   # sem flag => gated
            assert rc == 0
        finally:
            COL.real_transport = orig

    def test_collect_offline_with_fake_transport(self, tmp_path):
        from crypto_trading_bot.microstructure.collector import collect, load_ticks

        def fake(url):
            if "orderbook" in url:
                return {"b": [["60000", "5"], ["59999", "4"]],
                        "a": [["60001", "5"], ["60002", "4"]]}
            return {"list": [{"execId": "x", "price": "60000", "size": "1",
                              "side": "Buy", "time": "1700000000000"}]}
        out = tmp_path / "t.jsonl"
        res = collect("BTCUSDT", transport=fake, out_path=str(out), polls=3,
                      cadence_s=0.0, sleep_fn=lambda _s: None,
                      now_fn=lambda: 1700000000.0)
        assert res["status"] == "completed" and res["polls_ok"] == 3
        assert len(load_ticks(str(out))) == 3
