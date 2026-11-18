"""
OperationalProfile — Factories (FASE 16)
==========================================
⚠️  Builders puros, sem rede, sem hardcode operacional.
⚠️  HyroTrader é TEMPLATE EDITÁVEL — não representa regras vinculantes.
    Use overrides para qualquer ajuste. Consulte docs/risk_rules.md.
⚠️  Nenhuma factory consulta provider_name == "HyroTrader" como regra
    de comportamento. Diferenciação é via flags estruturados
    (is_prop_firm, is_challenge_account, kill_switch_enabled, etc.).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from crypto_trading_bot.operational_profile.profile import OperationalProfile


def _validate_capital(value: float | None, *, allow_none: bool = False) -> None:
    if value is None:
        if allow_none:
            return
        raise ValueError("account_size_usd deve ser fornecido")
    if not isinstance(value, (int, float)):
        raise TypeError(
            f"account_size_usd deve ser numérico; recebido {type(value).__name__}"
        )
    if value <= 0:
        raise ValueError(
            f"account_size_usd deve ser > 0; recebido {value}"
        )


def _apply_overrides(base: dict, overrides: Mapping[str, Any]) -> dict:
    """Mescla overrides sobre os defaults do builder (sem mutar base)."""
    merged = dict(base)
    for key, val in overrides.items():
        merged[key] = val
    return merged


# ---------------------------------------------------------------------------
# Personal
# ---------------------------------------------------------------------------

def build_personal_profile(
    *,
    account_size_usd: float,
    name: str = "personal_v1",
    description: str = (
        "Conta pessoal/exchange. Configure limites operacionais via "
        "overrides e .env conforme sua preferência."
    ),
    **overrides: Any,
) -> OperationalProfile:
    """
    Perfil pessoal — sem restrições de prop firm.

    Args:
        account_size_usd: capital nominal da conta (USD), > 0.
        name: identificador do profile (opcional).
        description: descrição livre (opcional).
        **overrides: qualquer campo do OperationalProfile pode ser
                     sobrescrito explicitamente.
    """
    _validate_capital(account_size_usd)
    defaults: dict[str, Any] = {
        "name": name,
        "description": description,
        "provider_type": "personal",
        "is_prop_firm": False,
        "is_challenge_account": False,
        "is_funded_account": False,
        "account_size_usd": float(account_size_usd),
        "kill_switch_enabled": False,
        "conservative_mode": False,
    }
    return OperationalProfile(**_apply_overrides(defaults, overrides))


# ---------------------------------------------------------------------------
# Prop challenge (genérico)
# ---------------------------------------------------------------------------

def build_prop_challenge_profile(
    *,
    account_size_usd: float,
    name: str = "prop_challenge_v1",
    description: str = (
        "Perfil genérico de prop firm em fase de challenge. Regras reais "
        "da prop firm devem ser configuradas via overrides e .env."
    ),
    **overrides: Any,
) -> OperationalProfile:
    """
    Template de prop firm challenge. Por default ativa kill_switch e
    conservative_mode — operador pode desligar via overrides.
    """
    _validate_capital(account_size_usd)
    defaults: dict[str, Any] = {
        "name": name,
        "description": description,
        "provider_type": "prop_challenge",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": float(account_size_usd),
        "kill_switch_enabled": True,
        "conservative_mode": True,
    }
    return OperationalProfile(**_apply_overrides(defaults, overrides))


# ---------------------------------------------------------------------------
# HyroTrader — template editável (NÃO regra vinculante)
# ---------------------------------------------------------------------------

def build_hyrotrader_demo_template(
    *,
    account_size_usd: float,
    name: str = "hyrotrader_demo_template_v1",
    **overrides: Any,
) -> OperationalProfile:
    """
    HyroTrader template **EDITÁVEL** — não representa regras vinculantes
    da HyroTrader. Apenas estrutura inicial conservadora; o operador
    deve editar via overrides e validar com regras reais documentadas
    em docs/risk_rules.md (ou equivalente).

    ⚠️  Nenhum módulo de produção deve consultar provider_name ==
        "HyroTrader" para decidir comportamento. Use as flags
        estruturadas (is_prop_firm, is_challenge_account).
    """
    _validate_capital(account_size_usd)
    description = (
        "HyroTrader 5k/10k/25k TEMPLATE EDITÁVEL — não representa regras "
        "vinculantes da HyroTrader. Ajuste via overrides; valide com as "
        "regras reais documentadas antes de usar em sessão real."
    )
    defaults: dict[str, Any] = {
        "name": name,
        "description": description,
        "provider_type": "prop_challenge",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": float(account_size_usd),
        "kill_switch_enabled": True,
        "conservative_mode": True,
        "require_manual_ack_on_triangulation": True,
    }
    return OperationalProfile(**_apply_overrides(defaults, overrides))


# ---------------------------------------------------------------------------
# Custom
# ---------------------------------------------------------------------------

def build_custom_profile(
    *,
    name: str,
    description: str,
    provider_type: str = "custom",
    account_size_usd: Optional[float] = None,
    **overrides: Any,
) -> OperationalProfile:
    """
    Builder totalmente customizável. Todos os campos podem ser
    sobrescritos via kwargs.

    Args:
        name: identificador (obrigatório).
        description: descrição livre (obrigatória).
        provider_type: tipo (default "custom"; validado pelo dataclass).
        account_size_usd: opcional (None → ler de RiskConfig em runtime).
    """
    _validate_capital(account_size_usd, allow_none=True)
    defaults: dict[str, Any] = {
        "name": name,
        "description": description,
        "provider_type": provider_type,
        "is_prop_firm": False,
        "is_challenge_account": False,
        "is_funded_account": False,
        "account_size_usd": (
            float(account_size_usd) if account_size_usd is not None else None
        ),
    }
    return OperationalProfile(**_apply_overrides(defaults, overrides))
