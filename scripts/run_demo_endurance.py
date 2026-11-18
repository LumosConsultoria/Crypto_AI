#!/usr/bin/env python
"""
run_demo_endurance.py - Demo REAL-TIME curta/longa com prazo definido
=======================================================================
FASE 30. ASCII-only. WIRED DRY-RUN: gate dry_run=True SEMPRE;
orders_submitted=0 SEMPRE; would_orders contabiliza ordem possivel.
NENHUMA ordem real nesta fase.

MODOS:
    --real-time      sleep REAL entre ciclos (demo acompanha mercado).
                     Demo de 30 min dura 30 minutos reais.
    (sem flag)       time-compressed INTENCIONAL (rapido; pesquisa).

    --duration-minutes 30|60|120     demo curta
    --duration-days 1|3|7            demo longa (daily summary +
                                     hourly snapshot obrigatorios)

    NAO EXISTE --no-max-time. Toda demo tem inicio e fim definidos.

FEEDS:
    default          wired demo (read-only API; exige credenciais demo)
    --synthetic-feed candles sinteticos offline (research; zero rede)

PERFIL (FASE 31): --profile resolve TODAS as permissoes/limites.
Nada de capital/risco/lado/estrategia hardcoded ignorando perfil.

GATES INDEPENDENTES (nenhum implica outro):
    DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED   (short)
    DEMO_ALLOW_MULTI_ORDER_PER_SESSION        (multi-order)
    DEMO_ALLOW_AI_MANUAL_REVIEW               (AI manual review)
    ENABLE_PREDICTION_MARKET_CONTEXT          (prediction context)

Exit codes: 0 ok | 1 input/preflight bloqueado | 2 manual review.
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


def _banner() -> None:
    print()
    print("=" * 72)
    print("  DEMO ENDURANCE REAL-TIME (FASE 30) - WIRED DRY-RUN")
    print("  gate dry_run=True | orders_submitted=0 | NO real order")
    print("  NO mainnet/live. Paper default. Demo opt-in/gated.")
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
            "Demo endurance real-time curta/longa com prazo definido "
            "(FASE 30, wired dry-run)."
        ),
    )
    parser.add_argument("--profile", type=str, required=True)
    parser.add_argument("--capital", type=float, required=True)
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument(
        "--strategy", type=str, default="trend_pullback",
    )
    parser.add_argument("--duration-minutes", type=int, default=None)
    parser.add_argument("--duration-days", type=int, default=None)
    parser.add_argument(
        "--cycle-interval-seconds", type=float, default=60.0,
    )
    parser.add_argument(
        "--real-time", action="store_true",
        help="Sleep REAL entre ciclos (demo acompanha o mercado).",
    )
    parser.add_argument(
        "--demo-only", action="store_true",
        help="Afirma ambiente demo; nunca mainnet/live.",
    )
    parser.add_argument("--operator-token", type=str, required=True)
    parser.add_argument("--output", type=str, default="")
    parser.add_argument("--telemetry-output", type=str, default="")
    # Limites (None = derivar do perfil; explicito = override operador)
    parser.add_argument("--max-orders-per-day", type=int, default=None)
    parser.add_argument(
        "--max-orders-per-session", type=int, default=None,
    )
    parser.add_argument("--max-open-positions", type=int, default=None)
    parser.add_argument(
        "--max-daily-loss-pct", type=float, default=None,
    )
    parser.add_argument(
        "--max-total-loss-pct", type=float, default=None,
    )
    parser.add_argument(
        "--max-consecutive-losses", type=int, default=None,
    )
    parser.add_argument("--max-api-failures", type=int, default=None)
    parser.add_argument(
        "--max-stale-data-seconds", type=float, default=None,
    )
    parser.add_argument(
        "--flat-check-interval-minutes", type=int, default=None,
    )
    parser.add_argument(
        "--require-sl-tp", action="store_true", default=True,
    )
    # Ecossistema (FASE 32/34)
    parser.add_argument(
        "--enable-ai-assist", action="store_true",
        help="Habilita IA consultiva (MockAIAdvisor offline).",
    )
    parser.add_argument(
        "--enable-prediction-context", action="store_true",
        help=(
            "Habilita prediction context (exige tambem perfil + ENV "
            "ENABLE_PREDICTION_MARKET_CONTEXT)."
        ),
    )
    parser.add_argument(
        "--prediction-provider", type=str, default="polymarket",
    )
    parser.add_argument(
        "--prediction-context-mode", type=str, default="read_only",
        choices=("read_only", "advisory"),
    )
    # Modo OBSERVACAO dry-run: continua apos would-order
    parser.add_argument(
        "--continue-after-would-order", action="store_true",
        help=(
            "Modo observacao (dry-run APENAS): continua registrando "
            "would-orders apos a primeira, sem ordem real, sem abrir "
            "posicao, sem tocar gates reais. Encerra por duration ou "
            "--max-would-orders."
        ),
    )
    parser.add_argument(
        "--max-would-orders", type=int, default=None,
        help=(
            "Teto de would-orders no modo observacao (exige "
            "--continue-after-would-order)."
        ),
    )
    # ===================================================================
    # FASE 30.2 - MULTI-ORDEM REAL DEMO SEQUENCIAL (gated)
    # ===================================================================
    parser.add_argument(
        "--execute-demo-real-multi", action="store_true",
        help=(
            "FASE 30.2: executa ordens REAIS demo em sequencia "
            "(1 posicao por vez). Exige flags redundantes + gates ENV "
            "+ frase + Y."
        ),
    )
    parser.add_argument(
        "--confirm-demo-real-multi", action="store_true",
    )
    parser.add_argument(
        "--first-real-demo-multi-order-fase30", action="store_true",
    )
    parser.add_argument(
        "--max-real-orders", type=int, default=None,
        help="Obrigatorio com --execute-demo-real-multi; cap [1,3].",
    )
    parser.add_argument(
        "--require-flat-before-next-order", action="store_true",
        default=True,
        help="Default ON: nova entrada so com flat-check limpo.",
    )
    parser.add_argument(
        "--disable-scale-in", action="store_true", default=True,
        help="Default ON: scale-in proibido nesta fase.",
    )
    parser.add_argument(
        "--disable-auto-reversal", action="store_true", default=True,
        help="Default ON: reversao automatica proibida nesta fase.",
    )
    # Feed offline para pesquisa/smoke (zero rede)
    parser.add_argument(
        "--synthetic-feed", action="store_true",
        help="Candles sinteticos offline (research; zero rede).",
    )
    # FASE 36 Bloco L - Operator Inputs (obrigatorio p/ execucao real)
    parser.add_argument(
        "--inputs-store", type=str, default="",
        help=(
            "Store JSON de Operator Inputs (run_operator_inputs.py). "
            "OBRIGATORIO com --execute-demo-real-multi."
        ),
    )
    # Demo longa: validacao da sessao anterior
    parser.add_argument("--previous-report", type=str, default="")
    parser.add_argument("--previous-telemetry", type=str, default="")
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="Roda apenas o preflight e sai.",
    )

    args = parser.parse_args(argv)
    _banner()

    # --- validacoes basicas ---
    if args.capital <= 0:
        print("  ERROR --capital deve ser > 0")
        _footer()
        return 1
    if not args.operator_token.strip():
        print("  ERROR --operator-token nao pode ser vazio")
        _footer()
        return 1
    has_min = args.duration_minutes is not None
    has_days = args.duration_days is not None
    if has_min == has_days:
        print(
            "  ERROR informe EXATAMENTE uma duracao: "
            "--duration-minutes XOR --duration-days "
            "(execucao indefinida nao existe; sem --no-max-time)"
        )
        _footer()
        return 1
    if not args.demo_only:
        print(
            "  ERROR --demo-only obrigatorio (afirma ambiente demo; "
            "mainnet/live bloqueados)"
        )
        _footer()
        return 1
    if args.max_would_orders is not None:
        if not args.continue_after_would_order:
            print(
                "  ERROR --max-would-orders exige "
                "--continue-after-would-order (modo observacao)"
            )
            _footer()
            return 1
        if args.max_would_orders < 1:
            print("  ERROR --max-would-orders deve ser >= 1")
            _footer()
            return 1

    # --- FASE 30.2: rejeicoes do modo real multi-ordem ---
    real_multi_any = (
        args.execute_demo_real_multi
        or args.confirm_demo_real_multi
        or args.first_real_demo_multi_order_fase30
    )
    real_multi_all = (
        args.execute_demo_real_multi
        and args.confirm_demo_real_multi
        and args.first_real_demo_multi_order_fase30
    )
    if real_multi_any and not real_multi_all:
        print(
            "  ERROR execucao real multi exige TODAS as flags: "
            "--execute-demo-real-multi --confirm-demo-real-multi "
            "--first-real-demo-multi-order-fase30"
        )
        _footer()
        return 1
    if args.execute_demo_real_multi:
        if args.continue_after_would_order:
            print(
                "  ERROR --execute-demo-real-multi e incompativel com "
                "--continue-after-would-order (observation_mode "
                "proibido em execucao real)"
            )
            _footer()
            return 1
        if args.synthetic_feed:
            print(
                "  ERROR --execute-demo-real-multi e incompativel com "
                "--synthetic-feed"
            )
            _footer()
            return 1
        if not args.real_time:
            print(
                "  ERROR --execute-demo-real-multi exige --real-time"
            )
            _footer()
            return 1
        if args.max_real_orders is None:
            print(
                "  ERROR --execute-demo-real-multi exige "
                "--max-real-orders N"
            )
            _footer()
            return 1
        if not (1 <= args.max_real_orders <= 3):
            print(
                "  ERROR --max-real-orders deve estar em [1, 3] "
                "(cap seguro inicial; valores maiores exigem gate "
                f"futuro especifico); recebido {args.max_real_orders}"
            )
            _footer()
            return 1
        # ---- FASE 36 Bloco L: Operator Inputs OBRIGATORIOS ----
        # Validado AQUI (offline, antes de qualquer wiring de rede):
        # campo obrigatorio ausente => blocked_missing_operator_input.
        from crypto_trading_bot.operator_inputs import (
            OperatorInputStore,
            build_default_schema,
            build_required_inputs_for_demo_report,
        )
        if not args.inputs_store.strip():
            print(
                "  ERROR execucao real exige --inputs-store "
                "(Operator Inputs; use scripts/run_operator_inputs.py)"
            )
            _footer()
            return 1
        try:
            _inputs_store = OperatorInputStore(args.inputs_store)
        except ValueError as e:
            print(f"  ERROR inputs store: {e}")
            _footer()
            return 1
        _inputs_report = build_required_inputs_for_demo_report(
            schema=build_default_schema(), store=_inputs_store,
        )
        if _inputs_report["blocks_execution"]:
            print(
                "  BLOCKED blocked_missing_operator_input: campos "
                "obrigatorios ausentes/invalidos/nao confirmados:"
            )
            for m in _inputs_report["missing"][:20]:
                if m["blocks_execution"]:
                    print(
                        f"    - {m['input_id']}: {m['status']} "
                        f"({m['reason'][:60]})"
                    )
            _maybe_write_output(args.output, {
                "phase": "36",
                "execution_declined":
                    "blocked_missing_operator_input",
                "required_inputs_report": _inputs_report,
            })
            _footer()
            return 1
        print(
            "  Operator Inputs OK (nenhum campo obrigatorio "
            "faltante)."
        )

    # --- lazy imports ---
    from crypto_trading_bot.demo_endurance import (
        DemoEnduranceRunner,
        DurationSpec,
        EnduranceLimits,
        SessionTelemetryRecorder,
        demo_credentials_present_from_env,
        validate_endurance_preflight,
    )
    from crypto_trading_bot.operational_profile import (
        SUPPORTED_PROFILE_NAMES,
        derive_endurance_limits,
        resolve_profile,
    )

    # --- perfil (FASE 31): fonte unica de permissoes ---
    try:
        profile = resolve_profile(args.profile, capital=args.capital)
    except ValueError as e:
        print(f"  ERROR profile: {str(e)[:200]}")
        print(f"  Perfis suportados: {list(SUPPORTED_PROFILE_NAMES)}")
        _footer()
        return 1

    # --- duracao com prazo definido ---
    try:
        duration = DurationSpec(
            duration_minutes=args.duration_minutes,
            duration_days=args.duration_days,
            cycle_interval_seconds=float(args.cycle_interval_seconds),
        )
    except ValueError as e:
        print(f"  ERROR duration: {str(e)[:200]}")
        _footer()
        return 1

    # --- limites: perfil -> overrides explicitos da CLI ---
    base_limits = derive_endurance_limits(profile)
    limit_overrides = {}
    for cli_name, field in (
        ("max_orders_per_day", "max_orders_per_day"),
        ("max_orders_per_session", "max_orders_per_session"),
        ("max_open_positions", "max_open_positions"),
        ("max_daily_loss_pct", "max_daily_loss_pct"),
        ("max_total_loss_pct", "max_total_loss_pct"),
        ("max_consecutive_losses", "max_consecutive_losses"),
        ("max_api_failures", "max_api_failures"),
        ("max_stale_data_seconds", "max_stale_data_seconds"),
        ("flat_check_interval_minutes", "flat_check_interval_minutes"),
    ):
        val = getattr(args, cli_name)
        if val is not None:
            limit_overrides[field] = val
    try:
        limits = EnduranceLimits(
            **{**base_limits.to_dict(), **limit_overrides},
        )
    except ValueError as e:
        print(f"  ERROR limits: {str(e)[:200]}")
        _footer()
        return 1

    print(f"  Profile:      {profile.name}")
    print(f"  Capital:      {args.capital}")
    print(f"  Symbol:       {args.symbol}")
    print(f"  Strategy:     {args.strategy}")
    print(f"  Duration:     {duration!r}")
    print(f"  Real-time:    {args.real_time} "
          f"(time_compressed={not args.real_time})")
    print(f"  Feed:         "
          f"{'synthetic (offline)' if args.synthetic_feed else 'demo wired'}")
    print(f"  Limits:       {limits.to_dict()}")
    print()

    # --- wiring do feed ---
    mode_guard = None
    flat_check_callable = None
    endpoint_url = ""
    if args.synthetic_feed:
        market_data_callable = _build_synthetic_feed(args.symbol)
        provider_id = "paper"
        environment = "paper"
        credentials_present = True  # n/a offline
        api_probe = None
        counts = (0, 0, 0)
        print(
            "  NOTE synthetic feed: research/offline. NAO representa "
            "mercado real."
        )
    else:
        try:
            from crypto_trading_bot.core.mode_guard import ModeGuard
            from crypto_trading_bot.demo_endurance import (
                build_live_demo_client,
            )
            mode_guard = ModeGuard()
            client = build_live_demo_client()
        except Exception as e:  # noqa: BLE001
            print(
                f"  ERROR wiring demo client: {type(e).__name__}: "
                f"{str(e)[:200]}"
            )
            _footer()
            return 1

        def market_data_callable(*, symbol, timeframe, limit):
            return client.get_candles(
                symbol=symbol, timeframe=timeframe, limit=limit,
            )

        provider_id = "bybit_demo_linear"
        environment = "demo"
        credentials_present = demo_credentials_present_from_env()
        api_probe = None
        counts = (0, 0, 0)  # preflight read-only abaixo refina
        try:
            from crypto_trading_bot.config.exchange_config import (
                get_exchange_config,
            )
            endpoint_url = str(get_exchange_config().rest_url)
        except Exception:  # noqa: BLE001
            endpoint_url = ""
        try:
            from crypto_trading_bot.demo_endurance import (
                build_live_blueprint_provider,
                build_live_preflight_factory,
            )
            from crypto_trading_bot.risk.risk_engine import RiskEngine
            _pf_risk = RiskEngine(initial_capital=float(args.capital))
            pf_factory = build_live_preflight_factory(
                client=client, mode_guard=mode_guard,
                risk_engine=_pf_risk, symbol=args.symbol, side="buy",
                leverage_target=1.0, target_take_profit_rr=2.0,
            )
            provider = build_live_blueprint_provider(
                preflight_factory=pf_factory,
            )
            snapshot = provider.preflight()
            bp = snapshot.blueprint
            counts = (
                int(bp.open_positions_count),
                int(bp.open_orders_count),
                int(bp.conditional_orders_count),
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"  ERROR demo preflight (read-only): "
                f"{type(e).__name__}: {str(e)[:200]}"
            )
            _footer()
            return 1

    # --- preflight endurance (FASE 30) ---
    is_long = duration.is_long
    preflight = validate_endurance_preflight(
        open_positions_count=counts[0],
        open_orders_count=counts[1],
        conditional_orders_count=counts[2],
        safety_state="normal",
        provider_id=provider_id,
        environment=environment,
        demo_credentials_present=credentials_present,
        api_probe=api_probe,
        mode_guard=mode_guard,
        endpoint_url=endpoint_url,
        require_previous_report=bool(
            is_long and args.previous_report
        ),
        previous_report_path=args.previous_report,
        require_previous_telemetry=bool(
            is_long and args.previous_telemetry
        ),
        previous_telemetry_path=args.previous_telemetry,
    )
    print(f"  Preflight:    approved={preflight.approved}")
    for b in preflight.blockers:
        print(f"    [BLOCKER] {b}")
    if is_long and not args.previous_report:
        print(
            "  WARN demo LONGA sem --previous-report: nova demo longa "
            "so deve iniciar apos validacao limpa da anterior."
        )
    if not preflight.approved:
        print("  Preflight BLOQUEADO: manual review obrigatorio.")
        _maybe_write_output(args.output, {
            "preflight": preflight.to_dict(),
            "profile": profile.to_dict(),
            "duration": duration.to_dict(),
        })
        _footer()
        return 1
    if args.preflight_only:
        _maybe_write_output(args.output, {
            "preflight": preflight.to_dict(),
            "profile": profile.to_dict(),
            "duration": duration.to_dict(),
        })
        _footer()
        return 0

    # --- componentes do pipeline ---
    try:
        from crypto_trading_bot.challenge_readiness.strategy_factory \
            import build_strategy_spec
        from crypto_trading_bot.data.feature_engine import FeatureEngine
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        spec = build_strategy_spec(args.strategy)
        strategy = spec.factory(dict(spec.default_config))
        feature_engine = FeatureEngine.from_strategy_spec(spec)
        risk_engine = RiskEngine(initial_capital=float(args.capital))
    except Exception as e:  # noqa: BLE001
        print(
            f"  ERROR pipeline deps: {type(e).__name__}: {str(e)[:200]}"
        )
        _footer()
        return 1

    # IA consultiva (FASE 32) - Mock deterministico offline.
    ai_support = None
    if args.enable_ai_assist:
        from crypto_trading_bot.ai_assistant import (
            AIDecisionSupport, MockAIAdvisor,
        )
        ai_support = AIDecisionSupport(advisor=MockAIAdvisor())
        print("  AI assist:    enabled (MockAIAdvisor, consultivo)")

    # Prediction context (FASE 34) - read-only; sem fetcher = unavailable.
    prediction_provider = None
    if args.enable_prediction_context:
        from datetime import datetime, timezone
        from crypto_trading_bot.prediction_markets import (
            PolymarketReadonlyClient, build_prediction_context,
        )
        _pm_client = PolymarketReadonlyClient(raw_fetcher=None)

        def prediction_provider():
            events = _pm_client.fetch_events()
            if not events:
                return None
            return build_prediction_context(
                events=events,
                mode=args.prediction_context_mode,
                fetched_at=datetime.now(timezone.utc),
                max_age_seconds=float(
                    profile.max_prediction_context_age_seconds
                ),
            )
        print(
            "  Prediction:   requested (read-only; exige perfil + ENV "
            "ENABLE_PREDICTION_MARKET_CONTEXT)"
        )

    recorder = SessionTelemetryRecorder(
        operator_token=args.operator_token,
    )

    # ===================================================================
    # FASE 30.2 - caminho REAL multi-ordem (frase + Y + gate + wiring)
    # ===================================================================
    real_kwargs = {}
    if args.execute_demo_real_multi:
        from crypto_trading_bot.demo_endurance import (
            build_live_demo_executor,
            build_position_monitor,
            build_provider_registry_with_opt_in,
            build_real_trade_lifecycle,
            expected_phrase_30_2,
            prompt_yes_or_abort,
            TTYRequired,
            validate_flat,
            validate_phase30_2_real_multi_gate,
        )
        expected = expected_phrase_30_2(int(args.max_real_orders))
        print()
        print("  " + "!" * 68)
        print("  FASE 30.2 - REAL DEMO MULTI-ORDER (SEQUENCIAL)")
        print(
            f"  Ate {args.max_real_orders} ordens REAIS em "
            "api-demo.bybit.com. 1 posicao por vez; SL/TP "
            "obrigatorios; flat-check + P&L por trade."
        )
        print("  Digite EXATAMENTE a frase (case-sensitive):")
        print(f"    {expected}")
        print("  " + "!" * 68)
        try:
            phrase_entered = input("  Phrase: ").strip()
        except (EOFError, KeyboardInterrupt):
            phrase_entered = ""
        if phrase_entered != expected:
            print("  ERROR phrase mismatch. Nenhuma ordem enviada.")
            _footer()
            return 1
        try:
            confirmed = prompt_yes_or_abort(
                "  FINAL CONFIRMATION - Type Y to enable real demo "
                "multi-order execution: ",
                timeout_seconds=60.0, assume_no=False,
            )
        except TTYRequired as e:
            print(f"  ERROR {e}")
            _footer()
            return 1
        if not confirmed:
            print("  Confirmacao recusada. Nenhuma ordem enviada.")
            _footer()
            return 1

        gate30 = validate_phase30_2_real_multi_gate(
            profile=profile,
            max_real_orders=int(args.max_real_orders),
            phrase_confirmation=phrase_entered,
            flag_execute_demo_real_multi=True,
            flag_confirm_demo_real_multi=bool(
                args.confirm_demo_real_multi,
            ),
            flag_first_real_demo_multi_order_fase30=bool(
                args.first_real_demo_multi_order_fase30,
            ),
            prompt_y_confirmed=bool(confirmed),
            operator_token=args.operator_token,
            tty_present=True,
            real_time=bool(args.real_time),
            demo_only=bool(args.demo_only),
            observation_mode=bool(args.continue_after_would_order),
            synthetic_feed=bool(args.synthetic_feed),
        )
        if not gate30.approved:
            print("  ERROR gate FASE 30.2 rejeitado:")
            for b in gate30.blockers:
                print(f"    - {b}")
            _maybe_write_output(args.output, {
                "phase": "30.2",
                "gate_result": gate30.to_dict(),
                "execution_declined": "gate_phase30_2_rejected",
            })
            _footer()
            return 1

        try:
            from crypto_trading_bot.operational_safety \
                .safety_state_machine import SafetyStateMachine
            safety_machine = SafetyStateMachine()
            registry = build_provider_registry_with_opt_in()
            executor = build_live_demo_executor(
                client=client, mode_guard=mode_guard,
                risk_engine=risk_engine,
                confirm_demo_execution=True,
            )
            lifecycle = build_real_trade_lifecycle(
                client=client,
                executor=executor,
                provider=provider,
                risk_engine=risk_engine,
                safety_machine=safety_machine,
                mode_guard=mode_guard,
                provider_registry=registry,
                profile=profile,
                effective_risk_config=(
                    risk_engine.config
                    if hasattr(risk_engine, "config") else None
                ),
                operator_token=args.operator_token,
                symbol=args.symbol,
                strategy_name=args.strategy,
                max_monitor_minutes=max(
                    1, int(duration.total_wall_clock_minutes),
                ),
                poll_interval_seconds=float(
                    args.cycle_interval_seconds,
                ),
                telemetry_emit=lambda et, **snap: recorder.record(
                    et, snapshot=snap,
                ),
                notes=f"fase30.2 operator={args.operator_token[:8]}",
            )
            _flat_monitor = build_position_monitor(
                client=client, symbol=args.symbol,
                poll_interval_seconds=float(
                    args.cycle_interval_seconds,
                ),
                max_monitor_minutes=1,
            )
            _flat_poll_counter = {"n": 0}

            def flat_check_callable():
                _flat_poll_counter["n"] += 1
                snap = _flat_monitor.poll_once(
                    poll_idx=_flat_poll_counter["n"],
                )
                flat = validate_flat(
                    positions=list(
                        getattr(snap, "positions", []) or [],
                    ),
                    open_orders=list(
                        getattr(snap, "open_orders", []) or [],
                    ),
                    conditional_orders=list(
                        getattr(snap, "conditional_orders", [])
                        or [],
                    ),
                )
                return flat.to_dict()
        except Exception as e:  # noqa: BLE001
            print(
                f"  ERROR wiring real multi: {type(e).__name__}: "
                f"{str(e)[:200]}"
            )
            _footer()
            return 1

        real_kwargs = {
            "execute_real_multi": True,
            "max_real_orders": int(args.max_real_orders),
            "real_trade_lifecycle": lifecycle,
            "require_flat_before_next_order": bool(
                args.require_flat_before_next_order,
            ),
        }
        flat_check_callable_ref = flat_check_callable
        print(
            "  REAL MULTI-ORDER ENABLED: ate "
            f"{args.max_real_orders} ordens reais sequenciais "
            "(scale-in OFF; auto-reversal OFF)."
        )
    else:
        flat_check_callable_ref = flat_check_callable

    try:
        runner = DemoEnduranceRunner(
            profile=profile,
            duration=duration,
            limits=limits,
            symbol=args.symbol,
            strategy_name=args.strategy,
            operator_token=args.operator_token,
            market_data_callable=market_data_callable,
            feature_engine=feature_engine,
            strategy=strategy,
            risk_engine=risk_engine,
            gate_callable=None,  # dry-run: would-order sem gate real
            flat_check_callable=flat_check_callable_ref,
            prediction_context_provider=prediction_provider,
            ai_decision_support=ai_support,
            telemetry_recorder=recorder,
            real_time=bool(args.real_time),
            continue_after_would_order=bool(
                args.continue_after_would_order,
            ),
            max_would_orders=args.max_would_orders,
            **real_kwargs,
        )
    except (TypeError, ValueError) as e:
        print(f"  ERROR runner: {str(e)[:200]}")
        _footer()
        return 1

    if args.continue_after_would_order:
        cap = (
            args.max_would_orders
            if args.max_would_orders is not None else "sem teto"
        )
        print(
            "  OBSERVATION MODE: continua apos would-order "
            f"(max_would_orders={cap}); dry-run, zero ordem real."
        )

    if args.real_time:
        total_min = duration.total_wall_clock_minutes
        print(
            f"  Starting REAL-TIME session (~{total_min:.0f} min reais; "
            "Ctrl+C = operator_interrupted)..."
        )
    else:
        print("  Starting TIME-COMPRESSED session (rapido)...")
    print()

    outcome = runner.run()

    d = outcome.to_dict()
    print()
    print("  === DEMO ENDURANCE FINAL ===")
    keys = [
        "execution_mode", "ended_reason", "real_time_mode",
        "time_compressed", "cycles_completed", "expected_cycles",
        "elapsed_wall_clock_minutes", "signals_evaluated",
        "would_orders", "orders_submitted",
    ]
    if args.execute_demo_real_multi:
        keys += [
            "orders_filled", "trades_completed",
            "trades_closed_by_tp", "trades_closed_by_sl",
            "trades_closed_by_reduce_only", "trades_manual_review",
            "total_realized_pnl", "final_flat_check_passed",
        ]
    for key in keys:
        print(f"    {key}: {d[key]}")
    if args.execute_demo_real_multi:
        print(
            "  FASE 30.2 REAL MULTI-ORDER: verifique api-demo.bybit.com "
            "UI e o report/telemetry antes de nova sessao."
        )
    else:
        print(
            "  NOTE wired dry-run: would_orders simulam ordem "
            "possivel; orders_submitted=0 (nenhuma ordem real)."
        )

    _maybe_write_output(args.output, {
        "phase": "30",
        "preflight": preflight.to_dict(),
        "profile": profile.to_dict(),
        "duration": duration.to_dict(),
        "limits": limits.to_dict(),
        "outcome": d,
    })

    if args.telemetry_output:
        try:
            recorder.to_jsonl_file(args.telemetry_output)
            print(f"  Telemetry written to: {args.telemetry_output}")
        except ValueError as e:
            print(f"  ERROR telemetry: {str(e)[:200]}")

    _footer()
    if d["ended_reason"] in ("manual_review_required", "safety_halt",
                             "api_failure"):
        return 2
    return 0


def _build_synthetic_feed(symbol: str):
    """Feed sintetico offline (research). Timestamps sempre frescos."""
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    base = generate_trending_candles(
        n=200, base_price=60000.0, trend_pct_per_candle=0.001,
        volatility_pct=0.006, symbol=symbol, timeframe="15",
    )

    def feed(*, symbol, timeframe, limit):
        now = datetime.now(timezone.utc)
        n = len(base)
        return [
            replace(c, timestamp=now - timedelta(minutes=(n - i)))
            for i, c in enumerate(base[:limit])
        ]
    return feed


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
