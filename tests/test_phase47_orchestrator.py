"""
FASE 47 — orquestrador edge_research_phase47 (ablacao A-E). 100% OFFLINE,
sintetico. Verifica plumbing: config efetiva soberana (0,5%), ablacoes A/B
executadas, C pending sem cobertura Polymarket, D/E PENDENTE (IA sem backtest
historico legitimo), funding nas metricas, verdict final E prospectivo.
Sem rede/ordem/secret; OOS so via segmentos curtos de teste.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.edge_research_phase47 import (
    run_edge_research47,
)
from crypto_trading_bot.research.perp_signals import load_funding

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _candles(n=900):
    out = []
    px = 100.0
    for i in range(n):
        px = px + math.sin(i / 9.0) * 0.8 + (0.05 if i % 7 else -0.04)
        px = max(50.0, px)
        ts = _D0 + timedelta(minutes=15 * i)
        out.append(Candle(symbol="BTCUSDT", timeframe="15m", timestamp=ts,
                          open=px - 0.3, high=px + 0.8, low=px - 0.8,
                          close=px, volume=100.0 + i % 5))
    return out


def _funding(n_days=12):
    rows = []
    for k in range(n_days * 3):              # 8h
        rows.append({"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
                     "funding_rate": 0.0001 * (1 if k % 2 else -1)})
    return load_funding(rows)


def _oi(n=900):
    from crypto_trading_bot.research.perp_signals import load_open_interest
    rows = [{"timestamp": (_D0 + timedelta(minutes=15 * i)).isoformat(),
             "open_interest": 1000.0 + i} for i in range(n)]
    return load_open_interest(rows)


class TestOrchestrator:

    def _run(self):
        return run_edge_research47(
            _candles(), funding_points=_funding(), oi_points=_oi(),
            dev=("2025-01-01", "2025-01-06"),
            val=("2025-01-06", "2025-01-08"),
            oos=("2025-01-08", "2025-01-10"),
            wf_folds=2, run_oos=True, polymarket_coverage_ok=False)

    def test_report_structure(self):
        rep = self._run().to_dict()
        fams = {f["family"] for f in rep["families"]}
        assert "F1_funding_fade" in fams and "F2_oi_momentum" in fams
        assert rep["demo_blocked"] and rep["live_blocked"]
        assert rep["strategy_promoted"] is False

    def test_effective_config_sovereign_half_pct(self):
        rep = self._run().to_dict()
        rc = rep["segments"]["effective_config"]["risk_config"]
        assert rc["max_risk_per_trade_pct"] == 0.005
        ext = rep["segments"]["effective_config"][
            "external_ceilings_hyrotrader"]
        assert ext["max_risk_per_trade_pct"] == 0.03

    def test_ablations_a_b_executed_c_d_e_pending(self):
        rep = self._run().to_dict()
        f0 = rep["families"][0]["configs"]
        # A e B executadas (tem 'dev'); C pending (sem cobertura); D/E PENDENTE
        assert "dev" in f0["A"] and "dev" in f0["B"]
        assert f0["C"].get("verdict") == "PENDENTE"
        assert f0["D"].get("verdict") == "PENDENTE"
        assert f0["E"].get("verdict") == "PENDENTE"
        assert "prospect" in f0["D"]["reason"].lower() or \
            "ia" in f0["D"]["reason"].lower()

    def test_final_bot_verdict_pending(self):
        rep = self._run().to_dict()
        assert rep["final_bot_verdict_E"] == "PENDENTE_E_PROSPECTIVO"

    def test_funding_in_metrics(self):
        rep = self._run().to_dict()
        b_dev = rep["families"][0]["configs"]["B"]["dev"]
        assert "funding" in b_dev
        assert "funding_total_usd" in b_dev["funding"]

    def test_standard_report_present_even_on_dev(self):
        # relatorio padronizado (3 secoes + 4 eixos + tabela mensal) em
        # TODO config, inclusive quando o DEV morre por edge negativo.
        rep = self._run().to_dict()
        b_dev = rep["families"][0]["configs"]["B"]["dev"]
        sr = b_dev["standard_report"]
        for sec in ("strategy_metrics", "temporal_breakdown",
                    "hyro_simulation", "verdict"):
            assert sec in sr
        assert "monthly_table" in sr["temporal_breakdown"]
        assert set(sr["verdict"]) == {"edge_estatistico", "robustez_temporal",
                                      "hyro_challenge", "standard_trader",
                                      "bot_completo_E"}
