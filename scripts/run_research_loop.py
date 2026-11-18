"""
run_research_loop (FASE 53 re-escopo) — loop de pesquisa controlado, simples e
pratico, sobre dados NORMAIS (OHLCV/volume/funding/OI/custos/calendario). SEM
microestrutura. Avaliacao SEMPRE pelos DOIS perfis obrigatorios via
standard_report (Hyro Challenge 5k + Trader Padrao 5k).

Esta CLI registra/valida a AGENDA de hipoteses propostas (racional antes do
teste). A execucao real (detectores + DEV/VAL via standard_report) e ligada
APOS aprovacao do operador da agenda. OOS intocado; sem ordem/demo/live.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Research loop FASE 53 (agenda)")
    ap.add_argument("--output", default="reports/research_agenda_phase53.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from crypto_trading_bot.research.normal_hypotheses import (
        proposed_hypotheses)
    from crypto_trading_bot.research.research_loop import (
        MAX_HYPOTHESES, MAX_VARIANTS)

    hyps = proposed_hypotheses()
    agenda = []
    for h in hyps:
        ok, errs = h.validate()       # registro OBRIGATORIO antes de testar
        agenda.append({
            "name": h.name, "family": h.family, "variants": h.variants,
            "spec_valid": ok, "spec_errors": errs,
            "economic_rationale": h.economic_rationale,
            "why_different": h.why_different, "data_used": list(h.data_used),
            "fixed_params": dict(h.fixed_params),
            "accept_criteria": h.accept_criteria,
            "expected_reason_to_work": h.expected_reason_to_work,
            "status": "pending_approval_and_detector"})

    report = {
        "schema": "research_agenda_phase53_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": ("dados NORMAIS: OHLCV, indicadores preco/volume, funding, "
                  "open interest, custos, calendario/sessao; IA/Polymarket "
                  "shadow. SEM orderbook/L2/liquidacoes/tick/on-chain/pago."),
        "mandatory_profiles": {
            "hyro_challenge_5k": {
                "capital": 5000, "risk_per_trade_pct": 0.5,
                "daily_drawdown_pct": 4, "max_loss_pct": 6,
                "session_loss_pct": 1, "kill_switch_usd": 50,
                "cooldown_after_losses": 2, "leverage": "1x",
                "max_positions": 1, "profit_target_pct": 10,
                "concentration": True, "min_days": True,
                "verdict": "passaria/falharia"},
            "trader_padrao_5k": {
                "capital": 5000, "risk_primary_pct": 0.5,
                "risk_extra_analysis_pct": 1, "profit_target": "nao obrigatoria",
                "daily_drawdown_challenge": False,
                "concentration_as_reject": False, "maxdd_as_gate_pct": 25,
                "pf_net_min": 1.15, "return_dd_min": 0,
                "sign_consistency_min": 0.6, "verdict": "aprovado/rejeitado"}},
        "final_classification_rule": {
            "hyro_pass + trader_pass": "candidata",
            "hyro_fail + trader_pass": "edge_possivel_incompativel_com_challenge",
            "trader_fail": "sem_edge_operacional"},
        "loop_rules": {"max_hypotheses": MAX_HYPOTHESES,
                       "max_variants": MAX_VARIANTS, "grid_search": False,
                       "tune_on_val": False, "oos_consulted": False,
                       "stop_on_dev_val_pass": True,
                       "per_hypothesis_report": True},
        "hypotheses": agenda,
        "next_step": ("aprovar a agenda => implementar 1 detector por hipotese "
                      "(params fixos) => run via standard_report dual-profile "
                      "DEV (+VAL se DEV passar); OOS so apos aprovacao."),
        "real_execution_allowed": False, "demo_blocked": True,
        "live_blocked": True, "strategy_promoted": False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(f"AGENDA de pesquisa (FASE 53) — {len(agenda)} hipoteses normais "
          f"(max {MAX_HYPOTHESES}); perfis obrigatorios: Hyro 5k + Trader Padrao")
    for a in agenda:
        print(f"  [{a['spec_valid']}] {a['name']:26} ({a['family']}) "
              f"dados={a['data_used']}")
        print(f"       diferente: {a['why_different'][:80]}...")
    print(f"\nproximo: {report['next_step']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
