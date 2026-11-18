#!/usr/bin/env python
"""
run_demo_30_min_planned.py - Demo 30 Min PLANNED/DRY-RUN (FASE 26)
======================================================================
ASCII-only. PLANNED-ONLY. NO network. NO real order. NO real API.

This CLI generates a PLANNED Demo30MinPlan + runs an OFFLINE
Demo30MinDryRunSimulator. It does NOT send any demo order. It does
NOT call Bybit. It does NOT read .env.

For real demo execution, use:
    scripts/run_bybit_demo_session_gated.py (Comando A + Comando B)
    (FASE 22 runbook).

The --apply-demo-real flag is a STUB in FASE 26: prints an error
message and exits without any effect. Real demo endurance loop is
deferred to FASE 27 (after explicit operator approval).

Exit codes:
    0  PLANNED dry-run OK; or --apply-demo-real stub printed safely.
    1  invalid input / readiness blocked / plan rejected.
    2  outcome failed / manual_review / safety_halt (reserved future).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


_PROFILE_CHOICES = (
    "personal", "prop_challenge", "hyrotrader_demo_template", "custom",
)
_STRATEGY_CHOICES = ("trend_pullback", "volatility_breakout")
_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:", "origin_string",
)


def _banner() -> None:
    print()
    print("=" * 72)
    print("  DEMO 30 MIN - PLANNED / DRY-RUN ONLY (FASE 26)")
    print("  NO network. NO real API. NO real order. NO secret.")
    print("  For real demo: scripts/run_bybit_demo_session_gated.py")
    print("                 (Comando A + Comando B, FASE 22 runbook).")
    print("=" * 72)
    print()


def _footer() -> None:
    print()
    print("=" * 72)
    print("  END.")
    print("=" * 72)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Demo 30 Min PLANNED/DRY-RUN runner (FASE 26). "
            "Generates plan + offline simulation. NO real order."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=True,
    )
    parser.add_argument(
        "--capital", type=float, required=True,
        help="account_size_usd in USD. Required.",
    )
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument(
        "--strategy", type=str, default="trend_pullback",
        choices=_STRATEGY_CHOICES,
    )
    parser.add_argument(
        "--max-orders", type=int, default=1,
        help="Hard cap = 1 in FASE 26.",
    )
    parser.add_argument(
        "--max-minutes", type=int, default=30,
        help="Hard cap = 30 in FASE 26.",
    )
    parser.add_argument(
        "--operator-token", type=str, required=True,
        help="Operator token (always sanitized in outputs).",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Optional JSON output path (sanitized).",
    )
    parser.add_argument(
        "--from-blueprint", type=str, default="",
        help=(
            "Optional local JSON file path with PlannedDemoBlueprint. "
            "Local-only; no network. If absent, CLI generates a "
            "default planned fixture clearly marked as planned-only."
        ),
    )
    parser.add_argument(
        "--apply-demo-real", action="store_true",
        help=(
            "STUB in FASE 26. Prints error and exits without effect. "
            "Real demo execution requires FASE 27."
        ),
    )
    parser.add_argument(
        "--yes", action="store_true",
        help=(
            "(test-only) Skip interactive prompt; default behavior "
            "requires typing Y interactively."
        ),
    )
    args = parser.parse_args(argv)

    _banner()

    # --- apply-demo-real STUB ---
    if args.apply_demo_real:
        print(
            "  ERROR --apply-demo-real is a STUB in FASE 26. "
            "Real execution requires FASE 27. Use FASE 22 runbook "
            "for real demo (scripts/run_bybit_demo_session_gated.py)."
        )
        _footer()
        return 0

    # --- basic input validation ---
    if args.capital <= 0:
        print("  ERROR --capital must be > 0")
        _footer()
        return 1
    if not args.symbol.strip():
        print("  ERROR --symbol cannot be empty")
        _footer()
        return 1
    if not args.operator_token.strip():
        print("  ERROR --operator-token must be non-empty")
        _footer()
        return 1
    if args.max_orders <= 0:
        print("  ERROR --max-orders must be >= 1")
        _footer()
        return 1
    if args.max_minutes <= 0:
        print("  ERROR --max-minutes must be >= 1")
        _footer()
        return 1

    # --- imports lazy (avoid heavy at parse time) ---
    from crypto_trading_bot.demo_endurance import (
        build_default_planned_blueprint,
        build_demo_30_min_plan,
        build_demo_30_min_readiness_report,
        DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
        DEMO_30_MIN_MAX_SESSION_MINUTES,
        DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
        DEMO_30_MIN_PLANNED_ENVIRONMENT,
        DEMO_30_MIN_PLANNED_PROVIDER_ID,
        Demo30MinDryRunSimulator,
        Demo30MinPlanRejected,
        Demo30MinReadinessConfig,
        EnvironmentSnapshot,
        LastSafetyFlags,
        PlannedDemoBlueprint,
        PlannedDemoBlueprintRejected,
        to_ui_snapshot,
    )

    # --- planned blueprint source ---
    if args.from_blueprint.strip():
        try:
            blueprint = _load_planned_blueprint_from_file(
                args.from_blueprint, PlannedDemoBlueprint,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"  ERROR loading --from-blueprint: {type(e).__name__}: "
                f"{str(e)[:200]}"
            )
            _footer()
            return 1
    else:
        # Default fixture - planned only.
        blueprint = build_default_planned_blueprint(
            symbol=args.symbol,
            wallet_balance_usd=float(args.capital),
        )

    print(
        "  NOTE Blueprint used in FASE 26 is planned/offline and not "
        "execution-ready."
    )
    print(
        "       Real fresh API blueprint remains FASE 22 Comando A or "
        "future FASE 27."
    )
    print()
    print(f"  Profile:        {args.profile}")
    print(f"  Capital (USD):  {args.capital}")
    print(f"  Symbol:         {args.symbol}")
    print(f"  Strategy:       {args.strategy}")
    print(f"  Max orders:     {args.max_orders} "
          f"(hard cap {DEMO_30_MIN_MAX_ORDERS_HARD_CAP})")
    print(f"  Max minutes:    {args.max_minutes} "
          f"(hard cap {DEMO_30_MIN_MAX_SESSION_MINUTES})")
    print()

    # --- readiness (offline; snapshot is a SAFE PLANNED default) ---
    env_snap = EnvironmentSnapshot(
        enable_live_trading=False,
        enable_demo_execution=False,
        trading_mode="paper",
        provider_id=DEMO_30_MIN_PLANNED_PROVIDER_ID,
        provider_status="opt_in",
        endpoint_type=DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
        credentials_present=False,
        environment=DEMO_30_MIN_PLANNED_ENVIRONMENT,
    )
    last_flags = LastSafetyFlags()  # default clean

    readiness_cfg = Demo30MinReadinessConfig(
        symbol=args.symbol,
        strategy_name=args.strategy,
        capital_usd=float(args.capital),
        max_orders=int(args.max_orders),
        max_session_minutes=int(args.max_minutes),
        max_trades_per_day=10,  # snapshot generic; CLI does not read RiskConfig env
        operator_token=args.operator_token,
        environment_snapshot=env_snap,
        last_safety_flags=last_flags,
        planned_blueprint=blueprint,
    )
    readiness = build_demo_30_min_readiness_report(readiness_cfg)

    print(f"  Readiness:      {readiness.status.value}")
    print(f"  Blockers:       {readiness.total_blockers}")
    print(f"  Warnings:       {readiness.total_warnings}")
    if readiness.blockers:
        for i in readiness.blockers:
            print(f"    [BLOCKER] {i.gate}: {i.message}")
    if readiness.warnings:
        for i in readiness.warnings:
            print(f"    [WARNING] {i.gate}: {i.message}")
    print()

    if not readiness.is_ready:
        print("  READINESS NOT_READY: plan NOT generated.")
        _footer()
        return 1

    # --- build plan ---
    try:
        plan = build_demo_30_min_plan(
            symbol=args.symbol,
            strategy_name=args.strategy,
            max_orders=int(args.max_orders),
            max_session_minutes=int(args.max_minutes),
            risk_thresholds_snapshot={
                "max_daily_loss_pct": 0.05,
                "max_total_loss_pct": 0.10,
                "max_trades_per_day": 10,
            },
            planned_blueprint=blueprint,
            operator_token=args.operator_token,
        )
    except (Demo30MinPlanRejected, ValueError, TypeError) as e:
        print(f"  ERROR plan build failed: {type(e).__name__}: {str(e)[:200]}")
        _footer()
        return 1

    print(f"  session_id:     {plan.session_id}")
    print(f"  token (san):    {plan.operator_token_sanitized}")
    print()

    # --- prompt Y (manual; --yes for tests only) ---
    if not args.yes:
        try:
            ans = input(
                "  Type Y to confirm dry-run plan "
                "(NO real order will be sent): "
            ).strip()
        except EOFError:
            ans = ""
        if ans != "Y":
            print()
            print("  Confirmation declined. Plan aborted. No effect.")
            _footer()
            return 1

    # --- dry-run simulator ---
    sim = Demo30MinDryRunSimulator(plan)
    outcome = sim.simulate()

    snap = to_ui_snapshot(plan=plan, outcome=outcome, readiness=readiness)
    print()
    print("  Demo30Min UI snapshot:")
    print(f"    stage:                    {snap['stage_info']['stage']}")
    print(f"    mode:                     {snap['stage_info']['mode']}")
    print(f"    provider:                 {snap['stage_info']['provider']}")
    print(f"    environment:              "
          f"{snap['stage_info']['environment']}")
    print(f"    endpoint_type:            "
          f"{snap['stage_info']['endpoint_type']}")
    print(f"    symbol:                   {snap['stage_info']['symbol']}")
    print(f"    strategy_name:            "
          f"{snap['stage_info']['strategy_name']}")
    print(f"    session_id:               "
          f"{snap['stage_info']['session_id']}")
    print(f"    max_session_minutes:      "
          f"{snap['plan']['max_session_minutes']}")
    print(f"    max_orders:               {snap['plan']['max_orders']}")
    print(f"    cycles_completed:         "
          f"{snap['session']['cycles_completed']}")
    print(f"    orders_planned:           "
          f"{snap['session']['orders_planned']}")
    print(f"    orders_submitted:         "
          f"{snap['session']['orders_submitted']}")
    print(f"    orders_filled:            "
          f"{snap['session']['orders_filled']}")
    print(f"    open_positions_count:     "
          f"{snap['session']['open_positions_count']}")
    print(f"    safety_state:             {snap['safety']['safety_state']}")
    print(f"    verdict:                  "
          f"{snap['verdict']['verdict']}")
    print(f"    recommended_next_action:  "
          f"{snap['verdict']['recommended_next_action']}")
    print(f"    outcome_reason:           "
          f"{snap['verdict']['outcome_reason']}")
    print()
    print(
        "  PLANNED DRY-RUN COMPLETE. No real demo order was sent. "
        "To send real demo orders, use scripts/"
        "run_bybit_demo_session_gated.py Comando A + Comando B "
        "(FASE 22 runbook)."
    )

    _maybe_write_output(args.output, {
        "readiness": readiness.to_dict(),
        "plan": plan.to_dict(),
        "outcome": outcome.to_dict(),
        "ui_snapshot": snap,
    })

    _footer()

    # Exit code policy
    if outcome.verdict.value == "planned_dry_run_ok":
        return 0
    if outcome.verdict.value in (
        "manual_review_required", "safety_halt_ack_needed", "failed",
    ):
        return 2
    return 1


def _load_planned_blueprint_from_file(path: str, blueprint_cls):
    """Le PlannedDemoBlueprint local de JSON. NAO chama rede."""
    p = Path(path)
    if any(part == ".." for part in p.parts):
        raise ValueError("path contains '..' (rejected)")
    if not p.is_file():
        raise FileNotFoundError(f"blueprint file not found: {path}")
    text = p.read_text(encoding="utf-8")
    # Defensive: rejeita tokens suspeitos no arquivo de blueprint.
    lower = text.lower()
    for tok in _SECRET_TOKENS:
        if tok in lower:
            raise ValueError("blueprint file contains suspicious token")
    data = json.loads(text)
    # Reconstroi blueprint via campos canonicos.
    from datetime import datetime, timezone
    if "generated_at" in data and isinstance(data["generated_at"], str):
        ts = data["generated_at"]
        try:
            generated = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            generated = datetime.now(timezone.utc)
    else:
        generated = datetime.now(timezone.utc)
    # Permite override silencioso de fields nao expostos via metadata.
    keys = (
        "side", "entry_price", "stop_loss", "take_profit",
        "qty", "notional_usd", "risk_pct", "wallet_balance_usd",
        "open_positions_count", "open_orders_count",
        "conditional_orders_count", "endpoint_type", "provider_id",
        "environment", "schema_version", "ttl_seconds",
    )
    kwargs = {k: data[k] for k in keys if k in data}
    return blueprint_cls(generated_at=generated, **kwargs)


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
            print("  ERROR refusing to write output: suspicious token found")
            return
    out_path.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    sys.exit(main())
