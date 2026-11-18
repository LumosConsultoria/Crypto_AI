"""
OperationalProfile — Validações puras offline (FASE 16)
=========================================================
⚠️  Funções PURAS: sem I/O, sem rede, sem importar BybitClient/executors/
    RiskEngine. Apenas inspecionam dataclasses.
⚠️  NÃO levantam — retornam lista de problemas/avisos (vazia se OK).
    Caller decide se aborta operação.
"""

from __future__ import annotations

from typing import Any, List

from crypto_trading_bot.operational_profile.profile import OperationalProfile

# Não importamos RiskConfig em load time para evitar acoplamento de
# inicialização. A validation cross-config aceita qualquer objeto duck-typed
# com os campos relevantes (max_daily_loss_pct, max_total_loss_pct,
# account_size_usd, default_symbol).


def validate_profile_self(profile: OperationalProfile) -> List[str]:
    """
    Valida o profile isoladamente (sem cross-config).

    Returns:
        Lista de problemas encontrados. Vazia se OK.
    """
    if not isinstance(profile, OperationalProfile):
        return [
            f"validate_profile_self: argumento deve ser OperationalProfile; "
            f"recebido {type(profile).__name__}"
        ]

    issues: List[str] = []

    # account_size_usd
    if profile.account_size_usd is not None:
        if not isinstance(profile.account_size_usd, (int, float)):
            issues.append(
                f"account_size_usd deve ser numérico ou None; "
                f"recebido {type(profile.account_size_usd).__name__}"
            )
        elif profile.account_size_usd <= 0:
            issues.append(
                f"account_size_usd deve ser > 0; "
                f"recebido {profile.account_size_usd}"
            )

    # max_concurrent_positions
    if not isinstance(profile.max_concurrent_positions, int):
        issues.append("max_concurrent_positions deve ser int")
    elif profile.max_concurrent_positions <= 0:
        issues.append(
            f"max_concurrent_positions deve ser > 0; "
            f"recebido {profile.max_concurrent_positions}"
        )

    # max_session_minutes
    if profile.max_session_minutes is not None:
        if not isinstance(profile.max_session_minutes, int):
            issues.append("max_session_minutes deve ser int ou None")
        elif profile.max_session_minutes <= 0:
            issues.append(
                f"max_session_minutes deve ser > 0; "
                f"recebido {profile.max_session_minutes}"
            )

    # pause_after_consecutive_losses
    if profile.pause_after_consecutive_losses is not None:
        if not isinstance(profile.pause_after_consecutive_losses, int):
            issues.append("pause_after_consecutive_losses deve ser int ou None")
        elif profile.pause_after_consecutive_losses <= 0:
            issues.append(
                f"pause_after_consecutive_losses deve ser > 0; "
                f"recebido {profile.pause_after_consecutive_losses}"
            )

    # max_trades_per_session
    if profile.max_trades_per_session is not None:
        if not isinstance(profile.max_trades_per_session, int):
            issues.append("max_trades_per_session deve ser int ou None")
        elif profile.max_trades_per_session <= 0:
            issues.append(
                f"max_trades_per_session deve ser > 0; "
                f"recebido {profile.max_trades_per_session}"
            )

    # allowed_symbols — devem ser strings não-vazias
    for sym in profile.allowed_symbols:
        if not isinstance(sym, str) or not sym.strip():
            issues.append(
                f"allowed_symbols contém entrada inválida: {sym!r}"
            )

    # allowed_hours_utc — pares (start, end) em [0, 24); start < end
    for entry in profile.allowed_hours_utc:
        if (not isinstance(entry, tuple) or len(entry) != 2
                or not all(isinstance(x, int) for x in entry)):
            issues.append(
                f"allowed_hours_utc entrada inválida (esperado par de ints): {entry!r}"
            )
            continue
        start, end = entry
        if not (0 <= start < 24) or not (0 <= end <= 24):
            issues.append(
                f"allowed_hours_utc fora de [0, 24): {entry!r}"
            )
            continue
        if start >= end:
            issues.append(
                f"allowed_hours_utc inválido (start >= end): {entry!r}"
            )

    # Coerência de flags: funded e challenge mutuamente exclusivos
    if profile.is_funded_account and profile.is_challenge_account:
        issues.append(
            "is_funded_account e is_challenge_account são mutuamente "
            "exclusivos"
        )

    # Coerência: prop_funded exige is_funded_account
    if profile.provider_type == "prop_funded" and not profile.is_funded_account:
        issues.append(
            "provider_type='prop_funded' exige is_funded_account=True"
        )
    if profile.provider_type == "prop_challenge" and not (
        profile.is_prop_firm or profile.is_challenge_account
    ):
        issues.append(
            "provider_type='prop_challenge' exige is_prop_firm=True "
            "ou is_challenge_account=True"
        )

    return issues


def validate_profile_against_risk_config(
    profile: OperationalProfile,
    risk_config: Any,
) -> List[str]:
    """
    Validação cruzada profile × RiskConfig (ou qualquer objeto duck-typed
    com os campos relevantes).

    NÃO importa RiskConfig em load time — aceita qualquer objeto.

    Returns:
        Lista de problemas/avisos. Vazia se OK.
    """
    if not isinstance(profile, OperationalProfile):
        return [
            f"validate_profile_against_risk_config: profile deve ser "
            f"OperationalProfile; recebido {type(profile).__name__}"
        ]
    if risk_config is None:
        return [
            "validate_profile_against_risk_config: risk_config não pode ser None"
        ]

    issues: List[str] = []

    # account_size_usd cross-check
    rc_capital = getattr(risk_config, "account_size_usd", None)
    if (profile.account_size_usd is not None and rc_capital is not None
            and isinstance(rc_capital, (int, float)) and rc_capital > 0):
        # Tolerância de 0.5% para arredondamentos
        tol = max(abs(profile.account_size_usd) * 0.005, 1.0)
        if abs(profile.account_size_usd - rc_capital) > tol:
            issues.append(
                f"account_size_usd diverge: profile={profile.account_size_usd} "
                f"vs risk_config={rc_capital}"
            )

    # Prop challenge tipicamente exige max_daily_loss_pct conservador (<= 5%)
    if profile.is_challenge_account:
        rc_max_daily = getattr(risk_config, "max_daily_loss_pct", None)
        if (isinstance(rc_max_daily, (int, float))
                and rc_max_daily > 0.05):
            issues.append(
                f"is_challenge_account=True mas max_daily_loss_pct="
                f"{rc_max_daily} > 0.05 (5%). Prop firms geralmente exigem "
                f"limite estrito; valide regras reais antes."
            )

    # Símbolos permitidos vs default_symbol do RiskConfig
    rc_default_symbol = getattr(risk_config, "default_symbol", None)
    if (profile.allowed_symbols and isinstance(rc_default_symbol, str)
            and rc_default_symbol and rc_default_symbol not in profile.allowed_symbols):
        issues.append(
            f"risk_config.default_symbol={rc_default_symbol!r} não está em "
            f"profile.allowed_symbols={list(profile.allowed_symbols)}"
        )

    # risk_config_overrides sugere chave inexistente em RiskConfig
    if profile.risk_config_overrides:
        for key in profile.risk_config_overrides.keys():
            if not hasattr(risk_config, key):
                issues.append(
                    f"profile.risk_config_overrides contém chave "
                    f"{key!r} que não existe em RiskConfig"
                )

    return issues
