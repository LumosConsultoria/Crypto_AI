#!/usr/bin/env python
"""
check_demo_session_readiness.py — PREVIEW ONLY / DOES NOT EXECUTE (FASE 19)
============================================================================
⚠️  Script puro de preview de prontidão para futura sessão Bybit Demo gated.
⚠️  DOES NOT EXECUTE. NÃO envia ordem. NÃO chama executor. NÃO chama rede.
⚠️  NÃO chama BybitClient. NÃO chama BybitDemoExecutor. NÃO promove provider.
⚠️  NÃO abre/imprime .env. NÃO imprime api_key/api_secret/Bearer/X-BAPI-SIGN.
⚠️  Readiness=True é APENAS sinal — não autoriza ordem.

Uso:
    python scripts/check_demo_session_readiness.py --profile personal --capital 5000
    python scripts/check_demo_session_readiness.py --profile prop_challenge --capital 10000
    python scripts/check_demo_session_readiness.py --profile hyrotrader_demo_template --capital 5000

Exit:
    0 → is_ready_for_gated_demo=True (todos os gates limpos).
    1 → houve issue 'error' em qualquer gate, OU input inválido.
"""

from __future__ import annotations

import argparse
import sys
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


def _print_banner() -> None:
    print()
    print("=" * 72)
    print("  DEMO SESSION READINESS — PREVIEW ONLY / DOES NOT EXECUTE")
    print("  NO ORDER SENT. NO NETWORK CALL. NO PROVIDER PROMOTION.")
    print("  Readiness=True is a SIGNAL ONLY — does not authorize orders.")
    print("=" * 72)
    print()


def _print_footer() -> None:
    print()
    print("=" * 72)
    print("  DOES NOT EXECUTE / NO ORDER SENT")
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
            name="custom_preview",
            description="Custom profile via check_demo_session_readiness.py",
            account_size_usd=capital,
        )
    raise ValueError(f"profile desconhecido: {name!r}")


def _icon(severity: str) -> str:
    return {"error": "ERROR  ", "warning": "WARNING", "info": "INFO   "}.get(
        severity, "?      "
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview de Demo Session Readiness. NÃO executa. NÃO envia "
            "ordem. NÃO chama rede."
        ),
    )
    parser.add_argument(
        "--profile", choices=_PROFILE_CHOICES, required=True,
        help="Nome do builder de profile a usar.",
    )
    parser.add_argument(
        "--capital", type=float, default=5000.0,
        help="account_size_usd do profile (default: 5000.0).",
    )
    parser.add_argument(
        "--symbol", type=str, default="BTCUSDT",
        help="Símbolo declarado para futura sessão demo (default: BTCUSDT).",
    )
    parser.add_argument(
        "--has-open-position", action="store_true",
        help="Sinaliza que o operador declara posição aberta (bloqueia).",
    )
    parser.add_argument(
        "--has-open-orders", action="store_true",
        help="Sinaliza que o operador declara ordens abertas (bloqueia).",
    )
    args = parser.parse_args(argv)

    _print_banner()

    if args.capital <= 0:
        print(f"  ERROR  --capital deve ser > 0; recebido {args.capital}")
        _print_footer()
        return 1
    if not args.symbol.strip():
        print("  ERROR  --symbol não pode ser vazio")
        _print_footer()
        return 1

    try:
        profile = _build_profile(args.profile, float(args.capital))
    except Exception as e:
        # Mensagem genérica — não vaza payload de exception.
        print(f"  ERROR  Falha ao construir profile: {type(e).__name__}")
        _print_footer()
        return 1

    # Lazy imports — evita inicialização pesada no parse_args.
    from crypto_trading_bot.demo_session_readiness import (
        DemoSessionReadinessCheck,
    )
    from crypto_trading_bot.operational_safety.safety_state_machine import (
        SafetyStateMachine,
    )

    safety = SafetyStateMachine()  # NORMAL por default
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=args.symbol,
        capital=float(args.capital),
        safety_machine=safety,
        risk_snapshot=None,           # CLI não aplica overrides
        last_safety_flags=None,       # CLI não consome flags reais
        has_open_position=bool(args.has_open_position),
        has_open_orders=bool(args.has_open_orders),
    )
    report = check.evaluate()

    # Cabeçalho
    print(f"  Profile name:       {report.profile_name}")
    print(f"  Provider id:        {report.provider_id}")
    print(f"  Symbol:             {report.symbol}")
    print(f"  Capital declarado:  {report.capital}")
    print(f"  Evaluated at:       {report.evaluated_at.isoformat()}")
    print()
    print(f"  GATES EVALUATED: {len(report.gates_evaluated)}")
    for g in report.gates_evaluated:
        print(f"    - {g.value}")
    print()
    print(
        f"  ISSUES: error={report.total_blocks}  "
        f"warning={report.total_warnings}  info={report.total_info}"
    )
    if report.issues:
        for issue in report.issues:
            print(
                f"  {_icon(issue.severity)} [{issue.gate.value}] "
                f"{issue.message}"
            )
            if issue.detail:
                print(f"           detail: {issue.detail}")
    else:
        print("    (sem issues)")
    print()
    print(f"  is_ready_for_gated_demo: {report.is_ready_for_gated_demo}")
    if report.blocking_reasons:
        print(f"  BLOCKING REASONS ({len(report.blocking_reasons)}):")
        for r in report.blocking_reasons:
            print(f"    * {r}")

    _print_footer()
    return 0 if report.is_ready_for_gated_demo else 1


if __name__ == "__main__":
    sys.exit(main())
