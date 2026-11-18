"""
FASE 47 (correcao shadow) — ai_candidate_builder: RiskEngine ANTES da IA (P1)
+ contexto causal COMPLETO (P3). 100% OFFLINE. Setup com stop<0,5% ou
bloqueado pelo RiskEngine NAO vira candidato (nao consome IA). Contexto traz
funding/OI/percentis/ATR/vol/entry/stop/alvo/RR/risco-Hyro/custos/Polymarket.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.ai_candidate_builder import (
    build_candidate_contexts,
)
from crypto_trading_bot.research.effective_config import build_effective_config
from crypto_trading_bot.research.perp_signals import (
    load_funding,
    load_open_interest,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _ramp(n=140, base=100.0, flat=60, slope=0.8):
    out = []
    for i in range(n):
        px = base if i < flat else base + slope * (i - flat)
        ts = _D0 + timedelta(minutes=15 * i)
        out.append(Candle(symbol="BTCUSDT", timeframe="15m", timestamp=ts,
                          open=px - 0.3, high=px + 0.8, low=px - 0.8,
                          close=px, volume=10.0 + i % 5))
    return out


def _oi(n=140):
    return load_open_interest([
        {"timestamp": (_D0 + timedelta(minutes=15 * i)).isoformat(),
         "open_interest": 1000.0 + i * 5} for i in range(n)])


def _funding():
    return load_funding([
        {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
         "funding_rate": 0.0002} for k in range(12)])


def _build():
    eff = build_effective_config(store=None)
    return build_candidate_contexts(
        _ramp(), funding_points=_funding(), oi_points=_oi(),
        effective_config=eff, symbol="BTCUSDT")


class TestRiskEngineBeforeAI:

    def test_counts_partition(self):
        contexts, counts = _build()
        # total = aprovados + rejeitados(floor) + rejeitados(riskengine)
        assert counts["total_setups"] == (
            counts["approved"] + counts["rejected_by_floor"]
            + counts["rejected_by_riskengine"])
        assert counts["approved"] == len(contexts)

    def test_all_candidates_pass_floor(self):
        contexts, _ = _build()
        # nenhum candidato com stop < piso 0,5% (RiskEngine antes da IA)
        assert all(c["stop_dist_pct"] >= 0.005 for c in contexts)


class TestFullCausalContext:

    def test_context_has_all_fields(self):
        contexts, _ = _build()
        assert contexts, "esperado ao menos 1 candidato"
        c = contexts[0]
        for k in ("funding_rate", "funding_pctile", "open_interest",
                  "oi_change", "atr", "atr_pct", "volume", "entry", "stop",
                  "target", "risk_reward", "stop_dist_pct",
                  "target_risk_usd", "hyro_per_trade_ceiling_usd",
                  "hyro_daily_dd_limit_usd", "costs_bps",
                  "polymarket_stance"):
            assert k in c, f"campo ausente: {k}"
        # risco Hyro: teto 3% = 150; daily 4% = 200; target 0,5% = 25
        assert c["hyro_per_trade_ceiling_usd"] == 150.0
        assert c["hyro_daily_dd_limit_usd"] == 200.0
        assert c["target_risk_usd"] == 25.0
        assert c["costs_bps"]["fees_bps"] == 6.0

    def test_no_fabricated_fields(self):
        # nao deve haver liquidation_price/orderbook (nao fornecidos)
        contexts, _ = _build()
        c = contexts[0]
        assert "liquidation_price" not in c
        assert "orderbook" not in c
        assert "liquid" in c["data_note"].lower()
