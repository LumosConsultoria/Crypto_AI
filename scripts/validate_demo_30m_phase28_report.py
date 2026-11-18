#!/usr/bin/env python
"""
validate_demo_30m_phase28_report.py - FASE 28 closeout validator
====================================================================
ASCII-only. 100% OFFLINE. ZERO network. ZERO secret. NEVER sends order.

Aprova ou reprova um par de artefatos da sessao FASE 28 wired dry-run:
    1. --report <path>.json      (--output do CLI)
    2. --telemetry <path>.jsonl  (--telemetry-output do CLI; opcional)

Verifica:
    JSON report:
        - wired_dry_run == True
        - apply_demo_real_invoked == False
        - outcome.orders_submitted == 0
        - outcome.orders_filled == 0
        - outcome.open_positions_count == 0
        - outcome.safety_state == "normal"
        - outcome.manual_review_required == False
        - outcome.safety_halt_recommended == False
        - outcome.mode == "real_endurance"
        - readiness.status == "ready"

    Telemetry JSONL (quando fornecido):
        - tem event_type=session_start
        - tem event_type=preflight_done
        - tem event_type=session_end
        - NAO tem event_type=api_failure
        - NAO tem event_type=safety_event
        - se houver gate_invoked: snapshot.dry_run == True
        - nenhum token sensivel no payload

Exit codes:
    0 - aprovado
    1 - reprovado (com lista de violacoes)
    2 - arquivo invalido / IO error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


# Substrings sensiveis: aparicao em qualquer texto rejeita o relatorio.
_SECRET_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:", "origin_string",
)


def _load_json(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


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


def _check_no_secret_substrings(text: str, *, source: str) -> List[str]:
    issues: List[str] = []
    lower = text.lower()
    for tok in _SECRET_SUBSTRINGS:
        if tok in lower:
            issues.append(
                f"[{source}] suspicious token '{tok}' detected"
            )
    return issues


def _validate_report(
    data: dict, *, report_text: str,
) -> List[str]:
    issues: List[str] = []

    # Token-level secrets in full text
    issues.extend(_check_no_secret_substrings(
        report_text, source="report_text"
    ))

    if data.get("wired_dry_run") is not True:
        issues.append("wired_dry_run must be True")
    if data.get("apply_demo_real_invoked") is not False:
        issues.append("apply_demo_real_invoked must be False")

    outcome = data.get("outcome", {})
    if not isinstance(outcome, dict):
        issues.append("outcome missing or invalid")
        return issues

    if int(outcome.get("orders_submitted", 0)) != 0:
        issues.append(
            f"orders_submitted must be 0; got "
            f"{outcome.get('orders_submitted')}"
        )
    if int(outcome.get("orders_filled", 0)) != 0:
        issues.append(
            f"orders_filled must be 0; got "
            f"{outcome.get('orders_filled')}"
        )
    if int(outcome.get("open_positions_count", 0)) != 0:
        issues.append(
            "open_positions_count must be 0 in FASE 28"
        )
    if outcome.get("safety_state") != "normal":
        issues.append(
            f"safety_state must be 'normal'; got "
            f"{outcome.get('safety_state')}"
        )
    if outcome.get("manual_review_required") is not False:
        issues.append("manual_review_required must be False")
    if outcome.get("safety_halt_recommended") is not False:
        issues.append("safety_halt_recommended must be False")
    if outcome.get("mode") != "real_endurance":
        issues.append(
            f"outcome.mode must be 'real_endurance'; got "
            f"{outcome.get('mode')}"
        )

    readiness = data.get("readiness", {})
    if isinstance(readiness, dict):
        if readiness.get("status") != "ready":
            issues.append(
                f"readiness.status must be 'ready'; got "
                f"{readiness.get('status')}"
            )

    return issues


def _validate_telemetry(
    events: List[dict], *, telemetry_text: str,
) -> List[str]:
    issues: List[str] = []
    issues.extend(_check_no_secret_substrings(
        telemetry_text, source="telemetry_text"
    ))

    types_present = {
        e.get("event_type") for e in events if isinstance(e, dict)
    }
    for required in ("session_start", "preflight_done", "session_end"):
        if required not in types_present:
            issues.append(
                f"telemetry missing required event_type='{required}'"
            )
    if "api_failure" in types_present:
        issues.append(
            "telemetry contains api_failure event(s); investigate"
        )
    if "safety_event" in types_present:
        issues.append(
            "telemetry contains safety_event(s); investigate"
        )

    # gate_invoked, se presente, deve ter dry_run=True na FASE 28.
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get("event_type") != "gate_invoked":
            continue
        snapshot = e.get("snapshot") or {}
        if snapshot.get("dry_run") is not True:
            issues.append(
                "gate_invoked.dry_run must be True in FASE 28; "
                f"cycle_idx={e.get('cycle_idx')}"
            )

    return issues


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate FASE 28 wired dry-run report + telemetry. "
            "Offline; never sends order."
        ),
    )
    parser.add_argument(
        "--report", type=str, required=True,
        help="Path to JSON report produced by --output.",
    )
    parser.add_argument(
        "--telemetry", type=str, default="",
        help="Optional path to JSONL telemetry produced by "
             "--telemetry-output.",
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
        print(f"ERROR parsing report: {type(e).__name__}: {str(e)[:160]}")
        return 2

    issues = _validate_report(data, report_text=report_text)

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
        issues.extend(
            _validate_telemetry(events, telemetry_text=tel_text)
        )

    if issues:
        print("FASE 28 report validation FAILED:")
        for i in issues:
            print(f"  - {i}")
        return 1

    print("FASE 28 report validation OK.")
    print("  wired_dry_run=True")
    print("  apply_demo_real_invoked=False")
    print("  orders_submitted=0, orders_filled=0")
    print("  open_positions_count=0, safety_state=normal")
    print("  no manual_review_required, no safety_halt_recommended")
    if args.telemetry:
        print("  telemetry: session_start + preflight_done + "
              "session_end present")
        print("  telemetry: no api_failure, no safety_event")
        print("  telemetry: gate_invoked (if any) had dry_run=True")
    print("  no secrets detected in report/telemetry text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
