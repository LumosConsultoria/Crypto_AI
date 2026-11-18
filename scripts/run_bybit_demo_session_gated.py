#!/usr/bin/env python
"""
run_bybit_demo_session_gated.py - OPERATOR WIRING / FASE 21
==============================================================
BYBIT DEMO SESSION GATED - real demo execution is OFF by default.

WARNINGS:
    - DRY-RUN DEFAULT. Without four CLI flags + final interactive
      confirmation + valid demo environment, this script never
      instantiates BybitClient or BybitDemoExecutor.
    - READINESS IS NOT AUTHORIZATION. is_ready_for_gated_demo=True is
      a SIGNAL only. The 10 gates inside execute_demo_session_gated
      remain the canonical invariants.
    - NO ORDER UNLESS EXPLICIT FLAGS. Real demo execution requires ALL:
        1. --execute-demo
        2. --confirm-demo-session
        3. --operator-token "..."
        4. --i-understand-this-is-demo
        plus an interactive Y prompt confirmation (or --non-interactive-assume-no
        to force dry-run in CI).
      AND the gate-internal verifications (ModeGuard, ProviderRegistry,
      Safety, RiskEngine, plan freshness).
    - ASCII-only. No emojis. No .env printing. No secret printing.
    - NEVER prints api_key/api_secret/Bearer/X-BAPI-SIGN/signature.
    - operator_token is shown TRUNCATED (8 chars + "...") in audit only.

Exit codes:
    0 = dry-run preview OK, or real canonical fill without issues.
    1 = invalid input, plan/gate rejection, missing demo config or
        credentials, abort before execution.
    2 = outcome requires manual review or safety halt acknowledgement.

Examples (PREVIEW with placeholders - manual values for dry-run only):
    # <PLACEHOLDER> values - never use these in real demo execution.
    python scripts/run_bybit_demo_session_gated.py \
        --profile personal --capital <PLACEHOLDER_CAPITAL> \
        --symbol BTCUSDT --side buy \
        --entry <PLACEHOLDER_ENTRY> --sl <PLACEHOLDER_SL> \
        --tp <PLACEHOLDER_TP> --size <PLACEHOLDER_SIZE>

FASE 22: Real demo execution now requires an API-driven blueprint.
    Manual --entry/--sl/--tp/--size are REJECTED in the real path.

Step 1: Prepare blueprint via preflight (read-only, no order sent):
    python scripts/run_bybit_demo_session_gated.py \
        --prepare-demo-blueprint \
        --output blueprint.json \
        --profile personal --capital <CAPITAL> \
        --symbol BTCUSDT --side buy

Step 2: Execute from fresh blueprint (within TTL, default 60s):
    python scripts/run_bybit_demo_session_gated.py \
        --from-blueprint blueprint.json \
        --execute-demo --confirm-demo-session \
        --operator-token "operator@example.com" \
        --i-understand-this-is-demo
"""

from __future__ import annotations

import argparse
import sys
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


_PROFILE_CHOICES = (
    "personal",
    "prop_challenge",
    "hyrotrader_demo_template",
    "custom",
)
_SIDE_CHOICES = ("buy", "sell")

# Exit code contract (documented in runbook)
EXIT_OK = 0
EXIT_REJECTED_OR_INVALID = 1
EXIT_MANUAL_REVIEW_OR_HALT = 2


# ---------------------------------------------------------------------------
# Banner / footer (ASCII-only)
# ---------------------------------------------------------------------------

def _banner() -> None:
    print()
    print("=" * 72)
    print("  BYBIT DEMO SESSION GATED - OPERATOR WIRING (FASE 21)")
    print("  DRY-RUN DEFAULT / DOES NOT EXECUTE WITHOUT FLAGS + PROMPT")
    print("  READINESS IS NOT AUTHORIZATION. NO ORDER UNLESS EXPLICIT FLAGS.")
    print("=" * 72)
    print()


def _footer(*, real_attempted: bool) -> None:
    print()
    print("=" * 72)
    if real_attempted:
        print("  END. Real demo path attempted. Review outcome above.")
        print("  Operator must check Bybit Demo UI for residual position/orders.")
    else:
        print("  END. DRY-RUN PATH. No real order was sent.")
    print("=" * 72)


