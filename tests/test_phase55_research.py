"""
FASE 55 — hipoteses NORMAIS condicionadas + orquestrador via research loop.
100% OFFLINE, deterministico. Verifica agenda (racional/limites/dados
permitidos), deteccao (direcao/stop no cap) e o orquestrador (dual-profile com
hyro_challenge_attempts + monthly_close; OOS intocado). Sem rede/ordem.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from crypto_trading_bot.exchange.base_exchange import Candle

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
_ALLOWED = {"ohlcv", "volume", "funding", "open_interest", "costs",
            "calendar", "session"}


def _candles(n=2400, base=1000.0):
    out = []
    for i in range(n):
        # tendencia lenta + ondas => regimes variados
        px = base + i * 0.05 + math.sin(i / 45.0) * 22.0 + math.sin(i / 8.0) * 6.0
        out.append(Candle(symbol="BTCUSDT", timeframe="1h",
                          timestamp=_D0 + timedelta(hours=i),
                          open=px - 1.5, high=px + 5, low=px - 5, close=px,
                          volume=100.0 + (i % 17)))
    return out


class TestAgenda:

    def test_specs_valid_limits_and_allowed_data(self):
        from crypto_trading_bot.research.normal_hypotheses_phase55 import (
            proposed_hypotheses_phase55)
        from crypto_trading_bot.research.research_loop import (
            MAX_HYPOTHESES, MAX_VARIANTS)
        hyps = proposed_hypotheses_phase55()
        assert 1 <= len(hyps) <= MAX_HYPOTHESES
        fams = [h.family for h in hyps]
        assert len(set(fams)) == len(fams)
        for h in hyps:
            ok, errs = h.validate()
            assert ok, errs
            assert h.variants <= MAX_VARIANTS
            assert set(h.data_used) <= _ALLOWED
            assert h.economic_rationale and h.why_different
            assert not (set(h.markers) & {"not_for_promotion",
                                          "insufficient_history"})


class TestDetectors:

    def test_detectors_run_and_respect_cap(self):
        from crypto_trading_bot.research.normal_families_phase55 import (
            detect_breakout_oi_funding_confirmed,
            detect_range_reversion_regime_gated,
            detect_trend_pullback_regime_gated)
        c = _candles()
        oc = [0.01 if i % 2 == 0 else -0.01 for i in range(len(c))]
        fp = [0.5] * len(c)
        for setups in (detect_trend_pullback_regime_gated(c),
                       detect_range_reversion_regime_gated(c),
                       detect_breakout_oi_funding_confirmed(c, oc, fp)):
            assert isinstance(setups, list)
            for s in setups:
                assert s.direction in ("long", "short")
                assert 0.005 <= s.stop_dist_pct <= 0.05


class TestNoLookahead:

    def test_oi_funding_detector_is_causal(self):
        # decisao no candle i NAO pode depender de candles futuros: truncar a
        # serie em cut deve preservar os setups com idx << cut.
        from crypto_trading_bot.research.normal_families_phase55 import (
            detect_breakout_oi_funding_confirmed)
        # escada de alta com wick pequeno => rompimentos reais de Donchian
        c = [Candle(symbol="BTCUSDT", timeframe="1h",
                    timestamp=_D0 + timedelta(hours=i),
                    open=(1000.0 + i * 0.5 + math.sin(i / 7.0) * 3.0) - 0.5,
                    high=(1000.0 + i * 0.5 + math.sin(i / 7.0) * 3.0) + 0.5,
                    low=(1000.0 + i * 0.5 + math.sin(i / 7.0) * 3.0) - 0.5,
                    close=(1000.0 + i * 0.5 + math.sin(i / 7.0) * 3.0),
                    volume=100.0) for i in range(520)]
        oc = [0.02] * len(c)               # OI sempre expandindo
        fp = [0.5] * len(c)                # funding neutro (gates abertos)
        # squeeze raro => relaxo SO o gate de squeeze p/ ISOLAR a causalidade.
        pr = {"squeeze_pct": 0.99, "donch": 10}
        full = detect_breakout_oi_funding_confirmed(c, oc, fp, params=pr)
        assert full, "fixture deve gerar ao menos 1 setup"
        cut = 470
        trunc = detect_breakout_oi_funding_confirmed(
            c[:cut], oc[:cut], fp[:cut], params=pr)
        ids_full = {s.setup_id for s in full if s.idx < cut - 60}
        ids_trunc = {s.setup_id for s in trunc if s.idx < cut - 60}
        assert ids_full and ids_full == ids_trunc      # idem => sem lookahead


class TestSampleGuard:

    def test_harden_downgrades_small_sample_and_few_attempts(self):
        from crypto_trading_bot.research.edge_research_phase55 import _harden
        sr = {
            "strategy_metrics": {"num_trades": 8},
            "temporal_breakdown": {"months_total": 2, "sign_consistency": 1.0},
            "hyro_challenge_attempts": {"total_attempts": 1},
            "verdict": {"edge_estatistico": "aprovado",
                        "hyro_challenge": "passaria",
                        "standard_trader": "aprovado"},
            "classification": "candidata_paper"}
        h = _harden(sr)
        g = h["phase55_sample_guard"]
        assert g["sample_sufficient"] is False
        assert h["verdict"]["edge_estatistico"] == "rejeitado"   # poucos trades
        assert h["verdict"]["hyro_challenge"] == "fraco_instavel"  # poucas tent.
        assert h["classification"] == "edge_possivel_incompativel_com_challenge"

    def test_harden_keeps_sufficient_sample(self):
        from crypto_trading_bot.research.edge_research_phase55 import _harden
        sr = {
            "strategy_metrics": {"num_trades": 60},
            "temporal_breakdown": {"months_total": 6, "sign_consistency": 0.7},
            "hyro_challenge_attempts": {"total_attempts": 5},
            "verdict": {"edge_estatistico": "aprovado",
                        "hyro_challenge": "passaria",
                        "standard_trader": "aprovado"},
            "classification": "candidata_paper"}
        h = _harden(sr)
        assert h["phase55_sample_guard"]["sample_sufficient"] is True
        assert h["verdict"]["edge_estatistico"] == "aprovado"
        assert h["verdict"]["hyro_challenge"] == "passaria"
        assert h["classification"] == "candidata_paper"


class TestOrchestrator55:

    def test_loop_dual_profile_no_oos(self):
        from crypto_trading_bot.research.edge_research_phase55 import (
            run_edge_research55)
        from crypto_trading_bot.research.perp_signals import (
            load_funding, load_open_interest)
        c = _candles()
        fund = load_funding([
            {"timestamp": (_D0 + timedelta(hours=8 * k)).isoformat(),
             "funding_rate": 0.0005 * math.sin(k / 4.0)}
            for k in range(len(c) // 8 + 2)])
        oi = load_open_interest([
            {"timestamp": (_D0 + timedelta(hours=i)).isoformat(),
             "open_interest": 1000.0 + 40.0 * math.sin(i / 25.0) + i * 0.1}
            for i in range(len(c))])
        d = run_edge_research55(
            c, funding_points=fund, oi_points=oi,
            dev=("2025-01-01", "2025-03-01"),
            val=("2025-03-01", "2025-04-01"), wf_folds=2).to_dict()
        assert d["decision"] in ("CANDIDATA_PENDENTE_APROVACAO_OOS",
                                 "NENHUMA_CANDIDATA")
        assert d["loop"]["oos_consulted"] is False
        assert d["strategy_promoted"] is False
        for name, b in d["per_hypothesis"].items():
            assert "dev_classification" in b
            assert "dev_sample_guard" in b           # guard de amostra
            assert "dev_hyro_attempts" in b          # leitura principal Hyro
            assert "dev_monthly_close" in b          # leitura principal Trader
            # 1% como sensibilidade SEPARADA (fora do ranking)
            assert "sensitivity_1pct_separate" in b
            assert "trader_padrao_1pct_dev" not in b
