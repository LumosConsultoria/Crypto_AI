"""
SupervisedReadiness (FASE 35)
==============================
Consolida evidencias de reports JA SALVOS (offline) e produz o
ReadinessReport consultivo.

⚠️  OFFLINE: le apenas arquivos JSON locais. ZERO rede. ZERO ordem.
⚠️  'ready' NUNCA habilita live/mainnet — fase futura propria, com
    gates e autorizacao explicita.

Fontes reconhecidas (heuristica por chaves):
    - Demo endurance FASE 30: payload com outcome.ended_reason.
    - Demo 30min FASE 29: payload com outcome.demo_finalization_scenario.
    - Advisor FASE 33: payload com candidate_strategy + ranking.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.readiness.readiness_report import (
    ReadinessReport,
    ReadinessVerdict,
)
from crypto_trading_bot.readiness.readiness_rules import (
    ReadinessEvidence,
    evaluate_rules,
)


def _safe_load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def collect_evidence_from_reports_dir(
    reports_dir: str,
) -> Tuple[ReadinessEvidence, int]:
    """Varre *.json no diretorio e consolida evidencias.

    Retorna (evidence, reports_scanned). Arquivos ilegiveis sao
    ignorados (nunca levanta por dado ruim).
    """
    base = Path(reports_dir)
    scanned = 0
    sessions = 0
    short_clean = 0
    short_completed = 0
    long_completed = 0
    residual = 0
    open_orders = 0
    missing_sl_tp = 0
    flat_failures = 0
    unresolved_pnl = 0
    safety_total = 0
    api_total = 0
    risk_violations = 0
    manual_reviews = 0
    ai_vetoes = 0
    ai_warnings = 0
    overfit_critical = 0
    pred_critical = 0
    pred_warnings = 0

    if base.is_dir():
        for path in sorted(base.glob("*.json")):
            data = _safe_load_json(path)
            if data is None:
                continue
            scanned += 1
            outcome = data.get("outcome")
            if isinstance(outcome, Mapping):
                ended = str(outcome.get("ended_reason", ""))
                scenario = str(
                    outcome.get("demo_finalization_scenario", ""),
                )
                if ended or scenario:
                    sessions += 1
                # FASE 30 endurance
                if ended:
                    dur_days = outcome.get("configured_duration_days")
                    is_long = dur_days is not None
                    completed = ended in (
                        "duration_completed", "passed_zero_trades",
                        "would_order_completed",
                        "dry_run_would_order_completed",
                        "order_completed", "graceful_shutdown",
                    )
                    if completed and is_long:
                        long_completed += 1
                    elif completed:
                        short_completed += 1
                    if ended == "manual_review_required":
                        manual_reviews += 1
                    if ended == "safety_halt":
                        safety_total += 1
                    api_total += int(outcome.get("api_failures", 0))
                    safety_total += int(
                        outcome.get("safety_events", 0),
                    )
                    summary = outcome.get("session_summary") or {}
                    if isinstance(summary, Mapping):
                        if summary.get("ai_status") == "veto":
                            ai_vetoes += 1
                        ai_warnings += len(
                            summary.get("ai_warnings") or [],
                        )
                        pm = summary.get(
                            "prediction_market_context",
                        ) or {}
                        if isinstance(pm, Mapping):
                            pred_warnings += len(
                                pm.get("risk_flags") or [],
                            )
                # FASE 29 demo 30 min
                if scenario:
                    if scenario == "A_clean":
                        short_clean += 1
                        short_completed += 1
                    elif scenario == "B_zero":
                        short_completed += 1
                    elif scenario == "C_manual":
                        manual_reviews += 1
                    residual += int(
                        outcome.get("open_positions_count", 0),
                    )
                    open_orders += int(
                        outcome.get("open_orders_count", 0),
                    )
                    risk_violations += int(
                        outcome.get("risk_violations_count", 0),
                    )
                    if bool(outcome.get("orders_submitted", 0)) and \
                            outcome.get("pnl_realized_usd") is None \
                            and scenario != "B_zero":
                        unresolved_pnl += 1
                    sl = outcome.get("sl_attached")
                    tp = outcome.get("tp_attached")
                    if bool(outcome.get("orders_submitted", 0)) and (
                        sl is False or tp is False
                    ):
                        missing_sl_tp += 1
                    flat = outcome.get("flat_check_result")
                    if isinstance(flat, Mapping) and \
                            flat.get("is_flat") is False:
                        flat_failures += 1
            # Advisor FASE 33
            if "candidate_strategy" in data and "ranking" in data:
                for row in (data.get("ranking") or []):
                    if isinstance(row, Mapping) and \
                            row.get("overfitting_warning"):
                        overfit_critical += 1
                        break
            # Readiness anteriores sao ignorados (evita recursao).

    evidence = ReadinessEvidence(
        total_sessions=sessions,
        short_demo_clean_count=short_clean,
        short_demo_completed_count=short_completed,
        long_demo_completed_count=long_completed,
        residual_positions=residual,
        unexpected_open_orders=open_orders,
        orders_missing_sl_tp=missing_sl_tp,
        flat_check_failures=flat_failures,
        unresolved_pnl_count=unresolved_pnl,
        safety_events_total=safety_total,
        api_failures_total=api_total,
        risk_violations_total=risk_violations,
        unresolved_manual_reviews=manual_reviews,
        ai_critical_vetoes=ai_vetoes,
        ai_warnings_total=ai_warnings,
        advisor_overfitting_critical=overfit_critical,
        prediction_critical_unhandled=pred_critical,
        prediction_warnings_total=pred_warnings,
    )
    return evidence, scanned


def evaluate_supervised_readiness(
    *,
    evidence: ReadinessEvidence,
    profile: Optional[Any] = None,
    profile_name: str = "",
    reports_scanned: int = 0,
    now: Optional[datetime] = None,
    # FASE 36 Bloco F - evidencias operacionais novas (opcionais;
    # defaults preservam o comportamento FASE 35).
    operator_inputs_blocking: Optional[bool] = None,
    operator_inputs_missing: int = 0,
    demo_credentials_present: Optional[bool] = None,
    stale_data_detected: bool = False,
    unresolved_position: bool = False,
    risk_policy_unresolved: bool = False,
    decision_trace_available: Optional[bool] = None,
) -> ReadinessReport:
    """Aplica as regras sobre evidencias consolidadas.

    Precedencia FASE 36 (antes das regras FASE 35):
        missing_operator_input > missing_credentials >
        unresolved_position > unresolved_risk_policy > stale_data.
    Readiness continua CONSULTIVO (nunca autoriza execucao).
    """
    now = now or datetime.now(timezone.utc)

    pre_verdict: Optional[str] = None
    pre_blockers: list = []
    if operator_inputs_blocking is True:
        pre_verdict = "blocked_missing_operator_input"
        pre_blockers.append(
            f"operator inputs obrigatorios ausentes "
            f"({operator_inputs_missing})"
        )
    elif demo_credentials_present is False:
        pre_verdict = "blocked_missing_credentials"
        pre_blockers.append(
            "credenciais demo ausentes (presence-only)"
        )
    elif unresolved_position:
        pre_verdict = "blocked_unresolved_position"
        pre_blockers.append("posicao nao resolvida")
    elif risk_policy_unresolved:
        pre_verdict = "blocked_unresolved_risk_policy"
        pre_blockers.append(
            "politica de risco nao resolvida (limites V5-V8 "
            "exigidos por capacidade habilitada)"
        )
    elif stale_data_detected:
        pre_verdict = "blocked_stale_data"
        pre_blockers.append("dados stale detectados")

    if pre_verdict is not None:
        return ReadinessReport(
            verdict=ReadinessVerdict(pre_verdict),
            profile_name=(
                profile_name or getattr(profile, "name", "")
                or "unknown"
            ),
            evaluated_at=now,
            evidence=evidence,
            blockers=tuple(pre_blockers),
            warnings=(
                ("decision_trace_unavailable",)
                if decision_trace_available is False else ()
            ),
            reports_scanned=reports_scanned,
        )

    verdict_str, blockers, warnings = evaluate_rules(
        evidence, profile=profile,
    )
    if decision_trace_available is False:
        warnings = list(warnings) + ["decision_trace_unavailable"]
    return ReadinessReport(
        verdict=ReadinessVerdict(verdict_str),
        profile_name=(
            profile_name or getattr(profile, "name", "") or "unknown"
        ),
        evaluated_at=now,
        evidence=evidence,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        reports_scanned=reports_scanned,
    )


def run_supervised_readiness_from_dir(
    *,
    reports_dir: str,
    profile: Optional[Any] = None,
    profile_name: str = "",
    now: Optional[datetime] = None,
) -> ReadinessReport:
    """Conveniencia: coleta evidencias do dir e avalia."""
    evidence, scanned = collect_evidence_from_reports_dir(reports_dir)
    return evaluate_supervised_readiness(
        evidence=evidence, profile=profile,
        profile_name=profile_name, reports_scanned=scanned, now=now,
    )


__all__ = [
    "collect_evidence_from_reports_dir",
    "evaluate_supervised_readiness",
    "run_supervised_readiness_from_dir",
]
