#!/usr/bin/env python
"""
validate_demo_30m_phase29_report.py - FASE 29 validator
==========================================================
ASCII-only. 100% OFFLINE. ZERO network. ZERO secret.

Valida par de artefatos da sessao FASE 29:
    1. --report <path>.json      (--output do CLI FASE 29)
    2. --telemetry <path>.jsonl  (--telemetry-output do CLI)

Reportes da FASE 29 sao distintos da FASE 28:
    - real_demo_full_cycle == True
    - phase == "29"
    - outcome.apply_demo_real_invoked == True
    - outcome.first_real_demo_order == True

Cenarios aceitos com exit 0:
    A) demo_full_cycle_clean (Demo finalizada):
       entry submetida + SL/TP confirmados + exit detectada +
       flat_check_final.is_flat=True + P&L registrado (ou
       manual_pending).
    B) passed_zero_trades (seguro mas NAO finaliza):
       sem entrada; ainda aprovado mas com sinalizacao especifica.
    C) manual_close_required (sessao encerrada mas NAO finaliza):
       entrada submetida mas exit nao automatica.

Exit codes:
    0 - aprovado (qualquer A, B, C valido conforme criterios)
    1 - rejeitado (lista de violacoes)
    2 - arquivo invalido / IO error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


_SECRET_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:", "origin_string",
)


def _check_no_secret_substrings(text: str, *, source: str) -> List[str]:
    issues: List[str] = []
    lower = text.lower()
    for tok in _SECRET_SUBSTRINGS:
        if tok in lower:
            issues.append(
                f"[{source}] suspicious token '{tok}' detected"
            )
    return issues


def _load_jsonl(path: Path) -> List[dict]:
    events: List[dict] = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(
                f"invalid JSONL line in {path.name}: {e}"
            )
    return events


def _validate_phase29_report(
    data: dict, *, report_text: str,
) -> tuple:
    """Retorna (issues, scenario) onde scenario in
    {A_clean, B_zero, C_manual, unknown}."""
    issues: List[str] = []
    issues.extend(_check_no_secret_substrings(
        report_text, source="report_text",
    ))

    if data.get("phase") != "29":
        issues.append("phase must be '29'")
    if data.get("real_demo_full_cycle") is not True:
        issues.append("real_demo_full_cycle must be True")

    outcome = data.get("outcome", {})
    if not isinstance(outcome, dict):
        issues.append("outcome missing or invalid")
        return issues, "unknown"

    verdict = outcome.get("verdict", "")
    orders_submitted = int(outcome.get("orders_submitted", 0))
    orders_filled = int(outcome.get("orders_filled", 0))
    open_positions = int(outcome.get("open_positions_count", 0))
    safety_state = outcome.get("safety_state", "")
    manual_review = outcome.get("manual_review_required")
    safety_halt = outcome.get("safety_halt_recommended")
    exit_path = outcome.get("exit_management_path", "none")
    close_submitted = int(outcome.get("close_orders_submitted", 0))
    close_filled = int(outcome.get("close_orders_filled", 0))
    flat_check = outcome.get("flat_check_result") or {}
    pnl_source = outcome.get("pnl_source")
    apply_real = outcome.get("apply_demo_real_invoked")
    first_real = outcome.get("first_real_demo_order")
    phrase = outcome.get("phrase_confirmation")
    demo_finalized = outcome.get("demo_finalized")
    finalization_scenario = outcome.get(
        "demo_finalization_scenario", "unknown",
    )

    if apply_real is not True:
        issues.append("apply_demo_real_invoked must be True")
    if first_real is not True:
        issues.append("first_real_demo_order must be True")
    if phrase is not True:
        issues.append("phrase_confirmation must be True")
    if outcome.get("mode") != "real_endurance":
        issues.append("outcome.mode must be 'real_endurance'")
    if safety_state != "normal":
        issues.append(f"safety_state must be 'normal'; got {safety_state}")

    # close orders constraints
    if close_submitted < 0:
        issues.append("close_orders_submitted < 0")
    if close_filled > close_submitted:
        issues.append("close_orders_filled > close_orders_submitted")
    if close_submitted > 1:
        issues.append(
            "close_orders_submitted > 1 (FASE 29 hard cap)"
        )

    # readiness
    readiness = data.get("readiness", {})
    if isinstance(readiness, dict):
        if readiness.get("status") != "ready":
            issues.append("readiness.status must be 'ready'")

    # Determine scenario.
    # FASE 29 Acceptance Polish: verdict canonico DEMO_FULL_CYCLE_CLEAN
    # eh o UNICO que finaliza Demo (A_clean). demo_finalized=True deve
    # acompanhar. Sem ambiguidade.
    if verdict == "demo_full_cycle_clean":
        scenario = "A_clean"
        if demo_finalized is not True:
            issues.append(
                "demo_full_cycle_clean requires demo_finalized=True"
            )
        if finalization_scenario != "A_clean":
            issues.append(
                "demo_full_cycle_clean requires "
                "demo_finalization_scenario='A_clean'"
            )
        if not (orders_submitted == 1 and orders_filled == 1):
            issues.append(
                "A_clean requires orders_submitted=1, orders_filled=1"
            )
        if open_positions != 0:
            issues.append("A_clean requires open_positions_count=0")
        if flat_check.get("is_flat") is not True:
            issues.append("A_clean requires flat_check.is_flat=True")
        if manual_review is True:
            issues.append(
                "A_clean requires manual_review_required=False"
            )
        if safety_halt is True:
            issues.append(
                "A_clean requires safety_halt_recommended=False"
            )
        if exit_path == "none":
            issues.append(
                "A_clean requires exit_management_path != 'none'"
            )
        if pnl_source not in (
            "api_execution_list", "api_closed_pnl",
            "local_calculation", "manual_pending",
        ):
            issues.append(
                f"pnl_source invalid for A_clean: {pnl_source}"
            )
    elif verdict == "passed_zero_trades" and orders_submitted == 0:
        scenario = "B_zero"
        if exit_path != "none":
            issues.append(
                "zero trade scenario must have exit_management_path='none'"
            )
        if demo_finalized is True:
            issues.append(
                "B_zero must NOT have demo_finalized=True"
            )
    elif (verdict == "manual_review_required"
          or exit_path == "manual_fallback"):
        scenario = "C_manual"
        if demo_finalized is True:
            issues.append(
                "C_manual must NOT have demo_finalized=True"
            )
    else:
        scenario = "unknown"
        issues.append(
            f"unknown scenario: verdict={verdict} "
            f"orders={orders_submitted} exit_path={exit_path}"
        )

    return issues, scenario


def _validate_phase29_telemetry(
    events: List[dict], *, telemetry_text: str, scenario: str,
) -> List[str]:
    issues: List[str] = []
    issues.extend(_check_no_secret_substrings(
        telemetry_text, source="telemetry_text",
    ))
    types_present = {
        e.get("event_type") for e in events if isinstance(e, dict)
    }
    for required in (
        "session_start", "preflight_done", "session_end",
    ):
        if required not in types_present:
            issues.append(
                f"telemetry missing event_type='{required}'"
            )
    if scenario == "A_clean":
        for required in (
            "entry_gate_invoked", "exit_monitoring_started",
            "exit_detected",
        ):
            # gate_invoked from FASE 28 also acceptable as entry_gate
            if required == "entry_gate_invoked" and \
                    "gate_invoked" in types_present:
                continue
            if required not in types_present:
                issues.append(
                    f"clean scenario telemetry missing "
                    f"'{required}'"
                )
        # Se reduceOnly, exit_gate_invoked.dry_run must be False (real)
        for e in events:
            if not isinstance(e, dict):
                continue
            if e.get("event_type") == "exit_gate_invoked":
                snap = e.get("snapshot") or {}
                if snap.get("dry_run") is True:
                    issues.append(
                        "FASE 29 exit_gate_invoked.dry_run must be False"
                    )

    # gate_invoked.dry_run must be False in FASE 29
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("event_type") == "gate_invoked":
            snap = e.get("snapshot") or {}
            if snap.get("dry_run") is True:
                issues.append(
                    "FASE 29 gate_invoked.dry_run must be False"
                )
    return issues


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate FASE 29 real demo full cycle report + telemetry. "
            "Offline; never sends order."
        ),
    )
    parser.add_argument(
        "--report", type=str, required=True,
        help="Path to JSON report.",
    )
    parser.add_argument(
        "--telemetry", type=str, default="",
        help="Optional path to JSONL telemetry.",
    )
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if any(part == ".." for part in report_path.parts):
        print("ERROR --report path contains '..' (rejected)")
        return 2
    if not report_path.is_file():
        print(f"ERROR report file not found: {args.report}")
        return 2

    try:
        report_text = report_path.read_text(encoding="utf-8")
        data = json.loads(report_text)
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR parsing report: {type(e).__name__}: "
              f"{str(e)[:160]}")
        return 2

    issues, scenario = _validate_phase29_report(
        data, report_text=report_text,
    )

    if args.telemetry:
        tel_path = Path(args.telemetry)
        if any(part == ".." for part in tel_path.parts):
            print("ERROR --telemetry path contains '..' (rejected)")
            return 2
        if not tel_path.is_file():
            print(f"ERROR telemetry file not found: {args.telemetry}")
            return 2
        try:
            tel_text = tel_path.read_text(encoding="utf-8")
            events = _load_jsonl(tel_path)
        except (ValueError, OSError) as e:
            print(
                f"ERROR parsing telemetry: "
                f"{type(e).__name__}: {str(e)[:160]}"
            )
            return 2
        issues.extend(_validate_phase29_telemetry(
            events, telemetry_text=tel_text, scenario=scenario,
        ))

    if issues:
        print("FASE 29 report validation FAILED:")
        for i in issues:
            print(f"  - {i}")
        return 1

    print(f"FASE 29 report validation OK (scenario={scenario}).")
    if scenario == "A_clean":
        print("  DEMO FINALIZED. demo_full_cycle_clean achieved.")
    elif scenario == "B_zero":
        print(
            "  Safe but inconclusive (zero trade). "
            "DEMO NOT YET FINALIZED."
        )
    elif scenario == "C_manual":
        print(
            "  Manual close path used. "
            "DEMO NOT YET FINALIZED automatically."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
