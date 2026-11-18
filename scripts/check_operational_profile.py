#!/usr/bin/env python
"""
check_operational_profile.py — PREVIEW ONLY / DOES NOT APPLY (FASE 18)
========================================================================
⚠️  Script PURO de preview/validação.
⚠️  NÃO aplica overrides. NÃO chama rede. NÃO chama BybitClient.
⚠️  NÃO chama executores. NÃO envia ordem. NÃO imprime secrets.
⚠️  NÃO abre/imprime `.env`.

Uso:
    python scripts/check_operational_profile.py --profile personal --capital 5000
    python scripts/check_operational_profile.py --profile hyrotrader_demo_template --capital 5000
    python scripts/check_operational_profile.py --profile prop_challenge --capital 10000

Exit:
    0 → profile válido / sem issues 'error'.
    1 → profile inválido / pelo menos 1 issue 'error'.
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
    print("=" * 70)
    print("  🔎 OPERATIONAL PROFILE — PREVIEW ONLY / DOES NOT APPLY")
    print("  ⚠️  Sem rede. Sem ordem. Sem secrets. Sem alteração de runtime.")
    print("=" * 70)
    print()


def _format_diff_line(field: str, base, proposed, changed: bool) -> str:
    arrow = "→" if changed else " "
    mark = "*" if changed else " "
    return f"  {mark} {field:<32} {str(base):>14}  {arrow}  {str(proposed):<14}"


def _build_profile(name: str, capital: float):
    """Constrói profile pelo nome do builder. Sem hardcode operacional."""
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
            description="Custom profile via check_operational_profile.py",
            account_size_usd=capital,
        )
    # Não esperado por causa do choices, mas defensivo:
    raise ValueError(f"profile desconhecido: {name!r}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Preview do plano de override de RiskConfig a partir de "
            "OperationalProfile. NÃO aplica nada. NÃO chama rede."
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
    args = parser.parse_args(argv)

    _print_banner()

    if args.capital <= 0:
        print(f"  ❌ --capital deve ser > 0; recebido {args.capital}")
        return 1

    try:
        profile = _build_profile(args.profile, float(args.capital))
    except Exception as e:
        # NÃO inclui str(e) com payload — apenas type name é seguro.
        # Mas neste script o erro vem de input validation; mensagem genérica.
        print(f"  ❌ Falha ao construir profile: {type(e).__name__}")
        return 1

    # Carrega RiskConfig de .env (pydantic-settings). NÃO imprimimos
    # o conteúdo do .env, apenas valores resolvidos do RiskConfig.
    from crypto_trading_bot.config.risk_config import RiskConfig
    from crypto_trading_bot.operational_profile import (
        build_risk_override_plan,
    )

    base_rc = RiskConfig()
    plan = build_risk_override_plan(profile, base_rc)

    # --- Cabeçalho ---
    print(f"  Profile name:       {plan.profile_name}")
    print(f"  Provider type:      {profile.provider_type}")
    print(f"  is_prop_firm:       {profile.is_prop_firm}")
    print(f"  is_challenge:       {profile.is_challenge_account}")
    print(f"  is_funded:          {profile.is_funded_account}")
    print(f"  account_size_usd:   {profile.account_size_usd}")
    print()

    # --- Diff ---
    real_diffs = [d for d in plan.diffs if d.changed]
    print(f"  📊 DIFF (base RiskConfig vs proposed):  {len(real_diffs)} change(s)")
    print()
    print(f"  {'  field':<34} {'base':>14}      {'proposed':<14}")
    print(f"  {'-' * 32}   {'-' * 14}  ---  {'-' * 14}")
    if real_diffs:
        for d in real_diffs:
            print(_format_diff_line(d.field, d.base_value, d.proposed_value, True))
    else:
        print("    (nenhuma alteração proposta)")
    print()

    # --- Issues ---
    n_error = sum(1 for i in plan.issues if i.severity == "error")
    n_warning = sum(1 for i in plan.issues if i.severity == "warning")
    n_info = sum(1 for i in plan.issues if i.severity == "info")
    print(
        f"  ⚠️  ISSUES: error={n_error}  warning={n_warning}  info={n_info}"
    )
    if plan.issues:
        for issue in plan.issues:
            icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}[issue.severity]
            key_part = f"[{issue.key}] " if issue.key else ""
            print(f"  {icon} {issue.severity:<7} {key_part}{issue.message}")
    else:
        print("    (sem issues)")
    print()

    # --- Status ---
    print(f"  is_apply_safe:           {plan.is_apply_safe}")
    print(f"  requires_confirmation:   {plan.requires_confirmation}")
    print()
    print("=" * 70)
    print("  ✅ PREVIEW ONLY — nenhum override foi aplicado.")
    print("  ⚠️  Para aplicar futuramente, use apply_profile_overrides_with_gate")
    print("     com confirm=True + operator_token não-vazio.")
    print("=" * 70)

    return 0 if plan.is_apply_safe else 1


if __name__ == "__main__":
    sys.exit(main())
