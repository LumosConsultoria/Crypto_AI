"""
FASE 53 re-escopo — hipoteses NORMAIS propostas + integracao com o research
loop. 100% OFFLINE. Verifica que as specs sao validas (racional obrigatorio),
respeitam limites (<=5 hip, <=2 variantes), usam SO dados permitidos e que o
loop as aceita (sem rodar backtest real). Sem rede/ordem.
"""

from __future__ import annotations

from crypto_trading_bot.research.normal_hypotheses import proposed_hypotheses
from crypto_trading_bot.research.research_loop import (
    MAX_HYPOTHESES, MAX_VARIANTS, run_research_loop)

_ALLOWED_DATA = {"ohlcv", "calendar", "funding", "open_interest", "costs",
                 "session"}


def test_proposed_specs_valid_and_within_limits():
    hyps = proposed_hypotheses()
    assert 1 <= len(hyps) <= MAX_HYPOTHESES
    families = [h.family for h in hyps]
    assert len(set(families)) == len(families)          # familias distintas
    for h in hyps:
        ok, errs = h.validate()
        assert ok, f"{h.name}: {errs}"
        assert h.variants <= MAX_VARIANTS
        assert set(h.data_used) <= _ALLOWED_DATA, h.data_used
        # racional/diferenca preenchidos (registro obrigatorio)
        assert h.economic_rationale and h.why_different
        assert h.expected_reason_to_work


def test_no_microstructure_data_used():
    forbidden = {"orderbook", "l2", "liquidation", "tick", "trade_tape",
                 "on_chain"}
    for h in proposed_hypotheses():
        assert not (set(h.data_used) & forbidden)


def test_specs_are_real_candidates_not_marked_not_for_promotion():
    # estas sao candidatas a validar (nao exploratorias bloqueadas)
    blocking = {"not_for_promotion", "invalid_for_validation",
                "insufficient_history"}
    for h in proposed_hypotheses():
        assert not (set(h.markers) & blocking)


def test_loop_accepts_agenda_without_oos():
    # evaluator fake reprova no DEV => loop nunca toca VAL/OOS; prova que a
    # agenda passa pela validacao e roda no loop controlado.
    seen = []

    def evaluator(h, seg):
        seen.append((h.name, seg))
        return {"classification": "sem_edge_operacional",
                "verdict": {"edge_estatistico": "reprovado"}}

    rep = run_research_loop(proposed_hypotheses(), evaluator).to_dict()
    assert rep["oos_consulted"] is False
    assert rep["candidate"] is None
    assert all(seg == "DEV" for _, seg in seen)          # DEV reprovou => sem VAL
    assert rep["limits"]["tested"] == len(proposed_hypotheses())
