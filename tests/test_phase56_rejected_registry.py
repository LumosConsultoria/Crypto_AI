"""
FASE 56 — registry/tombstone de hipoteses rejeitadas. 100% OFFLINE. Verifica
catalogo, guard anti-repeticao (nome rejeitado bloqueia; familia rejeitada exige
diferenca estrutural) e invariantes (OOS intocado/nada promovido). Sem rede.
"""

from __future__ import annotations

from crypto_trading_bot.research.rejected_hypotheses_registry import (
    NEAR_MISS, REJECTED_HYPOTHESES, check_before_test, find, is_tombstoned,
    registry_summary)


def test_catalog_covers_known_families():
    fams = {h.family for h in REJECTED_HYPOTHESES}
    for expected in ("breakout_trend", "mean_reversion", "funding_directional",
                     "oi_momentum", "calendar", "volume",
                     "compression_confirmed"):
        assert expected in fams
    assert len(REJECTED_HYPOTHESES) >= 15


def test_breakout_oi_funding_is_near_miss():
    hit = find("breakout_oi_funding_confirmed")
    assert hit and hit[0].status == NEAR_MISS
    assert hit[0].key_metrics["profit_factor"] == 1.19
    assert hit[0].key_metrics["sign_consistency"] == 0.556


def test_rejected_name_is_blocked():
    r = check_before_test("funding_swing_mr")
    assert r["allowed"] is False
    assert "BLOQUEADA" in r["reason"] or "REJEITADA" in r["reason"]


def test_rejected_family_requires_structural_difference():
    # mesma familia (breakout_trend) sem justificativa => bloqueia
    r = check_before_test("novo_breakout_x", family="breakout_trend")
    assert r["allowed"] is False
    assert "ESTRUTURAL" in r["reason"]
    # com justificativa estrutural suficiente => permite
    r2 = check_before_test(
        "novo_breakout_x", family="breakout_trend",
        structural_difference=("usa fluxo cross-sectional entre perps em vez de "
                               "preco isolado de BTC"))
    assert r2["allowed"] is True


def test_new_family_allowed():
    r = check_before_test("alguma_coisa_nova", family="cross_sectional_relative")
    assert r["allowed"] is True


def test_is_tombstoned_by_name_and_family():
    assert is_tombstoned("seasonality_session_bias")
    assert is_tombstoned("funding_directional")        # familia
    assert not is_tombstoned("inexistente_xyz")


def test_summary_invariants():
    s = registry_summary()
    assert s["oos_consulted"] is False
    assert s["any_promoted"] is False
    assert s["demo_blocked"] and s["live_blocked"]
    assert s["total"] == len(REJECTED_HYPOTHESES)
