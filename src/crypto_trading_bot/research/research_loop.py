"""
Research Loop controlado (FASE 53) — testa MULTIPLAS hipoteses sem parar na
primeira rejeicao, mas com LIMITES claros e registro OBRIGATORIO. CONSOME o
standard_report dual-profile (NAO o altera => modulo nao-compartilhado tocado).

Regras: registro obrigatorio antes de testar; <=5 hipoteses/fase; <=2 variantes/
hipotese; sem grid; sem tuning na VAL; OOS INTOCADO (o loop NUNCA avalia OOS);
VAL so se DEV passar; para se uma candidata passar DEV+VAL (e PEDE aprovacao,
nao consulta OOS). Marcadores de Parte C (insufficient_history/exploratory/
invalid_for_validation/not_for_promotion) impedem promocao.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import (Any, Callable, Dict, List, Mapping, Optional, Sequence,
                    Tuple)

MAX_HYPOTHESES = 5
MAX_VARIANTS = 2
SPEC_FIELDS = ("name", "economic_rationale", "why_different", "data_used",
               "fixed_params", "accept_criteria", "expected_reason_to_work")
NOT_FOR_PROMOTION = {"insufficient_history", "invalid_for_validation",
                     "exploratory", "not_for_promotion"}


@dataclass(frozen=True)
class HypothesisSpec:
    name: str
    economic_rationale: str
    why_different: str            # por que difere das rejeitadas (38-52.1)
    data_used: Sequence[str]
    fixed_params: Mapping[str, Any]
    accept_criteria: str
    expected_reason_to_work: str
    family: str = ""
    variants: int = 1
    markers: Sequence[str] = field(default_factory=tuple)

    def validate(self) -> Tuple[bool, List[str]]:
        errs: List[str] = []
        for f in SPEC_FIELDS:
            v = getattr(self, f)
            empty = (v is None or (isinstance(v, str) and not v.strip())
                     or (isinstance(v, (list, tuple, dict)) and len(v) == 0))
            if empty:
                errs.append(f"campo obrigatorio vazio: {f}")
        if self.variants > MAX_VARIANTS:
            errs.append(f"variants {self.variants} > {MAX_VARIANTS}")
        return (not errs), errs


def _dev_passes(sr: Mapping[str, Any]) -> bool:
    v = sr.get("verdict", {}) or {}
    return (v.get("edge_estatistico") == "aprovado"
            and sr.get("classification") != "sem_edge_operacional")


def _val_passes(sr: Mapping[str, Any]) -> bool:
    v = sr.get("verdict", {}) or {}
    return (v.get("edge_estatistico") == "aprovado"
            and v.get("robustez_temporal") == "aprovado"
            and sr.get("classification") == "candidata_paper")


@dataclass(frozen=True)
class ResearchLoopReport:
    schema: str
    generated_at: str
    results: Tuple[Mapping[str, Any], ...]
    stop_reason: str
    candidate: Optional[str]
    ranking: Tuple[Mapping[str, Any], ...]
    failure_patterns: Mapping[str, int]
    recommendation: str
    limits: Mapping[str, Any]
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "generated_at": self.generated_at,
                "results": [dict(r) for r in self.results],
                "stop_reason": self.stop_reason, "candidate": self.candidate,
                "ranking": [dict(r) for r in self.ranking],
                "failure_patterns": dict(self.failure_patterns),
                "recommendation": self.recommendation,
                "limits": dict(self.limits),
                "oos_consulted": False, "real_execution_allowed": False,
                "demo_blocked": True, "live_blocked": True,
                "strategy_promoted": False, "notes": list(self.notes)}


def run_research_loop(
    hypotheses: Sequence[HypothesisSpec],
    evaluator: Callable[[HypothesisSpec, str], Optional[Mapping[str, Any]]], *,
    max_hypotheses: int = MAX_HYPOTHESES,
    data_sufficiency: Optional[Callable[[HypothesisSpec], Mapping[str, Any]]]
    = None, progress=None) -> ResearchLoopReport:
    """`evaluator(spec, segment)` retorna um standard_report (dict) ou None.
    O loop SO chama segment 'VAL' se 'DEV' passar. OOS NUNCA e avaliado."""

    def _cb(m):
        if progress:
            progress(m)

    results: List[Dict[str, Any]] = []
    families: Dict[str, int] = {}
    stop_reason: Optional[str] = None
    candidate: Optional[str] = None
    tested = 0

    for h in hypotheses:
        if tested >= max_hypotheses:
            stop_reason = "reached_hypothesis_limit"
            break
        ok, errs = h.validate()
        if not ok:
            results.append({"name": h.name, "status": "invalid_spec",
                            "errors": errs})
            continue
        fam = h.family or h.name
        families[fam] = families.get(fam, 0) + 1
        if families[fam] > MAX_VARIANTS:
            stop_reason = "becoming_variations_of_same_idea"
            break
        if data_sufficiency is not None:
            suff = data_sufficiency(h)
            if not suff.get("sufficient", True):
                results.append({"name": h.name, "family": fam,
                                "status": "insufficient_prospective_data",
                                "detail": dict(suff),
                                "markers": list(h.markers),
                                "spec": asdict(h)})
                tested += 1
                continue
        _cb(f"hipotese DEV: {h.name}")
        dev = evaluator(h, "DEV") or {}
        tested += 1
        entry: Dict[str, Any] = {
            "name": h.name, "family": fam, "markers": list(h.markers),
            "spec": asdict(h),
            "dev": {"classification": dev.get("classification"),
                    "verdict": dev.get("verdict"),
                    "strategy_metrics": dev.get("strategy_metrics")}}
        if dev.get("classification") == "insufficient_history" \
                or "insufficient_history" in h.markers:
            entry["status"] = "insufficient_history"
            entry["report"] = {"dev": dev}
            results.append(entry)
            continue
        if not _dev_passes(dev):
            entry["status"] = "rejected_dev"
            entry["reject_reason"] = dev.get("classification") or "no_edge_dev"
            entry["report"] = {"dev": dev}
            results.append(entry)
            continue
        _cb(f"hipotese VAL: {h.name}")
        val = evaluator(h, "VAL") or {}
        entry["val"] = {"classification": val.get("classification"),
                        "verdict": val.get("verdict")}
        entry["report"] = {"dev": dev, "val": val}
        promotable = not (NOT_FOR_PROMOTION & set(h.markers))
        if _val_passes(val) and promotable:
            entry["status"] = "candidate_pending_approval"
            results.append(entry)
            candidate = h.name
            stop_reason = "candidate_passed_dev_val"
            break
        entry["status"] = ("passed_but_not_promotable" if _val_passes(val)
                           else "rejected_val")
        entry["reject_reason"] = (val.get("classification")
                                  if not _val_passes(val) else
                                  "marcada_nao-promovivel")
        results.append(entry)

    if stop_reason is None:
        stop_reason = "exhausted_hypotheses"

    # ranking das rejeitadas + padroes de falha
    rank_order = {"rejected_val": 0, "passed_but_not_promotable": 1,
                  "rejected_dev": 2, "insufficient_history": 3,
                  "insufficient_prospective_data": 4, "invalid_spec": 5}
    rejected = [r for r in results if r.get("status") != "candidate_pending_approval"]
    ranking = sorted(rejected, key=lambda r: rank_order.get(r["status"], 9))
    patterns: Dict[str, int] = {}
    for r in rejected:
        patterns[r["status"]] = patterns.get(r["status"], 0) + 1

    if candidate:
        recommendation = (f"CANDIDATA '{candidate}' passou DEV+VAL. PARAR. NAO "
                          "consultar OOS automaticamente; pedir APROVACAO antes "
                          "do OOS. Marcada candidata, NAO validada. paper/demo/"
                          "live bloqueados ate aprovacao explicita.")
    elif patterns.get("insufficient_prospective_data") or \
            patterns.get("insufficient_history"):
        recommendation = ("Dados prospectivos insuficientes p/ validar. ACUMULAR "
                          "amostra (orderbook/trade_flow via coleta gated) ate "
                          "readiness=ready; so entao testar hipoteses reais. "
                          "Nada promovido.")
    elif not results:
        recommendation = "Nenhuma hipotese registrada. Registrar specs validos."
    else:
        recommendation = ("Nenhuma candidata. Ver ranking + padroes de falha; "
                          "propor proxima direcao estruturalmente diferente "
                          "(nao repetir breakout/trend/vol/funding).")

    return ResearchLoopReport(
        schema="research_loop_report_v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        results=tuple(results), stop_reason=stop_reason, candidate=candidate,
        ranking=tuple(ranking), failure_patterns=patterns,
        recommendation=recommendation,
        limits={"max_hypotheses": max_hypotheses, "max_variants": MAX_VARIANTS,
                "tested": tested, "oos_consulted": False},
        notes=("Loop controlado: registro obrigatorio; VAL so apos DEV; OOS "
               "intocado; candidata NAO e validada (pede aprovacao). Sem grid; "
               "sem tuning na VAL; sem ordem/demo/live.",
               "Marcadores insufficient_history/exploratory/invalid_for_"
               "validation/not_for_promotion impedem promocao (Parte C).",))


__all__ = ["HypothesisSpec", "ResearchLoopReport", "run_research_loop",
           "MAX_HYPOTHESES", "MAX_VARIANTS"]
