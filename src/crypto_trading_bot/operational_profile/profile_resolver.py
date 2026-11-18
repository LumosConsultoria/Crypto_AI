"""
ProfileResolver (FASE 31)
==========================
Resolve nome de perfil -> OperationalProfile completo e deriva os
tetos operacionais (EnduranceLimits) usados pelo DemoEnduranceRunner.

⚠️  O runner e a CLI usam ESTE resolver. Nada de capital, risco,
    max orders, lado permitido, provider ou estrategia hardcoded
    ignorando o perfil.
⚠️  Funcoes puras: sem rede, sem .env, sem secrets.
"""

from __future__ import annotations

from typing import Any

from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.operational_profile.profile_registry import (
    PROFILE_BUILDERS,
    SUPPORTED_PROFILE_NAMES,
)


def resolve_profile(
    name: str, *, capital: float, **overrides: Any,
) -> OperationalProfile:
    """Resolve um perfil nomeado do registry.

    Args:
        name: um de SUPPORTED_PROFILE_NAMES.
        capital: account_size_usd (> 0), explicitamente informado.
        **overrides: ajustes explicitos do operador sobre o template.

    Returns:
        OperationalProfile completo (frozen).

    Raises:
        ValueError: nome desconhecido ou capital invalido.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("profile name deve ser string nao-vazia")
    norm = name.strip().lower()
    builder = PROFILE_BUILDERS.get(norm)
    if builder is None:
        raise ValueError(
            f"profile desconhecido: {name!r}. "
            f"Aceitos: {list(SUPPORTED_PROFILE_NAMES)}"
        )
    if not isinstance(capital, (int, float)) or capital <= 0:
        raise ValueError(f"capital deve ser > 0: {capital!r}")
    return builder(float(capital), **overrides)


def derive_endurance_limits(profile: OperationalProfile):
    """Deriva EnduranceLimits dos tetos do perfil.

    Os limites do runner SEMPRE vem do perfil (nada hardcoded).
    Percentuais de perda usam risk_config_overrides quando presentes
    (em fracao 0-1 no RiskConfig; EnduranceLimits usa percentual 0-100).
    """
    from crypto_trading_bot.demo_endurance.endurance_limits import (
        EnduranceLimits,
    )

    overrides = dict(profile.risk_config_overrides)
    daily_frac = float(overrides.get("max_daily_loss_pct", 0.01))
    total_frac = float(overrides.get("max_total_loss_pct", 0.02))

    return EnduranceLimits(
        max_orders_per_day=int(profile.max_orders_per_day),
        max_orders_per_session=int(profile.max_orders_per_session),
        max_open_positions=int(profile.max_open_positions),
        max_daily_loss_pct=max(0.0001, daily_frac) * 100.0,
        max_total_loss_pct=max(0.0001, total_frac) * 100.0,
        max_consecutive_losses=int(profile.max_consecutive_losses),
        max_api_failures=int(profile.max_api_failures),
        max_stale_data_seconds=float(profile.max_stale_data_seconds),
        require_sl_tp=bool(profile.require_sl_tp),
        flat_check_interval_minutes=int(
            profile.flat_check_interval_minutes
        ),
    )


def is_strategy_allowed(
    profile: OperationalProfile, strategy_name: str,
) -> bool:
    """True se a estrategia eh permitida pelo perfil (vazio = todas)."""
    if not profile.allowed_strategies:
        return True
    return strategy_name in profile.allowed_strategies


def is_side_allowed(profile: OperationalProfile, side: str) -> bool:
    """True se o lado (buy/sell ~ long/short) eh permitido pelo perfil."""
    s = str(side).strip().lower()
    if s in ("buy", "long"):
        return profile.allowed_sides in ("long", "both")
    if s in ("sell", "short"):
        return profile.allowed_sides in ("short", "both")
    return False


def is_symbol_allowed(profile: OperationalProfile, symbol: str) -> bool:
    """True se o simbolo eh permitido pelo perfil (vazio = todos)."""
    if not profile.allowed_symbols:
        return True
    return symbol in profile.allowed_symbols


__all__ = [
    "derive_endurance_limits",
    "is_side_allowed",
    "is_strategy_allowed",
    "is_symbol_allowed",
    "resolve_profile",
]
