"""
FASE 53 — research loop controlado. 100% OFFLINE, deterministico. Verifica
registro obrigatorio, limites, VAL-so-apos-DEV, candidata-pendente-aprovacao
(OOS NUNCA consultado), marcadores nao-promoviveis e dados insuficientes.
Sem rede/ordem.
"""

from __future__ import annotations

from crypto_trading_bot.research.research_loop import (
    HypothesisSpec, run_research_loop)


def _spec(name, **kw):
    base = dict(name=name, economic_rationale="r", why_different="d",
                data_used=["orderbook"], fixed_params={"a": 1},
                accept_criteria="c", expected_reason_to_work="w")
    base.update(kw)
    return HypothesisSpec(**base)


def test_spec_validation():
    ok, _ = _spec("h").validate()
    assert ok
    bad, errs = _spec("h", economic_rationale="").validate()
    assert not bad and errs
    over, errs2 = _spec("h", variants=3).validate()
    assert not over


def test_candidate_pending_approval_stops_and_no_oos():
    passing = {"classification": "candidata_paper",
               "verdict": {"edge_estatistico": "aprovado",
                           "robustez_temporal": "aprovado"}}

    def evaluator(h, seg):
        return passing

    rep = run_research_loop([_spec("good"), _spec("never_reached")],
                            evaluator).to_dict()
    assert rep["candidate"] == "good"
    assert rep["stop_reason"] == "candidate_passed_dev_val"
    assert rep["oos_consulted"] is False
    assert rep["strategy_promoted"] is False
    # parou na 1a candidata: a 2a nem foi testada
    assert [r["name"] for r in rep["results"]] == ["good"]
    assert rep["results"][0]["status"] == "candidate_pending_approval"


def test_val_only_after_dev():
    seen = []

    def evaluator(h, seg):
        seen.append(seg)
        return {"classification": "sem_edge_operacional",
                "verdict": {"edge_estatistico": "rejeitado"}}

    rep = run_research_loop([_spec("h")], evaluator).to_dict()
    assert seen == ["DEV"]            # DEV reprovou => VAL nao roda
    assert rep["results"][0]["status"] == "rejected_dev"


def test_not_promotable_marker_blocks_candidate():
    passing = {"classification": "candidata_paper",
               "verdict": {"edge_estatistico": "aprovado",
                           "robustez_temporal": "aprovado"}}
    rep = run_research_loop(
        [_spec("h", markers=("exploratory", "not_for_promotion"))],
        lambda h, s: passing).to_dict()
    assert rep["candidate"] is None
    assert rep["results"][0]["status"] == "passed_but_not_promotable"


def test_hypothesis_limit():
    specs = [_spec(f"h{i}", family=f"f{i}") for i in range(7)]

    def evaluator(h, seg):
        return {"classification": "sem_edge_operacional",
                "verdict": {"edge_estatistico": "rejeitado"}}

    rep = run_research_loop(specs, evaluator, max_hypotheses=5).to_dict()
    assert rep["limits"]["tested"] == 5
    assert rep["stop_reason"] == "reached_hypothesis_limit"


def test_insufficient_data_path():
    rep = run_research_loop(
        [_spec("h", markers=("insufficient_history",))],
        lambda h, s: {},
        data_sufficiency=lambda h: {"sufficient": False, "feeds": {}}).to_dict()
    assert rep["results"][0]["status"] == "insufficient_prospective_data"
    assert "insufficient_prospective_data" in rep["failure_patterns"]
    assert "ACUMULAR" in rep["recommendation"] or "acumular" \
        in rep["recommendation"].lower()
