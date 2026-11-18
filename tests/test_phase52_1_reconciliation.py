"""
FASE 52.1 — reconciliacao sinal->estrategia (decomposicao). 100% OFFLINE,
deterministico. Perpetual-only; sem OOS; sem otimizacao. Verifica a mecanica
de simulacao de trades (sequencial nao-sobreposto, direcao MR, stop/alvo
path-aware, funding) + estrutura/decisao do relatorio. Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(n=2880, base=1000.0):
    out = []
    for i in range(n):
        px = base + math.sin(i / 50.0) * 30.0 + math.sin(i / 7.0) * 8.0
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1, high=px + 5, low=px - 5, close=px,
                          volume=100.0))
    return out


class TestSimulate:

    def test_direction_and_nonoverlap(self):
        from crypto_trading_bot.research.edge_research_phase52_1 import (
            simulate_trades)
        c = _candles(400)
        # percentil sintetico: alterna extremos p/ disparar short/long
        fpct = [0.9 if (i // 80) % 2 == 0 else 0.05 for i in range(len(c))]
        trades = simulate_trades(c, fpct, [], hi=0.85, lo=0.15,
                                 exit_kind="fixed", horizon_bars=72,
                                 apply_funding=False)
        assert trades, "deve gerar ao menos 1 trade"
        # high pctile => short, low => long
        for t in trades:
            assert t["direction"] in ("short", "long")
        # nao-sobreposto: entrada seguinte > saida anterior
        for a, b in zip(trades, trades[1:]):
            assert b["entry_idx"] > a["exit_idx"]

    def test_stop_caps_loss(self):
        from crypto_trading_bot.research.edge_research_phase52_1 import (
            simulate_trades)
        c = _candles(400)
        fpct = [0.9] * len(c)             # sempre short
        st = simulate_trades(c, fpct, [], hi=0.85, lo=0.15,
                             exit_kind="stop_target", horizon_bars=168,
                             stop_pct=0.05, rr=1.5, apply_funding=False)
        # nenhuma perda bruta pior que stop+folga (path-aware, intrabar)
        for t in st:
            assert t["gross"] >= -0.06     # stop 5% + folga de barra

    def test_neutral_pctile_no_trade(self):
        from crypto_trading_bot.research.edge_research_phase52_1 import (
            simulate_trades)
        c = _candles(300)
        assert simulate_trades(c, [0.5] * len(c), [], hi=0.85, lo=0.15,
                               exit_kind="fixed", horizon_bars=72) == []


class TestReconciliation:

    def _run(self):
        from crypto_trading_bot.research.edge_research_phase52_1 import (
            run_reconciliation)
        from crypto_trading_bot.research.perp_signals import load_funding
        c = _candles()
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0008 * math.sin(k / 5.0)}
            for k in range(len(c) // 8 + 2)])
        return run_reconciliation(
            c, funding_points=fund, dev=("2025-01-01", "2025-03-01"),
            val=("2025-03-01", "2025-04-30"))

    def test_report_structure(self):
        d = self._run().to_dict()
        assert d["schema"] == "funding_signal_strategy_reconciliation_v1"
        assert len(d["ladder"]) == 6
        for r in d["ladder"]:
            assert "dev" in r and "val" in r
            assert "mean_net_pct" in r["dev"] and "sign_consistency" in r["val"]
        assert d["window"]["perpetual_only"] and not d["window"]["oos_consulted"]
        assert d["demo_blocked"] and d["strategy_promoted"] is False

    def test_decision_and_answers(self):
        d = self._run().to_dict()
        assert d["decision"] in ("ENCERRAR_APENAS_F5_E_REGIME_FILTER",
                                 "ENCERRAR_FUNDING_COMPLETAMENTE")
        a = d["answers"]
        for k in ("q1_signal_execution_compatible", "q2_where_f5_lost_edge",
                  "q3_simple_strategy_without_val_tuning",
                  "q4_where_raw_edge_disappears", "next_minimal_test"):
            assert k in a
        assert "first_step_that_kills_val" in a["q2_where_f5_lost_edge"]
