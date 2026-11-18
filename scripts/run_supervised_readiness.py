#!/usr/bin/env python
"""
run_supervised_readiness.py - Readiness supervisionado (FASE 35)
=================================================================
ASCII-only. 100% OFFLINE: le apenas reports JSON locais. ZERO rede,
ZERO ordem, ZERO secret.

Consolida evidencias de demos curtas/longas, advisor, IA e prediction
markets e produz verdict CONSULTIVO:
    ready | not_ready | manual_review_required | insufficient_history

'ready' NAO habilita live/mainnet: decisao final e humana,
supervisionada e com gates proprios em fase futura.

Exemplo:
    python scripts/run_supervised_readiness.py `
        --profile personal `
        --reports-dir reports `
        --output reports/supervised_readiness_YYYYMMDD.json

Exit codes: 0 ready | 1 not_ready/insufficient | 2 manual_review.
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
    "authorization:", "origin_string",
)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Supervised readiness (FASE 35). Consultivo/offline; "
            "nunca habilita live/mainnet."
        ),
    )
    parser.add_argument("--profile", type=str, default="personal")
    parser.add_argument(
        "--capital", type=float, default=5000.0,
        help="Capital para resolver o perfil (metadata).",
    )
    parser.add_argument("--reports-dir", type=str, required=True)
    parser.add_argument("--output", type=str, default="")
    args = parser.parse_args(argv)

    print()
    print("=" * 72)
    print("  SUPERVISED READINESS (FASE 35) - OFFLINE/CONSULTIVO")
    print("  'ready' NAO habilita live/mainnet.")
    print("=" * 72)
    print()

    reports_dir = Path(args.reports_dir)
    if any(p == ".." for p in reports_dir.parts):
        print("  ERROR --reports-dir contains '..' (rejected)")
        return 1
    if not reports_dir.is_dir():
        print(f"  ERROR reports dir not found: {args.reports_dir}")
        return 1

    from crypto_trading_bot.operational_profile import resolve_profile
    from crypto_trading_bot.readiness import (
        run_supervised_readiness_from_dir,
    )

    profile = None
    try:
        profile = resolve_profile(args.profile, capital=args.capital)
    except ValueError as e:
        print(f"  WARN profile nao resolvido: {str(e)[:120]}")

    report = run_supervised_readiness_from_dir(
        reports_dir=str(reports_dir),
        profile=profile,
        profile_name=args.profile,
    )

    print(report.human_summary())

    _maybe_write_output(args.output, report.to_dict())

    print()
    print("=" * 72)
    print("  END.")
    print("=" * 72)

    if report.verdict.value == "ready":
        return 0
    if report.verdict.value == "manual_review_required":
        return 2
    return 1


def _maybe_write_output(path: str, payload: dict) -> None:
    if not path:
        return
    out_path = Path(path)
    if any(p == ".." for p in out_path.parts):
        print("  ERROR --output path contains '..' (rejected)")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    lower = text.lower()
    for tok in _SECRET_TOKENS:
        if tok in lower:
            print(
                "  ERROR refusing to write output: suspicious token found"
            )
            return
    out_path.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    sys.exit(main())
