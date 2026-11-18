#!/usr/bin/env python
"""
run_demo_session_gated.py - DRY-RUN DEFAULT / DOES NOT EXECUTE (FASE 20)
==========================================================================
WARNINGS:
    - DRY-RUN BY DEFAULT. dry_run=False requires FOUR redundant flags:
        --execute-demo
        --confirm-demo-session
        --operator-token "..."
        --i-understand-this-is-demo
      AND the gate-level invariants (ModeGuard, ProviderRegistry,
      Safety, RiskEngine, plan freshness).
    - READINESS IS NOT AUTHORIZATION. is_ready_for_gated_demo=True is a
      SIGNAL only. This script does NOT promote any provider, does NOT
      load .env directly, does NOT send orders by default.
    - NO ORDER UNLESS EXPLICIT FLAGS. Without all redundant flags, the
      executor is invoked with dry_run=True (no network call).
    - ASCII-only output. No emojis. No PYTHONIOENCODING needed.

Examples (PREVIEW):
    python scripts/run_demo_session_gated.py --profile personal --capital 5000 \\
        --symbol BTCUSDT --entry 65000 --sl 64000 --tp 67000 --size 200

To attempt real demo (operator approval required separately):
    python scripts/run_demo_session_gated.py --profile personal --capital 5000 \\
        --symbol BTCUSDT --entry 65000 --sl 64000 --tp 67000 --size 200 \\
        --execute-demo --confirm-demo-session --operator-token "operator@example.com" \\
        --i-understand-this-is-demo

Exit:
    0 = preview/outcome computed without rejection.
    1 = invalid input or DemoSessionRejected/DemoSessionPlanRejected raised.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


_PROFILE_CHOICES = (
    "personal",
    "prop_challenge",
    "hyrotrader_demo_template",
    "custom",
)
_SIDE_CHOICES = ("buy", "sell")


def _banner() -> None:
    print()
    print("=" * 72)
    print("  DEMO SESSION GATED - DRY-RUN DEFAULT / DOES NOT EXECUTE")
    print("  READINESS IS NOT AUTHORIZATION. NO ORDER UNLESS EXPLICIT FLAGS.")
    print("  NO NETWORK CALL IN PREVIEW. NO PROVIDER PROMOTION.")
    print("=" * 72)
    print()


def _footer() -> None:
    print()
    print("=" * 72)
    print("  END. NO ORDER SENT unless executor was real AND all flags set.")
    print("=" * 72)


def _build_profile(name: str, capital: float):
    from crypto_trading_bot.operational_profile import (
        build_custom_profile,
        build_hyrotrader_demo_template,
        build_personal_profile,
        build_prop_challenge_profile,
    )
    if name == "personal":
        return build_personal_profile(account_size_usd=capital)
    if name == "prop_challenge":
        return build_prop_challenge_profile(account_size_usd=capital)
    if name == "hyrotrader_demo_template":
        return build_hyrotrader_demo_template(account_size_usd=capital)
    if name == "custom":
        return build_custom_profile(
            name="custom_demo_session",
            description="Custom profile via run_demo_session_gated.py",
            account_size_usd=capital,
        )
    raise ValueError("unknown profile")


class _DryExecutor:
    """
    Default executor used by the CLI when --execute-demo is NOT set.

    Simulates a clean dry-run response. NO network. NO secrets.
    Implements DemoExecutorProtocol via duck typing.
    """
    def execute(self, risk_result, dry_run=True):
        from types import SimpleNamespace

        ns = SimpleNamespace(
            success=True,
            operation="place_order",
            reason="dry-run: no order sent (CLI default executor)",
            dry_run=True,
            manual_review_required=False,
            safety_halt_recommended=False,
            reconciliation_confidence="canonical",
            trade=None,
        )
        ns.to_dict = lambda: {
            "success": True,
            "operation": "place_order",
            "reason": "dry-run: no order sent (CLI default executor)",
            "dry_run": True,
            "manual_review_required": False,
            "safety_halt_recommended": False,
            "reconciliation_confidence": "canonical",
        }
        return ns


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Demo Session Gated - DRY-RUN by default. No order is sent "
            "without four redundant flags AND all internal gates."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=True,
    )
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--symbol", type=str, required=True)
    parser.add_argument(
        "--side", type=str, default="buy", choices=_SIDE_CHOICES,
    )
    parser.add_argument("--entry", type=float, required=True)
    parser.add_argument("--sl", type=float, required=True)
    parser.add_argument("--tp", type=float, required=True)
    parser.add_argument("--size", type=float, required=True)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument(
        "--readiness-max-age-seconds", type=int, default=300,
    )
    # Triple-lock flags (all required for real demo execution)
    parser.add_argument("--execute-demo", action="store_true",
                        help="REQUIRED to attempt real demo execution.")
    parser.add_argument("--confirm-demo-session", action="store_true",
                        help="REQUIRED. Explicit operator confirmation.")
    parser.add_argument("--operator-token", type=str, default="",
                        help="REQUIRED. Operator identifier (sanitized).")
    parser.add_argument("--i-understand-this-is-demo", action="store_true",
                        help="REQUIRED. Operator acknowledges demo nature.")
    parser.add_argument("--notes", type=str, default="")

    args = parser.parse_args(argv)

    _banner()

    if args.capital <= 0:
        print("  ERROR --capital must be > 0")
        _footer()
        return 1

    # Build profile (lazy imports for testability)
    try:
        profile = _build_profile(args.profile, float(args.capital))
    except Exception as e:
        print(f"  ERROR profile construction failed: {type(e).__name__}")
        _footer()
        return 1

    # Build blueprint
    from crypto_trading_bot.demo_session_execution import (
        BlueprintSide,
        SignalBlueprint,
        build_demo_session_plan,
        execute_demo_session_gated,
        DemoSessionPlanRejected,
        DemoSessionRejected,
    )
    from crypto_trading_bot.demo_session_readiness import (
        DemoSessionReadinessCheck,
    )
    from crypto_trading_bot.operational_safety.safety_state_machine import (
        SafetyStateMachine,
    )

    try:
        blueprint = SignalBlueprint(
            symbol=args.symbol,
            side=BlueprintSide.BUY if args.side == "buy" else BlueprintSide.SELL,
            entry_price=float(args.entry),
            stop_loss=float(args.sl),
            take_profit=float(args.tp),
            position_size_usd=float(args.size),
            leverage=float(args.leverage),
        )
    except (ValueError, TypeError) as e:
        print(f"  ERROR blueprint validation: {type(e).__name__}: {e}")
        _footer()
        return 1

    # Readiness (FASE 19) - uses default singleton registry (read-only)
    safety = SafetyStateMachine()
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=args.symbol,
        capital=float(args.capital),
        safety_machine=safety,
    )
    report = check.evaluate()
    print(f"  Readiness ready: {report.is_ready_for_gated_demo}")
    print(f"  Blocking reasons: {len(report.blocking_reasons)}")
    if report.blocking_reasons:
        for r in report.blocking_reasons:
            print(f"    BLOCK {r}")
        _footer()
        return 1

    # Build plan
    from crypto_trading_bot.config.risk_config import RiskConfig
    try:
        plan = build_demo_session_plan(
            plan_id=str(uuid.uuid4()),
            readiness_report=report,
            profile=profile,
            blueprint=blueprint,
            effective_risk_config=RiskConfig(),
            readiness_max_age_seconds=int(args.readiness_max_age_seconds),
        )
    except DemoSessionPlanRejected as e:
        print(f"  PLAN REJECTED: {type(e).__name__}")
        _footer()
        return 1

    print(f"  Plan id: {plan.plan_id}")
    print(f"  Symbol: {plan.blueprint.symbol}  side: {plan.blueprint.side.value}")
    print(f"  Entry: {plan.blueprint.entry_price}  SL: {plan.blueprint.stop_loss}"
          f"  TP: {plan.blueprint.take_profit}")
    print(f"  position_size_usd: {plan.blueprint.position_size_usd}")

    # Decide dry_run
    real_demo = bool(
        args.execute_demo
        and args.confirm_demo_session
        and args.i_understand_this_is_demo
        and args.operator_token
    )
    dry_run = not real_demo
    print()
    print(f"  dry_run: {dry_run}")
    if real_demo:
        print("  REAL DEMO EXECUTION REQUESTED (all four flags present).")
        print("  Gates internos ainda devem aprovar. NO direct .env read here.")
    else:
        print("  No real execution requested. Using CLI default dry-run executor.")

    # Execute via gate. CLI never imports BybitDemoExecutor directly.
    # When real_demo=True, operator must wire an executor via separate
    # script + manual approval. This CLI uses a safe dry-run executor.
    if real_demo:
        print()
        print("  NOTE: This CLI does NOT instantiate a real BybitDemoExecutor.")
        print("  Real demo execution requires a separate operator-approved")
        print("  script that wires the executor with credentials. Exiting.")
        _footer()
        return 1

    executor = _DryExecutor()

    # ModeGuard + provider registry are required by the gate even in
    # dry-run. For preview we use a paper-mode guard (which blocks demo
    # at the ModeGuard layer). The CLI surfaces this rejection as a
    # visible message instead of crashing.
    from crypto_trading_bot.config.settings import Settings, TradingMode
    from crypto_trading_bot.core.mode_guard import ModeGuard
    from crypto_trading_bot.execution.provider_registry import get_registry
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    cli_settings = Settings(
        trading_mode=TradingMode.PAPER,
        enable_demo_execution=False,
        enable_live_trading=False,
        enable_testnet_execution=False,
    )
    cli_mode_guard = ModeGuard(cli_settings)

    try:
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=RiskEngine(initial_capital=float(args.capital)),
            demo_executor=executor,
            safety_machine=safety,
            mode_guard=cli_mode_guard,
            provider_registry=get_registry(),
            operator_token=(args.operator_token or "cli_preview_token"),
            confirm_demo_session=True,
            dry_run=True,  # CLI default executor is always dry-run
            notes=args.notes,
        )
    except DemoSessionRejected as e:
        print(f"  GATE REJECTED: {type(e).__name__}")
        _footer()
        # CLI default uses PAPER mode_guard which intentionally rejects
        # demo execution at the ModeGuard gate. This is the expected
        # SAFE behavior for preview. We report it and exit 0 because
        # the readiness/plan stages succeeded.
        return 0

    print()
    print(f"  Outcome reason: {outcome.outcome_reason}")
    print(f"  Recommended next: {outcome.recommended_next_action.value}")
    print(f"  is_filled_canonical: {outcome.is_filled_canonical}")
    print(f"  requires_manual_review: {outcome.requires_manual_review}")

    _footer()
    return 0


if __name__ == "__main__":
    sys.exit(main())
