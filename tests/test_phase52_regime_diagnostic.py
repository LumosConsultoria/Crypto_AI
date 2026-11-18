"""
FASE 52 — diagnostico de robustez por REGIME do funding-MR. Perpetual-ONLY
(sem spot/basis). 100% OFFLINE, deterministico. NAO monta estrategia; OOS
intocado. Verifica masking por segmento+regime, estrutura do relatorio e o
gate travado (SOBREVIVE/NAO_SOBREVIVE). Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles_1h(n=2880, base=1000.0):
    out = []
    for i in range(n):
        px = base + math.sin(i / 50.0) * 30.0 + math.sin(i / 7.0) * 8.0
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1, high=px + 4, low=px - 4, close=px,
                          volume=100.0 + (i % 13)))
    return out


def _funding(n_candles=2880):
    from crypto_trading_bot.research.perp_signals import load_funding
    rows = []
    for k in range(n_candles // 8 + 2):
        rate = 0.0009 * math.sin(k / 5.0)        # oscila p/ gerar extremos
        rows.append({"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
                     "funding_rate": rate})
    return load_funding(rows)


class TestMasking:

    def test_masked_restricts_segment_and_regime(self):
        from crypto_trading_bot.research.edge_research_phase52 import _masked
        ts = [_D0 + timedelta(hours=i) for i in range(10)]
        feat = [float(i) for i in range(10)]
        regime = {i: ("lowvol" if i < 5 else "highvol") for i in range(10)}
        # segmento cobre so as 5 primeiras horas; regime lowvol
        seg = ("2025-01-01", "2025-01-01")  # lo==hi => nada (hi exclusivo)
        out = _masked(feat, ts, regime, seg, None)
        assert all(v is None for v in out)   # janela vazia
        # janela ampla + filtro lowvol => so indices 0..4 sobrevivem
        seg2 = ("2025-01-01", "2025-02-01")
        out2 = _masked(feat, ts, regime, seg2, "lowvol")
        assert [i for i, v in enumerate(out2) if v is not None] == [0, 1, 2, 3, 4]


class TestRegimeDiagnostic:

    def _run(self):
        from crypto_trading_bot.research.edge_research_phase52 import (
            run_regime_diagnostic)
        c = _candles_1h()
        return run_regime_diagnostic(
            c, funding_points=_funding(len(c)),
            dev=("2025-01-01", "2025-03-01"),
            val=("2025-03-01", "2025-04-30"))

    def test_report_structure_perp_only(self):
        d = self._run().to_dict()
        assert d["schema"] == "funding_mr_regime_diagnostic_v1"
        assert d["window"]["perpetual_only"] is True
        assert d["window"]["spot_used"] is False
        assert d["real_execution_allowed"] is False
        assert d["demo_blocked"] and d["live_blocked"]
        assert d["strategy_promoted"] is False

    def test_signals_have_overall_and_by_regime(self):
        d = self._run().to_dict()
        sigs = {s["signal"] for s in d["signals"]}
        assert "funding_rate" in sigs
        for s in d["signals"]:
            for h, blk in s["by_horizon"].items():
                assert "overall_dev" in blk and "overall_val" in blk
                assert set(blk["by_regime"]) == {"lowvol", "midvol", "highvol"}
                for reg in blk["by_regime"].values():
                    assert "dev" in reg and "val" in reg
                    assert "robust_dev_and_val" in reg

    def test_gate_verdict_and_decision_consistent(self):
        d = self._run().to_dict()
        g = d["gate"]
        assert g["verdict"] in ("SOBREVIVE", "NAO_SOBREVIVE")
        if g["verdict"] == "SOBREVIVE":
            assert g["decision"] == "PROPOR_HIPOTESE_FASE53"
            assert g["survivors"]
        else:
            assert g["decision"] == "ENCERRAR_LINHA_BTC_DIRECIONAL_FUNDING"
            assert "conclusion" in g
