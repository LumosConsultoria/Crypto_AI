"""
FASE 47 — BudgetGuard do coletor shadow de IA. 100% OFFLINE.
Limite diario de chamadas + orcamento; fail-safe ao atingir; reset por dia
UTC. Garante que o shadow real NUNCA estoura 50 chamadas/dia nem US$0,25/dia.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = (Path(__file__).resolve().parents[1] / "scripts"
           / "run_ai_shadow_collect.py")


def _load_guard():
    spec = importlib.util.spec_from_file_location("ai_shadow_cli", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.BudgetGuard


def test_blocks_after_max_calls(tmp_path):
    BudgetGuard = _load_guard()
    g = BudgetGuard(str(tmp_path / "b.json"), max_calls=3,
                    max_budget_usd=1.0, est_cost_per_call=0.004)
    for _ in range(3):
        assert g.can_call()
        g.register()
    assert not g.can_call()                 # fail-safe por nº de chamadas
    assert g.state["calls"] == 3


def test_blocks_after_budget(tmp_path):
    BudgetGuard = _load_guard()
    # orcamento 0,01 e custo 0,004 => no maximo 2 chamadas (0,008); a 3a
    # estouraria (0,012 > 0,01)
    g = BudgetGuard(str(tmp_path / "b.json"), max_calls=999,
                    max_budget_usd=0.01, est_cost_per_call=0.004)
    assert g.can_call(); g.register()
    assert g.can_call(); g.register()
    assert not g.can_call()                 # fail-safe por orcamento
    assert g.state["spent_usd"] <= 0.01


def test_approved_limits_50_and_025(tmp_path):
    BudgetGuard = _load_guard()
    g = BudgetGuard(str(tmp_path / "b.json"), max_calls=50,
                    max_budget_usd=0.25, est_cost_per_call=0.004)
    n = 0
    while g.can_call():
        g.register(); n += 1
    assert n == 50                          # 50×0,004=0,20 < 0,25 => 50 limita
    assert g.state["spent_usd"] <= 0.25


def test_persists_same_day(tmp_path):
    BudgetGuard = _load_guard()
    p = str(tmp_path / "b.json")
    g1 = BudgetGuard(p, max_calls=50, max_budget_usd=0.25, est_cost_per_call=0.004)
    g1.register(); g1.register()
    g2 = BudgetGuard(p, max_calls=50, max_budget_usd=0.25, est_cost_per_call=0.004)
    assert g2.state["calls"] == 2           # estado do dia persiste


def test_tracks_real_cost_and_tokens(tmp_path):
    BudgetGuard = _load_guard()
    g = BudgetGuard(str(tmp_path / "b.json"), max_calls=50,
                    max_budget_usd=0.25, est_cost_per_call=0.004)
    g.register(actual_cost_usd=0.0006, in_tokens=250, out_tokens=80)
    g.register(actual_cost_usd=0.0007, in_tokens=260, out_tokens=90)
    s = g.state
    assert s["calls"] == 2
    assert abs(s["spent_usd"] - 0.0013) < 1e-9     # custo REAL somado
    assert s["input_tokens"] == 510 and s["output_tokens"] == 170
