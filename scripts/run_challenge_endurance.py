#!/usr/bin/env python
"""
run_challenge_endurance.py - Paper Endurance (FASE 23)
==========================================================
ASCII-only. Paper-only. NO network. NO order. NO secret printed.

Estagios:
    PAPER_30_MIN, PAPER_60_MIN, PAPER_1_DAY  -> EXECUTAVEIS
    DEMO_30_MIN_PLANNED, DEMO_60_MIN_PLANNED,
    DEMO_1_DAY_PLANNED                       -> PLANNED ONLY
                                                (saida com aviso, sem rede)

DEMO_* nao chama Bybit. Para demo real, use scripts/
run_bybit_demo_session_gated.py (Comando A + B) apos paper progression
aprovada (ver runbook FASE 22).

Uso:
    # --capital eh OBRIGATORIO. Sem default chumbado.
    python scripts/run_challenge_endurance.py \\
        --profile personal --capital 5000 \\
        --stage PAPER_30_MIN --symbol BTCUSDT

    python scripts/run_challenge_endurance.py \\
        --profile personal --capital 10000 \\
        --stage PAPER_30_MIN --symbol BTCUSDT \\
        --strategy trend_pullback \\
        --output reports/challenge_endurance_paper_30m.json

Exit codes:
    0 = endurance passed (paper) OR planned-only stage with --confirm-planned
    1 = invalid input, profile/risk_config inconsistency, readiness NOT_READY
    2 = endurance executed but FAILED (blockers reported)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


_PROFILE_CHOICES = (
    "personal", "prop_challenge", "hyrotrader_demo_template", "custom",
)
_STAGE_CHOICES = (
    "PAPER_30_MIN", "PAPER_60_MIN", "PAPER_1_DAY",
    "DEMO_30_MIN_PLANNED", "DEMO_60_MIN_PLANNED", "DEMO_1_DAY_PLANNED",
)


def _banner() -> None:
    print()
    print("=" * 72)
    print("  CHALLENGE ENDURANCE - PAPER ONLY (FASE 23)")
    print("  NO NETWORK. NO ORDER. NO SECRET. PAPER TRADER ONLY.")
    print("  DEMO_* stages are PLANNED ONLY (not executable here).")
    print("=" * 72)
    print()


def _footer() -> None:
    print()
    print("=" * 72)
    print("  END.")
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
            name="custom_endurance",
            description="Custom profile via run_challenge_endurance.py",
            account_size_usd=capital,
        )
    raise ValueError("unknown profile")


def _stage_from_arg(stage_arg: str):
    from crypto_trading_bot.challenge_readiness import ChallengeEnduranceStage
    return ChallengeEnduranceStage(stage_arg.lower())


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Challenge Endurance - paper-only progression runner. "
            "FASE 23. No network, no order, no secret."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=True,
    )
    parser.add_argument(
        "--stage", choices=_STAGE_CHOICES, required=True,
    )
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    # FASE 24 microfix: --capital obrigatorio. Sem default chumbado para
    # nao mascarar capital operacional do operador.
    parser.add_argument(
        "--capital", type=float, required=True,
        help="account_size_usd em USD do operador. Obrigatorio.",
    )
    parser.add_argument(
        "--virtual-cycle-seconds", type=float, default=60.0,
        help="Tempo virtual por ciclo no SessionRunner (default 60s).",
    )
    parser.add_argument(
        "--challenge-target-usd", type=float, default=None,
        help="KPI informativo. NUNCA bloqueia readiness/endurance.",
    )
    parser.add_argument(
        "--output", type=str, default="",
        help="Path opcional para gravar JSON do relatorio.",
    )
    parser.add_argument(
        "--readiness-only", action="store_true",
        help="So avalia readiness; nao roda endurance.",
    )
    # FASE 24: --strategy opcional habilita run operacional real (paper).
    parser.add_argument(
        "--strategy", type=str, default="",
        choices=("", "trend_pullback", "volatility_breakout"),
        help=(
            "Estrategia injetada no SessionRunner paper. Default vazio "
            "= preview_no_strategy (zero-trade preview). Para corrida "
            "operacional real em paper, escolha trend_pullback ou "
            "volatility_breakout."
        ),
    )
    # FASE 25: --feed e --signal-exercise. Defaults preservam comportamento
    # legado (mock_random_walk, sem signal_exercise).
    parser.add_argument(
        "--feed", type=str, default="mock_random_walk",
        choices=(
            "mock_random_walk", "synthetic_trending",
            "synthetic_ranging", "cache",
        ),
        help=(
            "Tipo de feed paper. Default mock_random_walk (legado). "
            "synthetic_* exige --signal-exercise e cenario controlado. "
            "cache eh leitura LOCAL APENAS (sem download)."
        ),
    )
    parser.add_argument(
        "--signal-exercise", action="store_true",
        help=(
            "Marca run como signal exercise (cenario controlado). "
            "Obrigatorio quando --feed != mock_random_walk. Ativa o "
            "PaperExitOrchestrator para SL/TP via candle.high/low. "
            "NUNCA eh evidencia de performance."
        ),
    )
    args = parser.parse_args(argv)

    _banner()

    if args.capital <= 0:
        print("  ERROR --capital must be > 0")
        _footer()
        return 1
    if not args.symbol.strip():
        print("  ERROR --symbol cannot be empty")
        _footer()
        return 1

    # FASE 25 - validacoes cruzadas feed / signal-exercise.
    feed_choice = args.feed
    feed_nonlegacy = feed_choice != "mock_random_walk"
    if feed_nonlegacy and not args.signal_exercise:
        print(
            f"  ERROR --feed {feed_choice} requires --signal-exercise "
            "(controlled scenario flag)"
        )
        _footer()
        return 1
    if args.signal_exercise and not feed_nonlegacy:
        print(
            "  ERROR --signal-exercise requires explicit --feed "
            "{synthetic_trending,synthetic_ranging,cache}"
        )
        _footer()
        return 1

    try:
        profile = _build_profile(args.profile, float(args.capital))
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR profile construction failed: {type(e).__name__}")
        _footer()
        return 1

    try:
        stage = _stage_from_arg(args.stage)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR invalid --stage: {type(e).__name__}")
        _footer()
        return 1

    from crypto_trading_bot.challenge_readiness import (
        ChallengeReadinessConfig,
        EnduranceReadinessRejected,
        StageNotExecutableInThisPhase,
        build_challenge_readiness_report,
        is_demo_planned_stage,
        is_paper_stage,
    )
    from crypto_trading_bot.config.risk_config import RiskConfig

    rc = RiskConfig()
    readiness_cfg = ChallengeReadinessConfig(
        target_stage=stage,
        symbol=args.symbol,
        challenge_target_usd=args.challenge_target_usd,
    )

    print(f"  Profile:        {profile.name}")
    print(f"  Target stage:   {stage.value}")
    print(f"  Symbol:         {args.symbol}")
    print(f"  Capital (USD):  {args.capital}")
    if args.challenge_target_usd is not None:
        print(f"  Challenge KPI:  {args.challenge_target_usd} "
              f"(informational only)")
    print()

    # Always evaluate readiness first.
    readiness = build_challenge_readiness_report(profile, rc, readiness_cfg)
    print(f"  Readiness:      {readiness.status.value}")
    print(f"  Errors:         {readiness.error_count}")
    print(f"  Warnings:       {readiness.warning_count}")
    if readiness.blockers:
        for b in readiness.blockers:
            tag = b.severity.upper()
            print(f"    [{tag}] {b.field_name}: {b.message}")
    print()

    if args.readiness_only:
        _maybe_write_output(args.output, readiness.to_dict())
        _footer()
        return 0 if readiness.is_ready else 1

    # If demo planned, surface and exit 0 (planned-only).
    if is_demo_planned_stage(stage):
        print("  Stage is PLANNED ONLY in FASE 23.")
        print("  No paper run, no demo execution.")
        print("  For demo real, use scripts/run_bybit_demo_session_gated.py")
        print("  (Comando A + B) after PAPER progression is approved.")
        print()
        report_dict = {
            "readiness": readiness.to_dict(),
            "endurance_executed": False,
            "reason": f"stage {stage.value} is PLANNED ONLY",
        }
        _maybe_write_output(args.output, report_dict)
        _footer()
        return 0

    if not is_paper_stage(stage):
        print("  ERROR stage is neither paper nor demo planned. Aborting.")
        _footer()
        return 1

    if not readiness.is_ready:
        print("  Readiness NOT_READY. Aborting endurance.")
        _maybe_write_output(args.output, readiness.to_dict())
        _footer()
        return 1

    from crypto_trading_bot.challenge_readiness import (
        ChallengeEnduranceResult,
        ChallengeEnduranceRunner,
        next_recommended_stage,
        get_stage_definition,
    )

    stage_def = get_stage_definition(stage)
    strategy_name_arg = args.strategy.strip()

    if not strategy_name_arg:
        # Modo preview: sem strategy. Resultado claramente identificado.
        print("  Mode: preview_no_strategy")
        print("  No strategy injected; this is NOT an operational paper")
        print("  validation. Pass --strategy {trend_pullback,"
              "volatility_breakout} to run operational paper.")

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        result = ChallengeEnduranceResult(
            stage=stage,
            mode="preview_no_strategy",
            strategy_name=None,
            profile_name=profile.name,
            account_size_usd=float(args.capital),
            symbol=args.symbol,
            duration_planned_minutes=stage_def.duration_minutes,
            cycles_completed=0,
            trades_opened=0,
            trades_closed=0,
            open_positions_end=0,
            pnl_realized=0.0,
            pnl_unrealized=0.0,
            max_drawdown_observed=0.0,
            max_daily_loss_observed=0.0,
            risk_violations_count=0,
            safety_events_count=0,
            blockers=(),
            warnings=(
                "preview_no_strategy: no strategy injected. Use --strategy "
                "to run operational paper. Preview NEVER counts as "
                "operational validation.",
            ),
            # Preview "passed" eh seguro porque mode separa de operacional.
            verdict="not_executable",
            # Preview NUNCA recomenda proximo estagio (nao validou nada).
            next_recommended_stage=None,
            challenge_target_progress_pct=None,
            final_safety_state="normal",
            stopped_reason="preview_no_strategy",
            started_at=now, ended_at=now,
        )
    else:
        # Modo operational_paper_run: instancia ChallengeEnduranceRunner
        # com strategy real. SessionRunner roda em paper.
        print(f"  Mode: operational_paper_run")
        print(f"  Strategy: {strategy_name_arg}")
        print(f"  Feed: {feed_choice}")
        if args.signal_exercise:
            print(
                "  signal_exercise=True (controlled scenario; "
                "NOT performance evidence)"
            )
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        try:
            spec = build_strategy_spec(strategy_name_arg)
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR strategy build failed: {type(e).__name__}")
            _footer()
            return 1

        # FASE 25 - constroi feed_adapter conforme --feed.
        feed_adapter = None
        if feed_nonlegacy:
            try:
                feed_adapter = _build_feed_adapter(
                    feed_choice, args.symbol
                )
            except Exception as e:  # noqa: BLE001
                # Sanitizado: nao printa stacktrace nem path completo bruto.
                print(
                    f"  ERROR feed build failed ({feed_choice}): "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                _footer()
                return 1
            print(
                f"  Feed source: {feed_adapter.source_description} "
                f"(n_candles={feed_adapter.n_candles})"
            )

        try:
            runner = ChallengeEnduranceRunner(
                profile=profile,
                risk_config=rc,
                readiness_config=readiness_cfg,
                strategy_spec=spec,
                cycle_interval_seconds=0.0,
                virtual_cycle_seconds=float(args.virtual_cycle_seconds),
                feed_adapter=feed_adapter,
                signal_exercise=bool(args.signal_exercise),
            )
            result = runner.run()
        except Exception as e:  # noqa: BLE001
            print(
                f"  ERROR endurance run failed: {type(e).__name__}: "
                f"{str(e)[:200]}"
            )
            _footer()
            return 1

    snap = result.to_ui_snapshot()
    print()
    print("  Endurance UI snapshot:")
    print(f"    mode:                     "
          f"{snap['stage_info']['mode']}")
    print(f"    strategy_name:            "
          f"{snap['stage_info']['strategy_name']}")
    print(f"    feed_type:                "
          f"{snap['stage_info'].get('feed_type', 'mock_random_walk')}")
    print(f"    signal_exercise:          "
          f"{snap['stage_info'].get('signal_exercise', False)}")
    print(f"    stage:                    {snap['stage_info']['stage']}")
    print(f"    duration_planned_minutes: "
          f"{snap['stage_info']['duration_planned_minutes']}")
    print(f"    cycles_completed:         "
          f"{snap['execution']['cycles_completed']}")
    print(f"    trades_opened:            "
          f"{snap['execution']['trades_opened']}")
    print(f"    trades_closed:            "
          f"{snap['execution']['trades_closed']}")
    print(f"    open_positions_end:       "
          f"{snap['execution'].get('open_positions_end', 0)}")
    print(f"    pnl_realized:             "
          f"{snap['execution']['pnl_realized']}")
    print(f"    max_drawdown_observed:    "
          f"{snap['risk_health']['max_drawdown_observed']}")
    print(f"    risk_violations_count:    "
          f"{snap['risk_health']['risk_violations_count']}")
    print(f"    safety_events_count:      "
          f"{snap['safety']['safety_events_count']}")
    print(f"    final_safety_state:       "
          f"{snap['safety']['final_safety_state']}")
    print(f"    verdict:                  {snap['verdict']['verdict']}")
    print(f"    next_recommended_stage:   "
          f"{snap['stage_info']['next_recommended_stage']}")

    # FASE 25 Bloco 9 - mensagens prescritas para front/UX:
    feed_type_now = snap['stage_info'].get('feed_type', 'mock_random_walk')
    signal_exercise_now = snap['stage_info'].get('signal_exercise', False)
    trades_opened_now = snap['execution']['trades_opened']
    if (trades_opened_now == 0
            and feed_type_now == "mock_random_walk"
            and result.mode == "operational_paper_run"):
        print()
        print(
            "  INFO 0 trades with feed=mock_random_walk is normal for "
            "low-volatility random walk."
        )
        print(
            "  To exercise paper entries in a controlled scenario, use "
            "--feed synthetic_trending --signal-exercise."
        )
    if signal_exercise_now:
        print()
        print(
            "  NOTE signal_exercise=True - controlled "
            "synthetic/cached scenario."
        )
        print(
            "       This is NOT performance evidence. Do not interpret "
            "PnL as strategy validation."
        )

    _maybe_write_output(args.output, {
        "readiness": readiness.to_dict(),
        "endurance": result.to_dict(),
        "ui_snapshot": snap,
    })

    _footer()
    # Exit code:
    #   0 = preview limpo OR operational passed
    #   2 = operational failed (blockers acionaveis)
    if result.mode == "preview_no_strategy":
        return 0
    return 0 if result.passed else 2


def _build_feed_adapter(feed_choice: str, symbol: str):
    """FASE 25 - constroi PaperFeedAdapter para CLI.

    SEM rede, SEM download. cache eh leitura LOCAL apenas.
    """
    from crypto_trading_bot.paper_feed import (
        build_cache_feed, build_synthetic_ranging_feed,
        build_synthetic_trend_pullback_feed,
    )
    if feed_choice == "synthetic_trending":
        # Fixture com pullback explicito (cenario para trend_pullback).
        return build_synthetic_trend_pullback_feed(symbol=symbol)
    if feed_choice == "synthetic_ranging":
        return build_synthetic_ranging_feed(symbol=symbol)
    if feed_choice == "cache":
        return build_cache_feed(symbol=symbol, timeframe="15")
    raise ValueError(f"feed_choice inesperado: {feed_choice!r}")


def _maybe_write_output(path: str, payload: dict) -> None:
    if not path:
        return
    out_path = Path(path)
    if any(p == ".." for p in out_path.parts):
        print("  ERROR --output path contains '..' (rejected)")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    # Defesa em profundidade: rejeitar substrings sensiveis na serializacao.
    lower = text.lower()
    for tok in ("api_key", "api_secret", "bearer ", "x-bapi", "sign=",
                "authorization:", "origin_string"):
        if tok in lower:
            print("  ERROR refusing to write output: suspicious token found")
            return
    out_path.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    sys.exit(main())
