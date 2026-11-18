#!/usr/bin/env python
"""
run_demo_30_min_endurance.py - Demo 30 Min REAL Endurance Gate (FASE 27)
============================================================================
ASCII-only. Caminho ALTERNATIVO opt-in para demo endurance strategy-driven
de ate 30 minutos com NO MAXIMO 1 ordem.

WARNING:Execucao real demo single-shot continua via FASE 22 runbook:
    scripts/run_bybit_demo_session_gated.py (Comando A + Comando B).
    FASE 27 NAO substitui FASE 22 - eh trilha paralela.

REGRAS ABSOLUTAS:
    - Default: readiness offline / dry-run safe.
    - Execucao real demo exige SIMULTANEAMENTE:
        --apply-demo-real
        --confirm-demo-endurance
        --i-understand-this-is-demo-endurance
        --execute-real
        prompt humano com resposta exatamente "Y"
        TTY presente (--non-interactive-assume-no abre dry-run safe)
        operator_token nao-vazio
        TRADING_MODE=demo
        ENABLE_DEMO_EXECUTION=true
        ENABLE_LIVE_TRADING=false
        provider_id=bybit_demo_linear
        ProviderStatus exatamente OPT_IN
        max_orders=1
        max_minutes<=30

    - Nenhuma ordem real envia sem TODAS as travas acima.
    - retry/segunda ordem/scheduler/background sao PROIBIDOS.
    - close_position/cancel_order NAO sao chamados.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _safe_load_dotenv() -> int:
    """FASE 28 closeout - autoload .env presence-only.

    Politica:
        - NUNCA imprime valores das variaveis carregadas.
        - NUNCA sobrescreve variaveis ja presentes no ambiente
          (override=False).
        - Usa python-dotenv se disponivel; fallback para parser minimo
          de KEY=VALUE caso a lib esteja ausente.
        - Apenas relata quantas chaves NOVAS foram introduzidas (count).
        - Retorna o numero de chaves novas; 0 em qualquer falha.
    """
    env_path = _ROOT / ".env"
    if not env_path.is_file():
        return 0
    before = set(os.environ.keys())
    try:
        # Lazy import: python-dotenv eh dependencia opcional. Se
        # ausente, cair para parser minimo.
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv(dotenv_path=str(env_path), override=False)
    except Exception:  # noqa: BLE001
        # Fallback minimo seguro: KEY=VALUE por linha, comentarios com #.
        try:
            text = env_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return 0
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            # Remove aspas simples/duplas externas se presentes.
            if (len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            )):
                value = value[1:-1]
            os.environ[key] = value
    after = set(os.environ.keys())
    return len(after - before)


# Auto-load .env early so downstream lazy imports / env reads see the
# operator's demo configuration. NUNCA imprime valores; o banner
# apenas informa a contagem de chaves carregadas.
_DOTENV_LOADED_COUNT = _safe_load_dotenv()


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
    print("  DEMO 30 MIN - REAL ENDURANCE GATE (FASE 27/28)")
    print("  NO mainnet/live. NO retry. Max 1 order. Max 30 min.")
    print("  Real execution requires 4 redundant flags + prompt Y.")
    print("  Single-shot real demo continues via FASE 22 runbook:")
    print("    scripts/run_bybit_demo_session_gated.py")
    if _DOTENV_LOADED_COUNT > 0:
        # Apenas count; valores nunca sao impressos.
        print(
            f"  .env autoloaded ({_DOTENV_LOADED_COUNT} new keys; "
            "values never printed; override=False)"
        )
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
            "Demo 30 Min Real Endurance Gate (FASE 27). "
            "Default dry-run / readiness-only. Real demo gated."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=True,
    )
    parser.add_argument(
        "--capital", type=float, required=True,
        help="account_size_usd in USD. Required (FASE 24 microfix).",
    )
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument(
        "--strategy", type=str, default="trend_pullback",
        choices=_STRATEGY_CHOICES,
    )
    parser.add_argument(
        "--max-orders", type=int, default=1,
        help="Hard cap = 1 in FASE 27.",
    )
    parser.add_argument(
        "--max-minutes", type=int, default=30,
        help="Hard cap = 30 in FASE 27.",
    )
    parser.add_argument(
        "--cycle-interval-seconds", type=float, default=60.0,
    )
    parser.add_argument(
        "--operator-token", type=str, required=True,
        help="Operator token (sanitized in outputs).",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Optional JSON output path (sanitized; rejects '..').",
    )
    parser.add_argument(
        "--prompt-timeout-seconds", type=float, default=60.0,
    )
    parser.add_argument(
        "--non-interactive-assume-no", action="store_true",
        help="CI/no-TTY: forces safe decline (no real order).",
    )
    parser.add_argument(
        "--readiness-only", action="store_true",
        help="Run readiness only; no runner, no order.",
    )
    parser.add_argument(
        "--notes", type=str, default="",
        help="Operator notes (sanitized, truncated to 200 chars).",
    )
    # The four redundant flags required for real execution.
    parser.add_argument("--apply-demo-real", action="store_true")
    parser.add_argument("--confirm-demo-endurance", action="store_true")
    parser.add_argument(
        "--i-understand-this-is-demo-endurance", action="store_true",
    )
    parser.add_argument("--execute-real", action="store_true")
    # FASE 28 - telemetry output + stub final flag.
    parser.add_argument(
        "--telemetry-output", type=str, default="",
        help="Optional JSONL telemetry path (sanitized; rejects '..').",
    )
    parser.add_argument(
        "--apply-demo-real-final", action="store_true",
        help=(
            "STUB in FASE 28. First real order requires FASE 29 "
            "explicit approval (separate flag --first-real-demo-order)."
        ),
    )
    # FASE 29 - 5a flag redundante + max-close-orders
    parser.add_argument(
        "--first-real-demo-order", action="store_true",
        help=(
            "FASE 29 - 5th redundant flag for the first real demo "
            "order via wired runner. Requires phrase confirmation."
        ),
    )
    parser.add_argument(
        "--max-close-orders", type=int, default=1,
        help="FASE 29 hard cap = 1.",
    )

    args = parser.parse_args(argv)

    _banner()

    # --- FASE 28 stub guard: --apply-demo-real-final never sends order ---
    if args.apply_demo_real_final:
        print(
            "  ERROR --apply-demo-real-final is a STUB in FASE 28. "
            "First real order requires FASE 29 authorization. "
            "No effect; exiting."
        )
        _footer()
        return 0

    # --- argparse-level basic validations ---
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
    if args.max_orders != 1:
        print(
            "  ERROR --max-orders must be exactly 1 in FASE 27 "
            f"(received {args.max_orders})"
        )
        _footer()
        return 1
    if args.max_minutes <= 0 or args.max_minutes > 30:
        print(
            "  ERROR --max-minutes must be in (0, 30] in FASE 27 "
            f"(received {args.max_minutes})"
        )
        _footer()
        return 1

    # --- lazy imports (avoid heavy load at parse time) ---
    from crypto_trading_bot.demo_endurance import (
        build_default_planned_blueprint,
        build_demo_30_min_plan,
        build_demo_30_min_readiness_report,
        DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
        DEMO_30_MIN_MAX_SESSION_MINUTES,
        DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
        DEMO_30_MIN_PLANNED_ENVIRONMENT,
        DEMO_30_MIN_PLANNED_PROVIDER_ID,
        Demo30MinReadinessConfig,
        EnvironmentSnapshot,
        envvar_present,
        is_tty,
        LastSafetyFlags,
        LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS,
        prompt_yes_or_abort,
        to_ui_snapshot,
        TTYRequired,
    )

    # --- determine if user is attempting real execution ---
    real_flags_set = (
        args.apply_demo_real
        and args.confirm_demo_endurance
        and args.i_understand_this_is_demo_endurance
        and args.execute_real
    )
    real_flags_any = (
        args.apply_demo_real
        or args.confirm_demo_endurance
        or args.i_understand_this_is_demo_endurance
        or args.execute_real
    )

    # Partial flags -> hard fail (cannot accidentally go halfway).
    if real_flags_any and not real_flags_set:
        missing = []
        if not args.apply_demo_real:
            missing.append("--apply-demo-real")
        if not args.confirm_demo_endurance:
            missing.append("--confirm-demo-endurance")
        if not args.i_understand_this_is_demo_endurance:
            missing.append("--i-understand-this-is-demo-endurance")
        if not args.execute_real:
            missing.append("--execute-real")
        print(
            "  ERROR real execution requires ALL four redundant flags. "
            f"Missing: {missing}"
        )
        _footer()
        return 1

    # --- ENV gates (presence only; values never printed) ---
    env_live = envvar_present("ENABLE_LIVE_TRADING") and \
        (os.environ.get("ENABLE_LIVE_TRADING", "").strip().lower()
         in ("true", "1", "yes"))
    env_demo_exec = (
        os.environ.get("ENABLE_DEMO_EXECUTION", "").strip().lower()
        in ("true", "1", "yes")
    )
    env_mode = os.environ.get("TRADING_MODE", "").strip().lower()

    env_snap = EnvironmentSnapshot(
        enable_live_trading=env_live,
        enable_demo_execution=env_demo_exec,
        # Note: para path readiness-only/dry-run, trading_mode pode ser
        # "paper" (default); real path exige "demo" explicito.
        trading_mode=(env_mode or "paper"),
        provider_id=DEMO_30_MIN_PLANNED_PROVIDER_ID,
        provider_status="opt_in",
        endpoint_type=DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
        credentials_present=(
            envvar_present("BYBIT_DEMO_API_KEY")
            and envvar_present("BYBIT_DEMO_API_SECRET")
        ),
        environment=DEMO_30_MIN_PLANNED_ENVIRONMENT,
    )
    last_flags = LastSafetyFlags()

    # --- offline readiness ---
    bp_planned = build_default_planned_blueprint(
        symbol=args.symbol, wallet_balance_usd=float(args.capital),
    )
    readiness_cfg = Demo30MinReadinessConfig(
        symbol=args.symbol,
        strategy_name=args.strategy,
        capital_usd=float(args.capital),
        max_orders=int(args.max_orders),
        max_session_minutes=int(args.max_minutes),
        max_trades_per_day=10,
        operator_token=args.operator_token,
        environment_snapshot=env_snap,
        last_safety_flags=last_flags,
        planned_blueprint=bp_planned,
    )
    # If real path requested, tighten env requirements (mode=demo,
    # enable_demo_execution=true). Add as additional pre-readiness gates.
    extra_blockers = []
    if real_flags_set:
        if env_live:
            extra_blockers.append("ENABLE_LIVE_TRADING=true is forbidden")
        if not env_demo_exec:
            extra_blockers.append(
                "ENABLE_DEMO_EXECUTION must be 'true' for real path"
            )
        if env_mode != "demo":
            extra_blockers.append(
                f"TRADING_MODE must be 'demo' (got {env_mode!r})"
            )
        if not env_snap.credentials_present:
            extra_blockers.append(
                "BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET must be "
                "present (values never printed)"
            )

    readiness = build_demo_30_min_readiness_report(readiness_cfg)

    print(f"  Profile:        {args.profile}")
    print(f"  Capital (USD):  {args.capital}")
    print(f"  Symbol:         {args.symbol}")
    print(f"  Strategy:       {args.strategy}")
    print(f"  Max orders:     {args.max_orders} "
          f"(hard cap {DEMO_30_MIN_MAX_ORDERS_HARD_CAP})")
    print(f"  Max minutes:    {args.max_minutes} "
          f"(hard cap {DEMO_30_MIN_MAX_SESSION_MINUTES})")
    print(f"  Real flags:     {bool(real_flags_set)}")
    print(f"  Readiness:      {readiness.status.value}")
    print(f"  Blockers:       {readiness.total_blockers}")
    if readiness.blockers:
        for i in readiness.blockers:
            print(f"    [BLOCKER] {i.gate}: {i.message}")
    for msg in extra_blockers:
        print(f"    [BLOCKER] env: {msg}")
    print()

    if args.readiness_only:
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "extra_blockers": list(extra_blockers),
            "real_flags_set": bool(real_flags_set),
        })
        _footer()
        return 0 if readiness.is_ready and not extra_blockers else 1

    if not readiness.is_ready or extra_blockers:
        print("  READINESS NOT_READY: runner not started.")
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "extra_blockers": list(extra_blockers),
        })
        _footer()
        return 1

    # --- if NOT real path: stop here (FASE 26 covers dry-run simulation) ---
    if not real_flags_set:
        print(
            "  No real-execution flags set. Use FASE 26 "
            "scripts/run_demo_30_min_planned.py for dry-run simulation. "
            "FASE 27 only proceeds when ALL four redundant flags are set."
        )
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "real_flags_set": False,
        })
        _footer()
        return 0

    # --- interactive prompt Y (mandatory in real path) ---
    if args.non_interactive_assume_no:
        print(
            "  --non-interactive-assume-no set: real execution declined. "
            "No order sent. Use FASE 26 dry-run for non-TTY environments."
        )
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "real_flags_set": True,
            "execution_declined": "non_interactive_assume_no",
        })
        _footer()
        return 1

    try:
        confirmed = prompt_yes_or_abort(
            "  Type Y to ACTUALLY send demo order if signal triggers "
            "(NO mainnet/live; NO retry; max 1 order; max 30 min): ",
            timeout_seconds=float(args.prompt_timeout_seconds),
            assume_no=False,
        )
    except TTYRequired as e:
        print(f"  ERROR {e}")
        _footer()
        return 1

    if not confirmed:
        print("  Confirmation declined. No order sent.")
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "real_flags_set": True,
            "execution_declined": "prompt_not_Y",
        })
        _footer()
        return 1

    # --- FASE 28 WIRED DRY-RUN BRANCH ---
    # Real network client wiring is gated behind one more boundary:
    # DEMO_30_MIN_REAL_RUNNER_DEPLOYED=true. Even with this flag, the
    # gate ALWAYS receives dry_run=True in FASE 28. First real order
    # requires FASE 29 authorization.
    deploy_ready = envvar_present("DEMO_30_MIN_REAL_RUNNER_DEPLOYED") and \
        (os.environ.get("DEMO_30_MIN_REAL_RUNNER_DEPLOYED", "")
         .strip().lower() in ("true", "1", "yes"))
    if not deploy_ready:
        print(
            "  WARN four flags + prompt Y OK, but real runner not "
            "deployed in this environment. Export "
            "DEMO_30_MIN_REAL_RUNNER_DEPLOYED=true to proceed with "
            "WIRED DRY-RUN (no real order sent). See "
            "docs/demo_30_min_real_runbook.md."
        )
        _maybe_write_output(args.output, {
            "readiness": readiness.to_dict(),
            "real_flags_set": True,
            "execution_declined": "real_runner_not_deployed",
        })
        _footer()
        return 1

    # --- FASE 29 BRANCH (real order) vs FASE 28 (wired dry-run) ---
    phase29_enabled = (
        envvar_present("DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED")
        and os.environ.get(
            "DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED", ""
        ).strip().lower() in ("true", "1", "yes")
    )
    if args.first_real_demo_order and phase29_enabled:
        print()
        print(
            "  FASE 29 - FIRST REAL DEMO ORDER PATH. "
            "Gate will be invoked with dry_run=False. "
            "Real order WILL be sent to api-demo.bybit.com."
        )
        print()
        return _run_phase29_real_full_cycle(
            args=args, readiness_dict=readiness.to_dict(),
        )

    # --- FASE 28 default branch ---
    print()
    print(
        "  FASE 28 WIRED DRY-RUN ONLY - gate dry_run=True. "
        "First real order requires FASE 29."
    )
    print(
        "  NOTE The preflight below performs READ-ONLY API demo "
        "calls (no order)."
    )
    print()

    return _run_wired_dry_run(args=args, readiness_dict=readiness.to_dict())


def _run_phase29_real_full_cycle(
    *, args, readiness_dict: dict,
) -> int:
    """FASE 29 - primeira ordem real demo via wired runner.

    Gates redundantes:
        - env DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED=true (ja checado)
        - env BYBIT_USE_DEMO=true
        - 5 flags + frase exata + prompt Y + TTY
        - operator_token
        - readiness ready + flat-check inicial OK
        - apply_demo_real=True passado para o gate

    Esta funcao NAO envia ordem por si: delega ao runner FASE 27/28 com
    apply_demo_real=True. O envio real eh produzido pelo gate FASE 22
    com dry_run=False.
    """
    from crypto_trading_bot.demo_endurance import (
        build_default_planned_blueprint,
        build_demo_30_min_plan,
        build_close_executor_wrapper,
        build_live_blueprint_provider,
        build_live_demo_client,
        build_live_demo_executor,
        build_live_preflight_factory,
        build_phase29_exit_resolver,
        build_pnl_tracker,
        build_position_monitor,
        build_provider_registry_with_opt_in,
        build_session_plan_factory,
        Demo30MinRealRunner,
        ENV_REAL_ORDER_ENABLED,
        ENV_REDUCE_ONLY_CLOSE_ENABLED,
        ENV_USE_DEMO,
        envvar_present,
        EXPECTED_PHRASE,
        ProductionWiringError,
        prompt_yes_or_abort,
        SessionTelemetryRecorder,
        to_ui_snapshot,
        TTYRequired,
        validate_phase29_entry_gate,
    )

    # --- BYBIT_USE_DEMO env required ---
    if not (
        envvar_present(ENV_USE_DEMO)
        and os.environ.get(ENV_USE_DEMO, "").strip().lower()
        in ("true", "1", "yes")
    ):
        print(f"  ERROR {ENV_USE_DEMO}=true required for FASE 29")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "BYBIT_USE_DEMO_missing",
        })
        _footer()
        return 1

    # --- Phrase confirmation (FASE 29 specific) ---
    print()
    print("  BEFORE PROCEEDING - read carefully:")
    print(
        "  This will send a REAL DEMO ORDER to api-demo.bybit.com."
    )
    print("  Type EXACTLY the following phrase (case-sensitive):")
    print(f"    {EXPECTED_PHRASE}")
    print()
    try:
        phrase_entered = input("  Phrase: ").strip()
    except (EOFError, KeyboardInterrupt):
        phrase_entered = ""

    if phrase_entered != EXPECTED_PHRASE:
        print("  ERROR phrase mismatch. No order sent.")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "phrase_mismatch",
        })
        _footer()
        return 1

    # --- TTY + prompt Y final ---
    try:
        confirmed = prompt_yes_or_abort(
            "  FINAL CONFIRMATION - Type Y to send real demo order: ",
            timeout_seconds=float(args.prompt_timeout_seconds),
            assume_no=False,
        )
    except TTYRequired as e:
        print(f"  ERROR {e}")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "tty_required",
        })
        _footer()
        return 1

    if not confirmed:
        print("  Confirmation declined. No order sent.")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "prompt_not_Y",
        })
        _footer()
        return 1

    # --- Validacao do gate FASE 29 (pura) ---
    gate_result = validate_phase29_entry_gate(
        phrase_confirmation=phrase_entered,
        flag_apply_demo_real=bool(args.apply_demo_real),
        flag_confirm_demo_endurance=bool(args.confirm_demo_endurance),
        flag_i_understand=bool(
            args.i_understand_this_is_demo_endurance
        ),
        flag_execute_real=bool(args.execute_real),
        flag_first_real_demo_order=bool(args.first_real_demo_order),
        prompt_y_confirmed=bool(confirmed),
        operator_token=args.operator_token,
        tty_present=True,
        non_interactive_assume_no=False,
    )
    if not gate_result.approved:
        print("  ERROR FASE 29 entry gate rejected:")
        for b in gate_result.blockers:
            print(f"    - {b}")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "gate_phase29_rejected",
            "gate_result": gate_result.to_dict(),
        })
        _footer()
        return 1

    # --- Wiring real ---
    try:
        client = build_live_demo_client()
    except ProductionWiringError as e:
        print(f"  ERROR wiring (client): {str(e)[:200]}")
        _footer()
        return 1

    try:
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        from crypto_trading_bot.operational_safety.safety_state_machine \
            import SafetyStateMachine
        from crypto_trading_bot.operational_profile import (
            build_personal_profile,
        )
        mode_guard = ModeGuard()
        risk_engine = RiskEngine(initial_capital=float(args.capital))
        safety_machine = SafetyStateMachine()
        profile = build_personal_profile(
            account_size_usd=float(args.capital)
        )
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR deps: {type(e).__name__}: {str(e)[:160]}"
        )
        _footer()
        return 1

    try:
        registry = build_provider_registry_with_opt_in()
    except ProductionWiringError as e:
        print(f"  ERROR registry: {str(e)[:200]}")
        _footer()
        return 1

    preflight_factory = build_live_preflight_factory(
        client=client, mode_guard=mode_guard, risk_engine=risk_engine,
        symbol=args.symbol, side="buy",
        leverage_target=1.0, target_take_profit_rr=2.0,
    )
    provider = build_live_blueprint_provider(
        preflight_factory=preflight_factory,
    )

    print("  Running FASE 29 preflight + flat-check (read-only)...")
    try:
        snapshot = provider.preflight()
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR preflight: {type(e).__name__}: {str(e)[:160]}"
        )
        _footer()
        return 1
    bp_live = snapshot.blueprint
    flat_blockers = []
    if int(bp_live.open_positions_count) > 0:
        flat_blockers.append("open_positions > 0")
    if int(bp_live.open_orders_count) > 0:
        flat_blockers.append("open_orders > 0")
    if int(bp_live.conditional_orders_count) > 0:
        flat_blockers.append("conditional_orders > 0")
    if flat_blockers:
        for b in flat_blockers:
            print(f"  [BLOCKER] flat-check: {b}")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "flat_check_failed",
            "flat_blockers": flat_blockers,
        })
        _footer()
        return 1

    print(
        f"  Flat-check OK. blueprint_id={snapshot.blueprint_id} "
        f"ttl={snapshot.ttl_remaining()}s"
    )

    runner_plan = build_demo_30_min_plan(
        symbol=args.symbol, strategy_name=args.strategy,
        max_orders=int(args.max_orders),
        max_session_minutes=int(args.max_minutes),
        risk_thresholds_snapshot={
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
        },
        planned_blueprint=bp_live,
        operator_token=args.operator_token,
        live_blueprint_id=snapshot.blueprint_id,
    )
    recorder = SessionTelemetryRecorder(
        operator_token=args.operator_token,
    )

    def _market_data(*, symbol, timeframe, limit):
        return client.get_candles(
            symbol=symbol, timeframe=timeframe, limit=limit,
        )

    executor = build_live_demo_executor(
        client=client, mode_guard=mode_guard, risk_engine=risk_engine,
        confirm_demo_execution=True,
    )
    session_plan_factory = build_session_plan_factory()

    # FASE 29 - apply_demo_real=True (gate sera chamado com dry_run=False).
    # Telemetria dotenv_loaded + readiness_done emitidos manualmente
    # antes de instanciar o runner.
    recorder.record(
        "session_start",
        snapshot={"phase": "29", "first_real_demo_order": True},
    )

    runner = Demo30MinRealRunner(
        plan=runner_plan, provider=provider,
        risk_engine=risk_engine, safety_machine=safety_machine,
        mode_guard=mode_guard, provider_registry=registry,
        effective_risk_config=(
            risk_engine.config if hasattr(risk_engine, "config")
            else None
        ),
        profile=profile, operator_token=args.operator_token,
        market_data_callable=_market_data,
        demo_executor_factory=lambda: executor,
        session_plan_factory=session_plan_factory,
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        apply_demo_real=True,  # FASE 29
        notes=args.notes,
        telemetry_recorder=recorder,
    )

    print()
    print("  Starting FASE 29 runner (real order may be sent)...")
    try:
        outcome = runner.run_real()
    except KeyboardInterrupt:
        print("  Runner interrupted by operator.")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "phase29_requested": True,
            "execution_declined": "operator_interrupt",
        })
        _footer()
        return 1

    # FASE 29 - inject extra flags into outcome via aditivo opcional.
    # Cria novo Outcome com mesmos dados + flags FASE 29.
    from dataclasses import replace
    outcome = replace(
        outcome,
        first_real_demo_order=True,
        phrase_confirmation=True,
    )

    # Position monitor + exit management ficam disponiveis no
    # production_wiring; nesta versao consolidada, a entrada eh
    # executada via runner FASE 27/28 e a saida real (TP/SL
    # server-side OU reduceOnly) eh gerenciada pelo monitor +
    # close wrapper APENAS quando uma entrada efetiva ocorrer e
    # operador habilitar reduceOnly via ENV separada. Nesta
    # implementacao consolidada, o monitor/close eh chamado
    # condicionalmente abaixo apenas se houve ordem de entrada.
    if outcome.orders_submitted >= 1:
        # Tenta gerenciar saida; resultado eh anexado ao outcome.
        outcome = _run_phase29_exit_management(
            client=client, args=args, plan=runner_plan,
            outcome=outcome, mode_guard=mode_guard,
            risk_engine=risk_engine,
            recorder=recorder, executor=executor,
        )
    else:
        # Cenario B_zero: sem sinal aprovado, sem entrada. Seguro mas
        # NAO finaliza Demo. demo_finalized permanece False.
        outcome = replace(
            outcome,
            demo_finalized=False,
            demo_finalization_scenario="B_zero",
        )

    snap = to_ui_snapshot(plan=runner_plan, outcome=outcome)

    print()
    print("  === PHASE 29 FINAL ===")
    print(f"    orders_submitted:   {outcome.orders_submitted}")
    print(f"    orders_filled:      {outcome.orders_filled}")
    print(f"    open_positions:     "
          f"{outcome.open_positions_count}")
    print(f"    exit_path:          "
          f"{outcome.exit_management_path}")
    print(f"    exit_reason:        {outcome.exit_reason}")
    print(f"    close_submitted:    "
          f"{outcome.close_orders_submitted}")
    print(f"    close_filled:       "
          f"{outcome.close_orders_filled}")
    print(f"    pnl_realized_usd:   "
          f"{outcome.pnl_realized_usd}")
    print(f"    pnl_source:         {outcome.pnl_source}")
    print(f"    flat_check.is_flat: "
          f"{snap['flat_check_final'].get('is_flat')}")
    print(f"    verdict:            {outcome.verdict.value}")
    print(f"    recommended:        "
          f"{outcome.recommended_next_action.value}")
    print()
    # FASE 29 Acceptance Polish - sinalizacao explicita e nao-ambigua.
    _demo_final = "YES" if outcome.demo_finalized else "NO"
    print(f"  DEMO FINALIZED: {_demo_final}")
    print(
        f"  scenario={outcome.demo_finalization_scenario}"
    )
    if outcome.demo_finalized:
        print(
            "  Demo stage FINALIZED (demo_full_cycle_clean). "
            "Manual UI verification recommended at api-demo.bybit.com."
        )
    elif outcome.demo_finalization_scenario == "B_zero":
        print(
            "  Safe but inconclusive (zero trade). "
            "DEMO STAGE NOT YET FINALIZED. Repeat session."
        )
    else:
        print(
            "  Manual close path or incomplete cycle. "
            "DEMO STAGE NOT YET FINALIZED. Verify api-demo.bybit.com UI."
        )

    _maybe_write_output(args.output, {
        "readiness": readiness_dict,
        "phase29_requested": True,
        "real_demo_full_cycle": True,
        "phase": "29",
        "plan": runner_plan.to_dict(),
        "outcome": outcome.to_dict(),
        "ui_snapshot": snap,
    })

    if args.telemetry_output:
        try:
            recorder.to_jsonl_file(args.telemetry_output)
            print(f"  Telemetry written to: {args.telemetry_output}")
        except ValueError as e:
            print(f"  ERROR telemetry: {str(e)[:200]}")

    _footer()
    if outcome.verdict.value in ("passed_zero_trades",
                                  "passed_one_trade"):
        return 0
    if outcome.verdict.value in ("failed",
                                  "manual_review_required",
                                  "safety_halt_ack_needed"):
        return 2
    return 1


def _run_phase29_exit_management(
    *, client, args, plan, outcome, mode_guard, risk_engine,
    recorder, executor,
):
    """FASE 29 - apos entrada, gerencia saida (read-only + opcional
    reduceOnly close).

    Reduce-only close so ocorre se DEMO_30_MIN_REDUCE_ONLY_CLOSE_
    PHASE29_ENABLED=true E ExitDecisionResolver indicar should_close
    com requires_reduce_only=True.
    """
    from dataclasses import replace
    from datetime import datetime, timezone
    from crypto_trading_bot.demo_endurance import (
        build_close_executor_wrapper,
        build_phase29_exit_resolver,
        build_pnl_tracker,
        build_position_monitor,
        build_open_position_state_from_snapshot,
        envvar_present,
        validate_flat,
        validate_phase29_close_gate,
    )

    monitor = build_position_monitor(
        client=client, symbol=args.symbol,
        poll_interval_seconds=float(args.cycle_interval_seconds),
        max_monitor_minutes=max(
            1, int(args.max_minutes) // 2,
        ),
    )
    resolver = build_phase29_exit_resolver()
    pnl_tracker = build_pnl_tracker(client=client)
    close_wrapper = build_close_executor_wrapper(executor=executor)

    reduce_only_enabled = (
        envvar_present("DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED")
        and os.environ.get(
            "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED", "",
        ).strip().lower() in ("true", "1", "yes")
    )

    recorder.record(
        "exit_monitoring_started",
        snapshot={
            "max_monitor_minutes": monitor.max_monitor_minutes,
            "reduce_only_enabled": reduce_only_enabled,
        },
    )

    entry_time = datetime.now(timezone.utc)
    entry_price = float(plan.planned_blueprint.entry_price)
    qty = float(plan.planned_blueprint.qty)
    stop_loss = float(plan.planned_blueprint.stop_loss)
    take_profit = float(plan.planned_blueprint.take_profit)
    side = str(plan.planned_blueprint.side)

    exit_path = "none"
    exit_reason = None
    exit_price = None
    exit_ms = None
    close_orders_submitted = 0
    close_orders_filled = 0
    flat_check_dict = None

    max_polls = max(1, monitor.max_monitor_minutes)
    for poll_idx in range(max_polls):
        snap = monitor.poll_once(poll_idx=poll_idx)
        recorder.record(
            "position_snapshot", cycle_idx=poll_idx,
            snapshot=snap.to_dict(),
        )
        if monitor.has_too_many_failures():
            recorder.record(
                "api_failure", cycle_idx=poll_idx,
                snapshot={"strikes": monitor.api_failure_strikes},
            )
            break
        if snap.error:
            monitor.sleep_until_next_poll()
            continue

        # Posicao fechou server-side (TP/SL bateu)?
        if snap.open_position_qty == 0.0:
            exit_path = "tp_sl_server_side"
            exit_reason = "exited_by_tp_or_sl_server_side"
            exit_price = snap.mark_price
            exit_ms = int(snap.timestamp.timestamp() * 1000)
            recorder.record(
                "exit_detected", cycle_idx=poll_idx,
                snapshot={
                    "exit_path": exit_path,
                    "exit_reason": exit_reason,
                },
            )
            break

        # Avaliar ExitPolicy
        if reduce_only_enabled and snap.mark_price:
            position = build_open_position_state_from_snapshot(
                snap.positions[0] if snap.positions else {
                    "side": side
                },
                symbol=args.symbol,
                entry_price=entry_price,
                entry_time=entry_time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                position_size_usd=float(
                    plan.planned_blueprint.notional_usd,
                ),
            )

            from crypto_trading_bot.exchange.base_exchange import Candle
            virtual_candle = Candle(
                symbol=args.symbol, timeframe="15",
                timestamp=snap.timestamp,
                open=snap.mark_price, high=snap.mark_price,
                low=snap.mark_price, close=snap.mark_price,
                volume=0.0,
            )
            decision = resolver.resolve(
                position=position, candle=virtual_candle,
                candle_idx=poll_idx,
            )
            recorder.record(
                "exit_policy_evaluated", cycle_idx=poll_idx,
                snapshot={
                    "should_close": bool(decision.should_close),
                    "reason": decision.reason.value
                    if decision.should_close else None,
                    "requires_reduce_only":
                        bool(decision.requires_reduce_only),
                },
            )

            if decision.should_close and \
                    decision.reason.value in (
                        "time_limit", "opposite_signal", "emergency",
                    ):
                # Gate de close FASE 29
                close_gate_result = validate_phase29_close_gate(
                    has_open_position=True,
                    position_qty=snap.open_position_qty,
                    requested_close_qty=snap.open_position_qty,
                    exit_decision_requires_reduce_only=bool(
                        decision.requires_reduce_only,
                    ),
                    exit_decision_should_close=True,
                    safety_state="normal",
                    safety_halt_recommended=False,
                    close_orders_submitted_so_far=(
                        close_orders_submitted
                    ),
                    max_close_orders=int(args.max_close_orders),
                    operator_token=args.operator_token,
                )
                recorder.record(
                    "exit_gate_invoked", cycle_idx=poll_idx,
                    snapshot={
                        "approved": bool(close_gate_result.approved),
                        "blockers": list(
                            close_gate_result.blockers
                        ),
                        "dry_run": False,
                    },
                )
                if not close_gate_result.approved:
                    exit_path = "manual_fallback"
                    exit_reason = (
                        "close_gate_rejected: "
                        + "; ".join(close_gate_result.blockers)[:120]
                    )
                    break

                # Submete close
                close_result = close_wrapper.close_position(
                    symbol=args.symbol,
                    position_side=side,
                    position_qty=snap.open_position_qty,
                    dry_run=False,
                    confirm_demo_execution=True,
                )
                close_orders_submitted += 1
                recorder.record(
                    "exit_order_submitted", cycle_idx=poll_idx,
                    snapshot=close_result.to_dict(),
                )
                if close_result.success:
                    close_orders_filled += 1
                    exit_path = "reduce_only_close"
                    exit_reason = decision.reason.value
                    exit_price = snap.mark_price
                    exit_ms = int(snap.timestamp.timestamp() * 1000)
                else:
                    exit_path = "manual_fallback"
                    exit_reason = "reduce_only_close_failed"
                break

        monitor.sleep_until_next_poll()

    # Flat-check final via monitor polls
    final_snap = monitor.poll_once(poll_idx=max_polls)
    recorder.record(
        "position_snapshot",
        cycle_idx=max_polls, snapshot=final_snap.to_dict(),
    )
    flat = validate_flat(
        positions=final_snap.positions,
        open_orders=final_snap.open_orders,
        conditional_orders=final_snap.conditional_orders,
    )
    flat_check_dict = flat.to_dict()
    recorder.record(
        "flat_check_done", snapshot=flat_check_dict,
    )

    if not flat.is_flat and exit_path == "none":
        exit_path = "manual_fallback"
        exit_reason = "position_open_after_monitor"

    # P&L
    pnl_result = None
    if exit_path != "none" and exit_price is not None:
        try:
            pnl_result = pnl_tracker.fetch_pnl(
                symbol=args.symbol,
                entry_price=entry_price,
                exit_price=exit_price,
                qty=qty,
                side=side,
                entry_ms=int(entry_time.timestamp() * 1000),
                exit_ms=exit_ms,
                exit_reason=exit_reason,
            )
            recorder.record(
                "pnl_recorded",
                snapshot=pnl_result.to_dict(),
            )
        except Exception:  # noqa: BLE001
            pnl_result = None

    # --- FASE 29 Acceptance Polish: resolver verdict canonico + scenario ---
    from crypto_trading_bot.demo_endurance import Demo30MinVerdict
    from crypto_trading_bot.demo_session_execution.outcome import (
        RecommendedNextAction,
    )

    flat_is_flat = bool(flat.is_flat)
    exited = exit_path in ("tp_sl_server_side", "reduce_only_close")
    clean = (
        exited
        and flat_is_flat
        and outcome.open_positions_count == 0
        and not outcome.manual_review_required
        and not outcome.safety_halt_recommended
    )

    if clean:
        # Cenario A_clean - Demo FINALIZADA (verdict canonico).
        final_verdict = Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN
        final_rec = RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
        demo_finalized = True
        scenario = "A_clean"
    else:
        # Cenario C_manual - encerra sessao mas NAO finaliza.
        final_verdict = Demo30MinVerdict.MANUAL_REVIEW_REQUIRED
        final_rec = RecommendedNextAction.MANUAL_REVIEW_REQUIRED
        demo_finalized = False
        scenario = "C_manual"

    # Atualiza outcome (replace garante imutabilidade).
    new_outcome = replace(
        outcome,
        verdict=final_verdict,
        recommended_next_action=final_rec,
        exit_reason=exit_reason,
        exit_management_path=exit_path,
        close_orders_submitted=close_orders_submitted,
        close_orders_filled=close_orders_filled,
        open_positions_count=(
            0 if flat_is_flat else outcome.open_positions_count
        ),
        manual_review_required=(
            outcome.manual_review_required or not clean
        ),
        pnl_realized_usd=(
            pnl_result.realized_pnl_usd
            if pnl_result is not None else None
        ),
        pnl_source=(
            pnl_result.pnl_source
            if pnl_result is not None else None
        ),
        flat_check_result=flat_check_dict,
        demo_finalized=demo_finalized,
        demo_finalization_scenario=scenario,
    )
    recorder.record(
        "session_end",
        snapshot={
            "verdict": final_verdict.value,
            "demo_finalized": demo_finalized,
            "demo_finalization_scenario": scenario,
            "exit_management_path": exit_path,
        },
    )
    return new_outcome


def _run_wired_dry_run(*, args, readiness_dict: dict) -> int:
    """FASE 28 wired dry-run branch.

    Instancia client demo + provider real + executor real + registry
    OPT_IN + session_plan_factory + telemetry recorder, e roda
    Demo30MinRealRunner com apply_demo_real=False HARD-CODED.

    Toda chamada de gate recebe dry_run=True. NENHUMA ordem real eh
    enviada nesta fase.
    """
    # Lazy imports (avoid heavy load at module parse time)
    from datetime import datetime, timezone
    from crypto_trading_bot.demo_endurance import (
        build_default_planned_blueprint,
        build_demo_30_min_plan,
        build_live_blueprint_provider,
        build_live_demo_client,
        build_live_demo_executor,
        build_live_preflight_factory,
        build_provider_registry_with_opt_in,
        build_session_plan_factory,
        Demo30MinRealRunner,
        ProductionWiringError,
        SessionTelemetryRecorder,
        to_ui_snapshot,
    )

    # --- Step 1: wiring via production_wiring helpers ---
    try:
        client = build_live_demo_client()
    except ProductionWiringError as e:
        print(f"  ERROR wiring failed (client): {str(e)[:200]}")
        _footer()
        return 1
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR wiring failed (client init): "
            f"{type(e).__name__}: {str(e)[:200]}"
        )
        _footer()
        return 1

    # ModeGuard + RiskEngine reais (sem mexer).
    try:
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        from crypto_trading_bot.operational_safety.safety_state_machine \
            import SafetyStateMachine
        from crypto_trading_bot.operational_profile import (
            build_personal_profile,
        )
        mode_guard = ModeGuard()
        risk_engine = RiskEngine(initial_capital=float(args.capital))
        safety_machine = SafetyStateMachine()
        profile = build_personal_profile(
            account_size_usd=float(args.capital)
        )
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR runner deps init failed: "
            f"{type(e).__name__}: {str(e)[:160]}"
        )
        _footer()
        return 1

    try:
        registry = build_provider_registry_with_opt_in()
    except ProductionWiringError as e:
        print(f"  ERROR provider registry: {str(e)[:200]}")
        _footer()
        return 1

    # Preflight factory (read-only via FASE 22 helper).
    preflight_factory = build_live_preflight_factory(
        client=client, mode_guard=mode_guard, risk_engine=risk_engine,
        symbol=args.symbol, side="buy",
        leverage_target=1.0, target_take_profit_rr=2.0,
    )
    provider = build_live_blueprint_provider(
        preflight_factory=preflight_factory,
    )

    # --- Step 2: flat-check inicial obrigatorio (read-only) ---
    print("  Running initial preflight (read-only demo API)...")
    try:
        snapshot = provider.preflight()
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR preflight failed: "
            f"{type(e).__name__}: {str(e)[:160]}"
        )
        _footer()
        return 1
    bp_live = snapshot.blueprint
    flat_blockers = []
    if int(bp_live.open_positions_count) > 0:
        flat_blockers.append(
            f"open_positions_count={bp_live.open_positions_count} > 0"
        )
    if int(bp_live.open_orders_count) > 0:
        flat_blockers.append(
            f"open_orders_count={bp_live.open_orders_count} > 0"
        )
    if int(bp_live.conditional_orders_count) > 0:
        flat_blockers.append(
            f"conditional_orders_count="
            f"{bp_live.conditional_orders_count} > 0"
        )
    if flat_blockers:
        for b in flat_blockers:
            print(f"  [BLOCKER] flat-check: {b}")
        print(
            "  Initial flat-check failed. Visit api-demo.bybit.com UI, "
            "close positions/cancel orders, then re-run."
        )
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "real_flags_set": True,
            "execution_declined": "flat_check_failed",
            "flat_blockers": flat_blockers,
        })
        _footer()
        return 1

    print(
        f"  Flat-check OK. blueprint_id={snapshot.blueprint_id} "
        f"ttl_remaining={snapshot.ttl_remaining()}s"
    )
    print(
        f"    side={bp_live.side} entry={bp_live.entry_price} "
        f"stop={bp_live.stop_loss} tp={bp_live.take_profit}"
    )
    print(
        f"    qty={bp_live.qty} notional={bp_live.notional_usd} "
        f"wallet={bp_live.wallet_balance_usd}"
    )

    # --- Step 3: construir Demo30MinPlan FASE 26 + telemetry recorder ---
    runner_plan = build_demo_30_min_plan(
        symbol=args.symbol,
        strategy_name=args.strategy,
        max_orders=int(args.max_orders),
        max_session_minutes=int(args.max_minutes),
        risk_thresholds_snapshot={
            "max_daily_loss_pct": 0.05,
            "max_total_loss_pct": 0.10,
        },
        planned_blueprint=bp_live,
        operator_token=args.operator_token,
        live_blueprint_id=snapshot.blueprint_id,
    )
    recorder = SessionTelemetryRecorder(
        operator_token=args.operator_token,
    )

    # --- Step 4: market_data_callable read-only via client.get_candles ---
    def _market_data(*, symbol, timeframe, limit):
        try:
            return client.get_candles(
                symbol=symbol, timeframe=timeframe, limit=limit,
            )
        except Exception as e:  # noqa: BLE001
            # Propaga: runner conta como api_failure.
            raise

    # --- Step 5: executor + session_plan_factory + gate (FASE 22) ---
    # Reuse mode_guard + risk_engine already validated above.
    # FASE 28 wired dry-run: gate FASE 22 will receive dry_run=True
    # (hard-coded), so confirm_demo_execution can stay False here.
    executor = build_live_demo_executor(
        client=client,
        mode_guard=mode_guard,
        risk_engine=risk_engine,
        confirm_demo_execution=False,
    )
    session_plan_factory = build_session_plan_factory()

    # --- Step 6: runner com apply_demo_real=False HARD-CODED ---
    _APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28 = False  # NOT overridable in FASE 28
    runner = Demo30MinRealRunner(
        plan=runner_plan,
        provider=provider,
        risk_engine=risk_engine,
        safety_machine=safety_machine,
        mode_guard=mode_guard,
        provider_registry=registry,
        effective_risk_config=risk_engine.config if hasattr(
            risk_engine, "config",
        ) else None,
        profile=profile,
        operator_token=args.operator_token,
        market_data_callable=_market_data,
        demo_executor_factory=lambda: executor,
        session_plan_factory=session_plan_factory,
        cycle_interval_seconds=float(args.cycle_interval_seconds),
        apply_demo_real=_APPLY_DEMO_REAL_HARD_DEFAULT_PHASE28,
        notes=args.notes,
        telemetry_recorder=recorder,
    )

    print()
    print("  Starting wired dry-run runner (max 30 min, max 1 order)...")
    try:
        outcome = runner.run_real()
    except KeyboardInterrupt:
        print("  Runner interrupted by operator. No order was sent.")
        _maybe_write_output(args.output, {
            "readiness": readiness_dict,
            "real_flags_set": True,
            "execution_declined": "operator_interrupt",
        })
        _footer()
        return 1

    snap = to_ui_snapshot(
        plan=runner_plan, outcome=outcome,
        blueprint_age_seconds=snapshot.age_seconds,
        blueprint_ttl_remaining=snapshot.ttl_remaining(),
    )

    print()
    print("  Demo30Min REAL ENDURANCE (wired dry-run) outcome:")
    print(f"    mode:                     {snap['stage_info']['mode']}")
    print(f"    real_vs_dry_run:          "
          f"{snap['stage_info']['real_vs_dry_run']}")
    print(f"    apply_demo_real_invoked:  "
          f"{snap['verdict']['apply_demo_real_invoked']}")
    print(f"    blueprint_id:             "
          f"{snap['plan'].get('blueprint_id')}")
    print(f"    session_id:               "
          f"{snap['stage_info']['session_id']}")
    print(f"    cycles_completed:         "
          f"{snap['session']['cycles_completed']}")
    print(f"    orders_submitted:         "
          f"{snap['session']['orders_submitted']}")
    print(f"    orders_filled:            "
          f"{snap['session']['orders_filled']}")
    print(f"    open_positions_count:     "
          f"{snap['session']['open_positions_count']}")
    print(f"    safety_state:             {snap['safety']['safety_state']}")
    print(f"    verdict:                  {snap['verdict']['verdict']}")
    print(f"    recommended_next_action:  "
          f"{snap['verdict']['recommended_next_action']}")
    print()
    print(
        "  No real order was sent. PHASE 28 WIRED DRY-RUN COMPLETE. "
        "Pipeline end-to-end validated against demo API read-only. "
        "First real order requires FASE 29 authorization."
    )

    _maybe_write_output(args.output, {
        "readiness": readiness_dict,
        "real_flags_set": True,
        "wired_dry_run": True,
        "apply_demo_real_invoked": bool(outcome.apply_demo_real_invoked),
        "plan": runner_plan.to_dict(),
        "outcome": outcome.to_dict(),
        "ui_snapshot": snap,
    })

    # Telemetry output (separate file).
    if args.telemetry_output:
        try:
            recorder.to_jsonl_file(args.telemetry_output)
            print(
                f"  Telemetry written to: {args.telemetry_output}"
            )
        except ValueError as e:
            print(
                f"  ERROR telemetry path rejected: {str(e)[:200]}"
            )

    _footer()
    # Exit code policy:
    #   0 - passed_zero_trades / passed_one_trade
    #   2 - failed / manual_review / safety_halt
    #   1 - not_executable / planned_dry_run_blocked
    if outcome.verdict.value in ("passed_zero_trades",
                                  "passed_one_trade"):
        return 0
    if outcome.verdict.value in ("failed", "manual_review_required",
                                  "safety_halt_ack_needed"):
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
