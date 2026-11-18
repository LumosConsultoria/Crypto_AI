"""
FASE 47 (7.3) — context_risk: multiplicadores IA/Polymarket + falha + impacto.
100% OFFLINE. So reduz (<=1,0); IA indisponivel NUNCA = favoravel silencioso;
not_applicable != falha. Metricas de trades mantidos/reduzidos/vetados +
PnL evitado/perdido. Sem rede/ordem/secret.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AISuggestedAction,
)
from crypto_trading_bot.research.context_risk import (
    ai_multiplier,
    compose_risk,
    impact_metrics,
    polymarket_multiplier,
)


def _advice(status, action=AISuggestedAction.PROCEED, conf=0.7):
    return AIAdvice(status=status, confidence=conf, reason="t",
                    suggested_action=action)


class TestAIMultiplier:

    def test_favorable_proceed_neutral(self):
        st, m = ai_multiplier(_advice(AIAdviceStatus.NEUTRAL))
        assert st == "favorable" and m == 1.00

    def test_veto_is_contrary_zero(self):
        st, m = ai_multiplier(_advice(AIAdviceStatus.VETO,
                                      AISuggestedAction.MANUAL_REVIEW))
        assert st == "contrary" and m == 0.00

    def test_caution_is_neutral_half(self):
        st, m = ai_multiplier(_advice(AIAdviceStatus.CAUTION,
                                      AISuggestedAction.WAIT))
        assert st == "neutral" and m == 0.50

    def test_manual_review_is_half(self):
        st, m = ai_multiplier(_advice(AIAdviceStatus.MANUAL_REVIEW,
                                      AISuggestedAction.MANUAL_REVIEW))
        assert m == 0.50

    def test_unavailable_never_favorable(self):
        st, m = ai_multiplier(None, available=False)
        assert st == "unavailable" and m == 0.50 and m != 1.00

    def test_error_veto_policy(self):
        st, m = ai_multiplier(None, error=True, failure_policy="veto")
        assert st == "error" and m == 0.00


class TestPolymarketMultiplier:

    def test_favorable(self):
        assert polymarket_multiplier("favorable") == ("favorable", 1.00)

    def test_elevated_risk(self):
        assert polymarket_multiplier("elevated_risk") == ("elevated_risk",
                                                          0.75)

    def test_contrary(self):
        assert polymarket_multiplier("contrary") == ("contrary", 0.00)

    def test_not_applicable_is_neutral_effect_not_failure(self):
        st, m = polymarket_multiplier("not_applicable")
        assert st == "not_applicable" and m == 1.00

    def test_unavailable_reduces(self):
        st, m = polymarket_multiplier("unavailable")
        assert st == "unavailable" and m == 0.50


class TestComposeRisk:

    def test_composition_formula(self):
        # IA favoravel (1.0) x Poly elevado (0.75) => 25 * 0.75 = 18.75
        d = compose_risk(25.0, advice=_advice(AIAdviceStatus.NEUTRAL),
                         poly_stance="elevated_risk")
        assert d.risk_final_usd == pytest.approx(18.75)
        assert d.decision == "reduced"

    def test_veto_zeroes_risk(self):
        d = compose_risk(25.0, advice=_advice(AIAdviceStatus.VETO),
                         poly_stance="favorable")
        assert d.risk_final_usd == 0.0 and d.decision == "vetoed"

    def test_kept_when_all_favorable(self):
        d = compose_risk(25.0, advice=_advice(AIAdviceStatus.NEUTRAL),
                         poly_stance="favorable")
        assert d.risk_final_usd == pytest.approx(25.0)
        assert d.decision == "kept"

    def test_never_exceeds_base(self):
        for poly in ("favorable", "elevated_risk", "contrary",
                     "not_applicable", "unavailable"):
            d = compose_risk(25.0, advice=_advice(AIAdviceStatus.NEUTRAL),
                             poly_stance=poly)
            assert d.risk_final_usd <= 25.0 + 1e-9

    def test_ablation_disabled_context_is_neutral(self):
        # modo A/B: sem IA e sem Polymarket => mult 1,0 (kept)
        d = compose_risk(25.0, use_ai=False, use_polymarket=False)
        assert d.risk_final_usd == pytest.approx(25.0)
        assert d.ai_state == "disabled" and d.poly_state == "disabled"

    def test_mode_d_only_ai(self):
        d = compose_risk(25.0, advice=_advice(AIAdviceStatus.CAUTION,
                                              AISuggestedAction.WAIT),
                         use_ai=True, use_polymarket=False)
        assert d.risk_final_usd == pytest.approx(12.5)
        assert d.poly_state == "disabled"


class TestImpactMetrics:

    def test_kept_reduced_vetoed_counts(self):
        recs = [
            {"decision": "kept", "baseline_pnl_usd": 10.0, "scale": 1.0},
            {"decision": "vetoed", "baseline_pnl_usd": -20.0, "scale": 0.0},
            {"decision": "reduced", "baseline_pnl_usd": 8.0, "scale": 0.5},
        ]
        m = impact_metrics(recs)
        assert m["trades_kept"] == 1
        assert m["trades_vetoed"] == 1
        assert m["trades_reduced"] == 1
        # vetou uma perda de -20 => evitou 20
        assert m["pnl_avoided_usd"] == pytest.approx(20.0)
        # reduziu metade de um ganho de 8 => perdeu 4
        assert m["pnl_lost_usd"] == pytest.approx(4.0)
        assert m["net_context_benefit_usd"] == pytest.approx(16.0)