# ---------------------------------------------------------------------------
# Dry-run fake executor (mirrors FASE 20 CLI default)
# ---------------------------------------------------------------------------

class _DryExecutor:
    """Default safe executor. Implements DemoExecutorProtocol via duck typing.

    Never touches the network. Never imports BybitClient.
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


# ---------------------------------------------------------------------------
# Profile builder
# ---------------------------------------------------------------------------

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
            description="Custom profile via run_bybit_demo_session_gated.py",
            account_size_usd=capital,
        )
    raise ValueError("unknown profile")


# ---------------------------------------------------------------------------
# Flag computation
# ---------------------------------------------------------------------------

def _compute_real_demo_requested(args) -> bool:
    """All four CLI flags must be present and operator_token non-empty.

    The interactive prompt confirmation is checked separately later.
    """
    return bool(
        getattr(args, "execute_demo", False)
        and getattr(args, "confirm_demo_session", False)
        and getattr(args, "i_understand_this_is_demo", False)
        and isinstance(getattr(args, "operator_token", ""), str)
        and args.operator_token.strip()
    )


# ---------------------------------------------------------------------------
# Interactive prompt with timeout (cross-platform, testable)
# ---------------------------------------------------------------------------

def _prompt_yes_or_default(
    *,
    timeout_seconds: float,
    input_fn: Optional[Callable[[str], str]] = None,
    isatty_fn: Optional[Callable[[], bool]] = None,
) -> bool:
    """Returns True only if the operator types exactly 'Y' (uppercase or
    lowercase) within the timeout. Otherwise False.

    Any of: non-TTY, timeout, empty input, exception, value other than Y -> False.

    input_fn / isatty_fn are injectable for testability.
    """
    isatty = isatty_fn if isatty_fn is not None else sys.stdin.isatty
    try:
        if not isatty():
            return False
    except Exception:
        return False

    inp = input_fn if input_fn is not None else input

    result: dict = {"value": None, "exc": None}
    done = threading.Event()

    def _worker():
        try:
            result["value"] = inp(
                "  Type 'Y' to confirm real demo execution: "
            )
        except Exception as e:  # noqa: BLE001
            result["exc"] = e
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    done.wait(timeout=max(0.0, float(timeout_seconds)))
    if not done.is_set():
        return False
    if result["exc"] is not None:
        return False
    answer = result["value"]
    if not isinstance(answer, str):
        return False
    answer = answer.strip()
    return answer == "Y" or answer == "y"


# ---------------------------------------------------------------------------
# Real executor wiring (called ONLY when all gates true)
# ---------------------------------------------------------------------------

def _build_real_demo_executor(
    args,
    *,
    capital: Optional[float] = None,
    settings_factory: Optional[Callable[[], object]] = None,
    exchange_config_factory: Optional[Callable[[], object]] = None,
    bybit_client_factory: Optional[Callable[..., object]] = None,
    mode_guard_factory: Optional[Callable[..., object]] = None,
    risk_engine_factory: Optional[Callable[..., object]] = None,
    bybit_demo_executor_factory: Optional[Callable[..., object]] = None,
    prompt_fn: Optional[Callable[..., bool]] = None,
):
    """Instantiate BybitDemoExecutor for real demo. Returns (executor, reason).

    Returns (None, reason_str) for any safe-abort path. reason is sanitized.

    Factories are injectable for testability. Defaults are the real
    production classes - tests inject mocks to avoid any network I/O.

    FASE 22.3: `capital` is an explicit kwarg. When --from-blueprint is
    used, args.capital may be None; caller passes the capital derived
    from the blueprint's proposal. Falls back to args.capital only when
    capital kwarg is omitted (legacy/preview paths).
    """
    from decimal import Decimal

    if settings_factory is None:
        from crypto_trading_bot.config.settings import Settings
        settings_factory = Settings
    if exchange_config_factory is None:
        from crypto_trading_bot.config.exchange_config import ExchangeConfig
        exchange_config_factory = ExchangeConfig
    if bybit_client_factory is None:
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        bybit_client_factory = BybitClient
    if mode_guard_factory is None:
        from crypto_trading_bot.core.mode_guard import ModeGuard
        mode_guard_factory = ModeGuard
    if risk_engine_factory is None:
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        risk_engine_factory = RiskEngine
    if bybit_demo_executor_factory is None:
        from crypto_trading_bot.execution.bybit_demo_executor import (
            BybitDemoExecutor,
        )
        bybit_demo_executor_factory = BybitDemoExecutor
    if prompt_fn is None:
        prompt_fn = _prompt_yes_or_default

    # Load Settings (pydantic-settings reads .env). We NEVER print contents.
    try:
        settings = settings_factory()
    except Exception as e:  # noqa: BLE001
        return None, f"settings_load_failed:{type(e).__name__}"

    # Check trading mode
    try:
        from crypto_trading_bot.config.settings import TradingMode
        if getattr(settings, "trading_mode", None) is not TradingMode.DEMO:
            return None, "trading_mode_not_demo"
        if not bool(getattr(settings, "enable_demo_execution", False)):
            return None, "enable_demo_execution_false"
    except Exception as e:  # noqa: BLE001
        return None, f"settings_check_failed:{type(e).__name__}"

    # Load ExchangeConfig for credentials. SecretStr - never printed.
    try:
        exchange_cfg = exchange_config_factory()
    except Exception as e:  # noqa: BLE001
        return None, f"exchange_config_load_failed:{type(e).__name__}"

    api_key_secret = getattr(exchange_cfg, "api_key", None)
    api_secret_secret = getattr(exchange_cfg, "api_secret", None)
    if api_key_secret is None or api_secret_secret is None:
        return None, "demo_credentials_missing"

    # Extract values to plain strings ONLY for BybitClient ctor.
    # NEVER print these.
    try:
        api_key_value = (
            api_key_secret.get_secret_value()
            if hasattr(api_key_secret, "get_secret_value")
            else str(api_key_secret)
        )
        api_secret_value = (
            api_secret_secret.get_secret_value()
            if hasattr(api_secret_secret, "get_secret_value")
            else str(api_secret_secret)
        )
    except Exception:  # noqa: BLE001
        return None, "demo_credentials_extract_failed"

    if not api_key_value.strip() or not api_secret_value.strip():
        return None, "demo_credentials_empty"

    # Interactive prompt with timeout.
    try:
        confirmed = prompt_fn(
            timeout_seconds=float(getattr(args, "prompt_timeout_seconds", 60.0)),
        )
    except Exception:  # noqa: BLE001
        return None, "prompt_failure"
    if not confirmed:
        return None, "prompt_declined_or_timeout"

    # Build BybitClient (environment must be "demo").
    try:
        client = bybit_client_factory(
            api_key=api_key_value,
            api_secret=api_secret_value,
            environment="demo",
        )
    except Exception as e:  # noqa: BLE001
        return None, f"bybit_client_init_failed:{type(e).__name__}"

    if getattr(client, "environment", None) != "demo":
        return None, "bybit_client_environment_not_demo"
    if not getattr(client, "has_credentials", False):
        return None, "bybit_client_missing_credentials"

    # Build ModeGuard + RiskEngine + BybitDemoExecutor.
    try:
        mode_guard = mode_guard_factory(settings)
    except Exception as e:  # noqa: BLE001
        return None, f"mode_guard_init_failed:{type(e).__name__}"
    # FASE 22.3: resolve capital from explicit kwarg first, then args.
    # When --from-blueprint is used, args.capital is None and the caller
    # MUST pass capital from the blueprint's proposal.capital. Without
    # that, RiskEngine init fails with TypeError (float(None)).
    capital_value: Optional[float] = None
    if capital is not None:
        capital_value = float(capital)
    elif getattr(args, "capital", None) is not None:
        capital_value = float(args.capital)
    if capital_value is None or capital_value <= 0:
        return None, "capital_missing_or_invalid"

    try:
        risk_engine = risk_engine_factory(initial_capital=capital_value)
    except Exception as e:  # noqa: BLE001
        # FASE 22.3: surface type + sanitized message (truncated, no secrets).
        msg_safe = str(e)[:200] if str(e) else ""
        return None, f"risk_engine_init_failed:{type(e).__name__}:{msg_safe}"
    try:
        executor = bybit_demo_executor_factory(
            client=client,
            mode_guard=mode_guard,
            risk_engine=risk_engine,
            confirm_demo_execution=True,
            qty_step=Decimal(str(args.qty_step)),
        )
    except Exception as e:  # noqa: BLE001
        return None, f"bybit_demo_executor_init_failed:{type(e).__name__}"

    return executor, "ok"


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bybit Demo Session Gated. DRY-RUN by default. Real demo "
            "execution requires four CLI flags + interactive prompt + "
            "valid demo environment AND all internal gates. "
            "FASE 22: real path requires --from-blueprint."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=False,
        default="personal",
    )
    parser.add_argument("--capital", type=float, required=False, default=None)
    parser.add_argument("--symbol", type=str, required=False, default=None)
    parser.add_argument(
        "--side", type=str, default="buy", choices=_SIDE_CHOICES,
    )
    parser.add_argument("--entry", type=float, required=False, default=None)
    parser.add_argument("--sl", type=float, required=False, default=None)
    parser.add_argument("--tp", type=float, required=False, default=None)
    parser.add_argument("--size", type=float, required=False, default=None)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--qty-step", type=str, default="0.001")
    parser.add_argument(
        "--readiness-max-age-seconds", type=int, default=300,
    )
    # Four CLI flags for real execution
    parser.add_argument("--execute-demo", action="store_true")
    parser.add_argument("--confirm-demo-session", action="store_true")
    parser.add_argument("--operator-token", type=str, default="")
    parser.add_argument("--i-understand-this-is-demo", action="store_true")
    # Operational safety / testability
    parser.add_argument("--prompt-timeout-seconds", type=float, default=60.0)
    parser.add_argument(
        "--non-interactive-assume-no", action="store_true",
        help="In CI/non-TTY: force dry-run (do NOT prompt).",
    )
    parser.add_argument("--notes", type=str, default="")
    # FASE 22 modes
    parser.add_argument(
        "--prepare-demo-blueprint", action="store_true",
        help=(
            "Mode: run BybitDemoPreflight (read-only) and save "
            "DemoApiBlueprint JSON to --output. No order sent."
        ),
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Path to write blueprint JSON (used with --prepare-demo-blueprint).",
    )
    parser.add_argument(
        "--from-blueprint", type=str, default="",
        help=(
            "Path to a fresh DemoApiBlueprint JSON. Required for real "
            "demo execution (FASE 22)."
        ),
    )
    parser.add_argument(
        "--blueprint-ttl-seconds", type=int, default=60,
        help="Max age for --from-blueprint (default 60s).",
    )
    parser.add_argument(
        "--max-spread-pct", type=float, default=0.10,
        help="Max spread%% for --prepare-demo-blueprint (default 0.10%%).",
    )
    parser.add_argument(
        "--accept-leverage-manual-confirmation", action="store_true",
        help=(
            "Allow blueprint when leverage_confirmable=False "
            "(operator promises to verify leverage manually)."
        ),
    )
    # FASE 22.1 - TP via risk-reward ratio (RR). Default conservador 2.0.
    # TP = entry +/- (entry - SL) * RR (sign by side), aligned to tick.
    parser.add_argument(
        "--take-profit-rr", type=float, default=None,
        help=(
            "Risk-reward ratio for TP in --prepare-demo-blueprint. "
            "Default: editable preflight constant DEFAULT_TAKE_PROFIT_RR=2.0. "
            "Conservative/editable; not a strategy rule. "
            "Pass 0 or negative to skip TP (NOT recommended for real demo)."
        ),
    )
    return parser.parse_args(argv)


def _real_path_requested(args) -> bool:
    """True iff any of the four real-execution CLI flags are set."""
    return bool(
        args.execute_demo
        or args.confirm_demo_session
        or args.i_understand_this_is_demo
        or (isinstance(args.operator_token, str) and args.operator_token.strip())
    )


def _has_manual_values(args) -> bool:
    """True iff operator supplied entry/sl/tp/size via CLI."""
    return any(
        v is not None for v in (args.entry, args.sl, args.tp, args.size)
    )


def _mode_prepare_blueprint(args) -> int:
    """FASE 22: produce DemoApiBlueprint JSON via BybitDemoPreflight."""
    from decimal import Decimal

    from crypto_trading_bot.config.exchange_config import ExchangeConfig
    from crypto_trading_bot.config.settings import Settings, TradingMode
    from crypto_trading_bot.core.mode_guard import ModeGuard
    from crypto_trading_bot.demo_session_execution import (
        DEFAULT_TAKE_PROFIT_RR,
        DemoApiBlueprintRejected,
        build_demo_api_blueprint,
        serialize_to_json,
    )
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    from crypto_trading_bot.execution.bybit_demo_preflight import (
        BybitDemoPreflight,
    )
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    if not args.output.strip():
        print("  ERROR --output is required with --prepare-demo-blueprint")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    if args.capital is None or args.capital <= 0:
        print("  ERROR --capital must be > 0 for --prepare-demo-blueprint")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    if not args.symbol or not args.symbol.strip():
        print("  ERROR --symbol is required")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    print("  Mode: PREPARE BLUEPRINT (read-only preflight, no order sent)")
    try:
        settings = Settings()
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR settings load: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    if getattr(settings, "trading_mode", None) is not TradingMode.DEMO:
        print("  ERROR trading_mode is not 'demo' in .env")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    if not bool(getattr(settings, "enable_demo_execution", False)):
        print("  ERROR enable_demo_execution=false in .env")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    try:
        exchange_cfg = ExchangeConfig()
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR exchange_config load: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    api_key_secret = getattr(exchange_cfg, "api_key", None)
    api_secret_secret = getattr(exchange_cfg, "api_secret", None)
    if api_key_secret is None or api_secret_secret is None:
        print("  ERROR demo credentials missing")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    try:
        api_key_value = (
            api_key_secret.get_secret_value()
            if hasattr(api_key_secret, "get_secret_value")
            else str(api_key_secret)
        )
        api_secret_value = (
            api_secret_secret.get_secret_value()
            if hasattr(api_secret_secret, "get_secret_value")
            else str(api_secret_secret)
        )
    except Exception:  # noqa: BLE001
        print("  ERROR demo credentials extract failed")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    if not api_key_value.strip() or not api_secret_value.strip():
        print("  ERROR demo credentials empty")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    try:
        client = BybitClient(
            api_key=api_key_value,
            api_secret=api_secret_value,
            environment="demo",
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR bybit_client init: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    # Resolve TP RR: CLI override -> default conservador 2.0; <=0 desliga TP.
    tp_rr_arg = args.take_profit_rr
    if tp_rr_arg is None:
        tp_rr_effective: Optional[float] = DEFAULT_TAKE_PROFIT_RR
    elif tp_rr_arg <= 0:
        tp_rr_effective = None
    else:
        tp_rr_effective = float(tp_rr_arg)

    try:
        mode_guard = ModeGuard(settings)
        risk_engine = RiskEngine(initial_capital=float(args.capital))
        preflight = BybitDemoPreflight(
            client=client,
            mode_guard=mode_guard,
            risk_engine=risk_engine,
            symbol=args.symbol,
            side=args.side,
            leverage_target=float(args.leverage),
            confirm_demo_execution=True,
            target_take_profit_rr=tp_rr_effective,
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR preflight init: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    report = preflight.run()
    if not report.ok:
        print(
            "  PREFLIGHT ABORT: "
            f"{report.abort_reason.value if report.abort_reason else 'unknown'}"
        )
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    try:
        api_blueprint = build_demo_api_blueprint(
            report,
            max_spread_pct=float(args.max_spread_pct),
            accept_leverage_manual_confirmation=bool(
                args.accept_leverage_manual_confirmation
            ),
            take_profit_rr=tp_rr_effective,
        )
    except DemoApiBlueprintRejected as e:
        # Surface specific reason (already sanitized in module) for runbook.
        msg = str(e)[:200]
        print(f"  BLUEPRINT REJECTED: {type(e).__name__}: {msg}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    try:
        serialize_to_json(api_blueprint, Path(args.output))
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR write blueprint: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    print(f"  Blueprint id: {api_blueprint.blueprint_id}")
    print(f"  Generated at: {api_blueprint.generated_at.isoformat()}")
    print(f"  Spread pct:   {api_blueprint.spread_pct:.4f}%")
    print(f"  Notional USD: {api_blueprint.notional_usd}")
    print(f"  Risk pct:     {api_blueprint.risk_pct:.4f}%")
    print(f"  TP RR used:   {api_blueprint.take_profit_rr}")
    print(f"  TP value:     {api_blueprint.proposal.take_profit}")
    if api_blueprint.manual_confirmations_needed:
        print("  Manual confirmations needed:")
        for c in api_blueprint.manual_confirmations_needed:
            print(f"    - {c}")
    print(f"  Blueprint written to: {args.output}")
    print()
    print("  Next step (within TTL):")
    print(f"    {api_blueprint.command_preview}")

    _footer(real_attempted=False)
    return EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    _banner()

    # FASE 22 mode routing.
    if args.prepare_demo_blueprint:
        if args.from_blueprint.strip():
            print("  ERROR cannot combine --prepare-demo-blueprint and "
                  "--from-blueprint")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID
        return _mode_prepare_blueprint(args)

    # FASE 22 safety: real-path + manual values is forbidden.
    real_requested = _real_path_requested(args) and not args.non_interactive_assume_no
    using_blueprint = bool(args.from_blueprint.strip())
    if real_requested and not using_blueprint:
        print(
            "  ERROR Real demo execution requires a fresh API-driven "
            "blueprint. Manual entry/sl/tp/size are allowed only for "
            "dry-run examples."
        )
        print("  Run with --prepare-demo-blueprint --output blueprint.json "
              "first, then re-run with --from-blueprint blueprint.json.")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID
    if using_blueprint and _has_manual_values(args):
        print("  ERROR --from-blueprint conflicts with manual "
              "--entry/--sl/--tp/--size (values come from the blueprint).")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    # Load blueprint OR validate manual dry-run inputs.
    blueprint_obj = None
    api_blueprint = None
    if using_blueprint:
        from crypto_trading_bot.demo_session_execution import (
            DemoApiBlueprintRejected,
            load_from_json,
            to_signal_blueprint,
        )
        try:
            api_blueprint = load_from_json(
                Path(args.from_blueprint),
                max_age_seconds=int(args.blueprint_ttl_seconds),
            )
        except DemoApiBlueprintRejected as e:
            print(f"  BLUEPRINT LOAD REJECTED: {type(e).__name__}")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID
        try:
            blueprint_obj = to_signal_blueprint(api_blueprint)
        except DemoApiBlueprintRejected as e:
            print(f"  BLUEPRINT BRIDGE REJECTED: {type(e).__name__}")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID
        derived_symbol = blueprint_obj.symbol
        derived_capital = float(api_blueprint.proposal.capital)
    else:
        # Dry-run preview path requires capital/symbol/entry/sl/tp/size.
        if args.capital is None:
            print("  ERROR --capital is required in dry-run preview path")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID
        if args.capital <= 0:
            print("  ERROR --capital must be > 0")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID
        for field_name in ("symbol", "entry", "sl", "tp", "size"):
            if getattr(args, field_name) is None:
                print(f"  ERROR --{field_name} is required in dry-run "
                      "preview path")
                _footer(real_attempted=False)
                return EXIT_REJECTED_OR_INVALID
        derived_symbol = args.symbol
        derived_capital = float(args.capital)

    # Build profile (from --profile + derived_capital).
    try:
        profile = _build_profile(args.profile, derived_capital)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR profile construction failed: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    # Build blueprint (SL/TP obrigatorios, ordering validado em __post_init__)
    from crypto_trading_bot.demo_session_execution import (
        BlueprintSide,
        DemoSessionPlanRejected,
        DemoSessionRejected,
        SignalBlueprint,
        build_demo_session_plan,
        execute_demo_session_gated,
    )
    from crypto_trading_bot.demo_session_readiness import (
        DemoSessionReadinessCheck,
    )
    from crypto_trading_bot.operational_safety.safety_state_machine import (
        SafetyStateMachine,
    )

    if blueprint_obj is None:
        try:
            blueprint_obj = SignalBlueprint(
                symbol=args.symbol,
                side=BlueprintSide.BUY if args.side == "buy" else BlueprintSide.SELL,
                entry_price=float(args.entry),
                stop_loss=float(args.sl),
                take_profit=float(args.tp),
                position_size_usd=float(args.size),
                leverage=float(args.leverage),
            )
        except (ValueError, TypeError) as e:
            print(f"  ERROR blueprint validation: {type(e).__name__}")
            _footer(real_attempted=False)
            return EXIT_REJECTED_OR_INVALID

    # Readiness (FASE 19)
    safety = SafetyStateMachine()
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=derived_symbol,
        capital=derived_capital,
        safety_machine=safety,
    )
    report = check.evaluate()
    print(f"  Readiness ready: {report.is_ready_for_gated_demo}")
    print(f"  Blocking reasons: {len(report.blocking_reasons)}")
    if report.blocking_reasons:
        for r in report.blocking_reasons:
            print(f"    BLOCK {r}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    # Build plan
    from crypto_trading_bot.config.risk_config import RiskConfig
    try:
        plan = build_demo_session_plan(
            plan_id=str(uuid.uuid4()),
            readiness_report=report,
            profile=profile,
            blueprint=blueprint_obj,
            effective_risk_config=RiskConfig(),
            readiness_max_age_seconds=int(args.readiness_max_age_seconds),
        )
    except DemoSessionPlanRejected as e:
        print(f"  PLAN REJECTED: {type(e).__name__}")
        _footer(real_attempted=False)
        return EXIT_REJECTED_OR_INVALID

    print(f"  Plan id: {plan.plan_id}")
    print(
        f"  Symbol: {plan.blueprint.symbol}  side: "
        f"{plan.blueprint.side.value}"
    )
    print(
        f"  Entry: {plan.blueprint.entry_price}  SL: {plan.blueprint.stop_loss}"
        f"  TP: {plan.blueprint.take_profit}"
    )
    print(f"  position_size_usd: {plan.blueprint.position_size_usd}")
    if api_blueprint is not None:
        print(f"  Source: API blueprint id={api_blueprint.blueprint_id}")
        print(
            f"  Blueprint age tolerated <= {args.blueprint_ttl_seconds}s"
        )
    print()

    # Decide real-demo path
    flags_complete = _compute_real_demo_requested(args)
    print(f"  Four CLI flags complete: {flags_complete}")
    if args.non_interactive_assume_no:
        print("  --non-interactive-assume-no set: forcing dry-run.")
        flags_complete = False

    real_attempted = False
    executor = None
    abort_reason: Optional[str] = None
    if flags_complete:
        # FASE 22.3: pass the derived_capital explicitly. When
        # --from-blueprint is used, args.capital is None; derived_capital
        # was already resolved from api_blueprint.proposal.capital above.
        executor, build_reason = _build_real_demo_executor(
            args, capital=derived_capital,
        )
        if executor is None:
            abort_reason = build_reason
            print(f"  Real demo executor NOT instantiated: {abort_reason}")
            print("  Falling back to DRY-RUN executor.")
        else:
            real_attempted = True
            print("  Real demo executor instantiated. Proceeding to gate.")

    if executor is None:
        executor = _DryExecutor()

    # post_session_check_fn
    # FASE 22 Final: caminho real prioriza post_session_check forte
    # (balance + positions + open_orders + residual detection). Fallback
    # safe_check_only (apenas get_balance) sera usado se o executor nao
    # tiver o metodo novo (compatibilidade defensiva). Em dry-run, usa
    # safe_check_only(dry_run=True) sem chamar rede.
    # FASE 22 close-out: pos-Command B real, a posicao recem-aberta com
    # SL/TP server-side eh esperada e NAO eh residual. Usar stage=
    # "after_entry" + expected_qty do blueprint. Flat-check final (zero
    # positions) eh responsabilidade do operador apos fechar pela UI.
    derived_symbol_for_check = derived_symbol
    expected_qty_for_check: Optional[float] = None
    if api_blueprint is not None:
        try:
            expected_qty_for_check = float(api_blueprint.proposal.qty)
        except Exception:  # noqa: BLE001
            expected_qty_for_check = None
    post_check_fn = None
    if real_attempted:
        if hasattr(executor, "post_session_check"):
            post_check_fn = (
                lambda: executor.post_session_check(
                    derived_symbol_for_check,
                    dry_run=False,
                    stage="after_entry",
                    expected_qty=expected_qty_for_check,
                    require_sl=True,
                    require_tp=True,
                )
            )
        elif hasattr(executor, "safe_check_only"):
            # Fallback legado (apenas get_balance). Marca como manual review
            # logico no proprio metodo; o gate ja propaga a flag se vier.
            post_check_fn = (
                lambda: executor.safe_check_only(dry_run=False)
            )
    else:
        if hasattr(executor, "post_session_check"):
            post_check_fn = (
                lambda: executor.post_session_check(
                    derived_symbol_for_check,
                    dry_run=True,
                    stage="after_entry",
                )
            )
        elif hasattr(executor, "safe_check_only"):
            post_check_fn = (
                lambda: executor.safe_check_only(dry_run=True)
            )

    # ModeGuard + Settings
    from crypto_trading_bot.config.settings import Settings, TradingMode
    from crypto_trading_bot.core.mode_guard import ModeGuard
    from crypto_trading_bot.execution.provider_registry import get_registry
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    if real_attempted:
        # In real path we use real Settings (already validated by
        # _build_real_demo_executor); reuse a fresh instance here. No print.
        try:
            mg_settings = Settings()
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR mode_guard settings: {type(e).__name__}")
            _footer(real_attempted=True)
            return EXIT_REJECTED_OR_INVALID
    else:
        # Preview path uses paper-mode ModeGuard placeholder which the
        # gate will reject (expected SAFE behavior).
        mg_settings = Settings(
            trading_mode=TradingMode.PAPER,
            enable_demo_execution=False,
            enable_live_trading=False,
            enable_testnet_execution=False,
        )
    cli_mode_guard = ModeGuard(mg_settings)

    try:
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=RiskEngine(initial_capital=derived_capital),
            demo_executor=executor,
            safety_machine=safety,
            mode_guard=cli_mode_guard,
            provider_registry=get_registry(),
            operator_token=(args.operator_token or "cli_preview_token"),
            confirm_demo_session=True,
            dry_run=(not real_attempted),
            notes=args.notes,
            post_session_check_fn=post_check_fn,
        )
    except DemoSessionRejected as e:
        print(f"  GATE REJECTED: {type(e).__name__}")
        _footer(real_attempted=real_attempted)
        # If dry-run preview was rejected by paper-mode guard, that is
        # the safe expected behavior; surface as EXIT_OK so CI/preview
        # use is non-noisy. Real-attempt rejection is EXIT 1.
        return (
            EXIT_REJECTED_OR_INVALID if real_attempted else EXIT_OK
        )

    print()
    print(f"  Outcome reason: {outcome.outcome_reason}")
    print(f"  Recommended next: {outcome.recommended_next_action.value}")
    print(f"  is_filled_canonical: {outcome.is_filled_canonical}")
    print(f"  requires_manual_review: {outcome.requires_manual_review}")
    print(f"  safety_halt_recommended: {outcome.safety_halt_recommended}")
    print(f"  final_safety_state: {outcome.final_safety_state}")
    print(f"  operator_token (sanitized): {outcome.operator_token_sanitized}")

    # FASE 22 close-out: quando manual_review ou halt, imprime resumo
    # SANITIZADO do post_session_check para o operador entender o motivo.
    if (
        outcome.requires_manual_review or outcome.safety_halt_recommended
    ) and outcome.post_session_check_summary is not None:
        pcs = outcome.post_session_check_summary
        print()
        print("  Post-session-check summary (sanitized):")
        # Apenas keys de interesse, sem secrets. dict eh ja sanitizado
        # pelo BybitDemoExecutor.post_session_check.
        keys_of_interest = (
            "success", "operation", "dry_run",
            "manual_review_required", "safety_halt_recommended",
            "reason",
        )
        for key in keys_of_interest:
            if key in pcs:
                value = pcs[key]
                # Redact defensivo de qualquer linha que possa carregar
                # token suspeito (origin_string ja eh redactado por
                # BybitAPIError, mas defesa em profundidade aqui).
                if isinstance(value, str):
                    low = value.lower()
                    if any(s in low for s in (
                        "origin_string", "x-bapi-sign", "bearer ",
                        "authorization:", "api_key=", "api_secret=",
                    )):
                        value = "<redacted_suspicious>"
                print(f"    {key}: {value}")

    _footer(real_attempted=real_attempted)

    # Exit code
    if outcome.safety_halt_recommended or outcome.requires_manual_review:
        return EXIT_MANUAL_REVIEW_OR_HALT
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
