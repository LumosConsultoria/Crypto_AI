"""
FASE 59 — H1 failed_breakout_fade_5m. 100% OFFLINE, deterministico. Verifica
deteccao do fakeout (direcao/stop no cap), causalidade (canal anterior), gate
dos 8 criterios e orquestrador (DEV; VAL so se DEV passar; OOS intocado). Sem
rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _c(ts, o, h, lo, cl, v=100.0):
    return Candle(symbol="BTCUSDT", timeframe="5m", timestamp=ts, open=o,
                  high=h, low=lo, close=cl, volume=v)


def _series(n=400, base=1000.0):
    out = []
    for i in range(n):
        px = base + math.sin(i / 30.0) * 8.0
        out.append(_c(_D0 + timedelta(minutes=5 * i), px - 1, px + 2, px - 2, px))
    return out


class TestDetector:

    def test_failed_up_breakout_emits_short(self):
        from crypto_trading_bot.research.failed_breakout_family import (
            detect_failed_breakout_fade)
        c = _series(60)
        # injeta um fakeout p/ CIMA na barra 50: pavio acima do canal, fecha dentro
        dh = max(x.high for x in c[30:50])
        c[50] = _c(c[50].timestamp, dh - 1, dh + 20, dh - 2, dh - 5)  # close<dh
        setups = detect_failed_breakout_fade(c, params={"donch_lookback": 20})
        s50 = [s for s in setups if s.idx == 50]
        assert s50 and s50[0].direction == "short"
        assert s50[0].stop > s50[0].entry_ref      # stop acima
        assert 0.005 <= s50[0].stop_dist_pct <= 0.05

    def test_causal_uses_prior_channel(self):
        # truncar a serie depois de i nao muda o setup em i (so usa canal anterior)
        from crypto_trading_bot.research.failed_breakout_family import (
            detect_failed_breakout_fade)
        c = _series(120)
        dh = max(x.high for x in c[40:60])
        c[60] = _c(c[60].timestamp, dh - 1, dh + 25, dh - 2, dh - 6)
        full = detect_failed_breakout_fade(c)
        trunc = detect_failed_breakout_fade(c[:62])
        a = {s.setup_id for s in full if s.idx <= 60}
        b = {s.setup_id for s in trunc if s.idx <= 60}
        assert a == b and any(s.idx == 60 for s in full)

    def test_regime_gate_blocks_short_in_strong_uptrend(self):
        from crypto_trading_bot.research.failed_breakout_family import (
            detect_failed_breakout_fade)
        c = _series(60)
        dh = max(x.high for x in c[30:50])
        c[50] = _c(c[50].timestamp, dh - 1, dh + 20, dh - 2, dh - 5)
        slope = [0.01] * len(c)     # tendencia de ALTA forte => bloqueia short
        setups = detect_failed_breakout_fade(c, regime_slope_1h=slope)
        assert not any(s.idx == 50 for s in setups)


def test_gate_eight_criteria():
    from crypto_trading_bot.research.edge_research_phase59 import _gate
    base = {"verdict": {"edge_estatistico": "aprovado"},
            "strategy_metrics": {"net_pnl_usd": 200, "profit_factor_net": 1.3,
                                 "expectancy_net_usd": 2.0, "num_trades": 150},
            "temporal_breakdown": {"sign_consistency": 0.7, "months_total": 6},
            "hyro_challenge_attempts": {"total_attempts": 4},
            "classification": "candidata_paper"}
    assert _gate(base)["passed"] is True
    # poucos trades => reprova
    bad = dict(base, strategy_metrics={**base["strategy_metrics"],
                                       "num_trades": 50})
    g = _gate(bad)
    assert g["passed"] is False and g["checks"]["trades_ge_100"] is False
    # poucas tentativas Hyro => reprova
    bad2 = dict(base, hyro_challenge_attempts={"total_attempts": 1})
    assert _gate(bad2)["passed"] is False


class TestOrchestrator59:

    def test_runs_dev_no_oos(self):
        from crypto_trading_bot.research.edge_research_phase59 import (
            run_edge_research59)
        c = _series(3000)
        # injeta varios fakeouts p/ gerar setups
        for i in range(60, len(c), 23):
            dh = max(x.high for x in c[i - 20:i])
            c[i] = _c(c[i].timestamp, dh - 1, dh + 18, dh - 2, dh - 5)
        d = run_edge_research59(
            c, dev=("2025-01-01", "2025-01-08"),
            val=("2025-01-08", "2025-01-11"), wf_folds=2).to_dict()
        assert d["decision"] in ("CANDIDATA_PENDENTE_APROVACAO_OOS", "REJEITAR")
        assert d["loop"]["oos_consulted"] is False
        assert d["strategy_promoted"] is False
        assert "gate" in d["hypothesis"]["dev"]
        assert "sensitivity_1pct_separate" in d["hypothesis"]
