#!/usr/bin/env python
"""
run_operator_inputs.py - Operator Required Inputs (FASE 36 Bloco L)
====================================================================
ASCII-only. 100% OFFLINE. Gerencia os campos que o operador PRECISA
informar antes de demo real. NUNCA inventa valor.

Acoes:
    --list                       lista schema + status atual
    --set ID=VALOR               define valor (JSON p/ tipos)
    --confirm ID                 confirma valor (confirmacao humana)
    --report                     RequiredInputsForDemoReport
    --output PATH                grava report JSON

Exemplos:
    python scripts/run_operator_inputs.py --store config/operator_inputs.json --list
    python scripts/run_operator_inputs.py --store config/operator_inputs.json `
        --operator-token thiago_001 --set session_capital_usd=5000
    python scripts/run_operator_inputs.py --store config/operator_inputs.json `
        --operator-token thiago_001 --confirm demo_real_authorized
    python scripts/run_operator_inputs.py --store config/operator_inputs.json --report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Operator Required Inputs (FASE 36). Offline.",
    )
    parser.add_argument(
        "--store", type=str, default="config/operator_inputs.json",
    )
    parser.add_argument("--operator-token", type=str, default="")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--set", type=str, action="append", default=[],
        metavar="ID=VALOR",
    )
    parser.add_argument("--confirm", type=str, action="append",
                        default=[], metavar="ID")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args(argv)

    from crypto_trading_bot.operator_inputs import (
        OperatorInputStore,
        build_default_schema,
        build_required_inputs_for_demo_report,
        validate_operator_inputs,
    )

    print()
    print("=" * 72)
    print("  OPERATOR REQUIRED INPUTS (FASE 36) - OFFLINE")
    print("  Valores obrigatorios ausentes BLOQUEIAM demo real.")
    print("=" * 72)

    schema = build_default_schema()
    try:
        store = OperatorInputStore(args.store)
    except ValueError as e:
        print(f"  ERROR store: {e}")
        return 1

    if args.set or args.confirm:
        if not args.operator_token.strip():
            print("  ERROR --operator-token obrigatorio p/ set/confirm")
            return 1

    known_ids = {r.input_id for r in schema}
    for item in args.set:
        if "=" not in item:
            print(f"  ERROR formato invalido: {item!r} (use ID=VALOR)")
            return 1
        input_id, _, raw = item.partition("=")
        input_id = input_id.strip()
        if input_id not in known_ids:
            print(f"  ERROR input desconhecido: {input_id!r}")
            return 1
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            value = raw  # string simples
        store.set_value(
            input_id, value, operator_token=args.operator_token,
        )
        print(f"  SET {input_id} = {value!r}")

    for input_id in args.confirm:
        if input_id not in known_ids:
            print(f"  ERROR input desconhecido: {input_id!r}")
            return 1
        ok = store.confirm(
            input_id, operator_token=args.operator_token,
        )
        print(
            f"  CONFIRM {input_id}: "
            + ("ok" if ok else "FALHOU (valor ausente)")
        )

    if args.list:
        result = validate_operator_inputs(schema=schema, store=store)
        print()
        print(f"  {'input_id':38} {'status':20} req? label")
        print("  " + "-" * 68)
        for req in schema:
            status = result.statuses.get(req.input_id, "?")
            flag = "SIM" if req.required_for_demo else "nao"
            print(
                f"  {req.input_id:38} {status:20} {flag:4} "
                f"{req.label[:30]}"
            )

    if args.report or args.output:
        report = build_required_inputs_for_demo_report(
            schema=schema, store=store,
        )
        print()
        print(f"  blocks_readiness:  {report['blocks_readiness']}")
        print(f"  blocks_execution:  {report['blocks_execution']}")
        print(f"  missing:           {len(report['missing'])}")
        for m in report["missing"][:15]:
            print(
                f"    - {m['input_id']}: {m['status']} "
                f"({m['reason'][:50]})"
            )
        if args.output:
            out = Path(args.output)
            if any(p == ".." for p in out.parts):
                print("  ERROR --output contem '..'")
                return 1
            text = json.dumps(
                report, indent=2, sort_keys=True, default=str,
            )
            if any(t in text.lower() for t in _SECRET_TOKENS):
                print("  ERROR token suspeito no report; nao gravado")
                return 1
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            print(f"  Report written to: {args.output}")

    print()
    print("=" * 72)
    print("  END.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
