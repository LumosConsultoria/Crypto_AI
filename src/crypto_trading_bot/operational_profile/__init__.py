"""
Módulo operational_profile — Perfis operacionais provider-agnostic (FASE 16)
==============================================================================
⚠️  NÃO substitui RiskConfig/RiskEngine. risk_config_overrides é apenas
    configuração explícita/validável; não é aplicada automaticamente.
⚠️  HyroTrader é TEMPLATE EDITÁVEL — não regra vinculante.
⚠️  Nenhum módulo de produção consulta provider_name == "HyroTrader".
    Diferenciação via flags estruturados (is_prop_firm,
    is_challenge_account, kill_switch_enabled, conservative_mode, etc.).

Exports:
    OperationalProfile,
    build_personal_profile, build_prop_challenge_profile,
    build_hyrotrader_demo_template, build_custom_profile,
    validate_profile_self, validate_profile_against_risk_config.
"""

from crypto_trading_bot.operational_profile.factories import (
    build_custom_profile,
    build_hyrotrader_demo_template,
    build_personal_profile,
    build_prop_challenge_profile,
)
from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.operational_profile.risk_adapter import (
    AppliedRiskConfigSnapshot,
    FieldDiff,
    ProfileOverrideRejected,
    ProfileRiskOverrideIssue,
    ProfileRiskOverridePlan,
    apply_profile_overrides_with_gate,
    build_risk_override_plan,
    preview_profile_risk_config,
)
from crypto_trading_bot.operational_profile.profile_registry import (
    ALL_DURATION_PRESETS,
    LONG_DURATION_PRESETS,
    PROFILE_BUILDERS,
    SHORT_DURATION_PRESETS,
    SUPPORTED_PROFILE_NAMES,
)
from crypto_trading_bot.operational_profile.profile_resolver import (
    derive_endurance_limits,
    is_side_allowed,
    is_strategy_allowed,
    is_symbol_allowed,
    resolve_profile,
)
from crypto_trading_bot.operational_profile.validation import (
    validate_profile_against_risk_config,
    validate_profile_self,
)

__all__ = [
    # FASE 31 — registry + resolver
    "ALL_DURATION_PRESETS",
    "LONG_DURATION_PRESETS",
    "PROFILE_BUILDERS",
    "SHORT_DURATION_PRESETS",
    "SUPPORTED_PROFILE_NAMES",
    "derive_endurance_limits",
    "is_side_allowed",
    "is_strategy_allowed",
    "is_symbol_allowed",
    "resolve_profile",
    "OperationalProfile",
    "build_personal_profile",
    "build_prop_challenge_profile",
    "build_hyrotrader_demo_template",
    "build_custom_profile",
    "validate_profile_self",
    "validate_profile_against_risk_config",
    # FASE 18 — Profile-to-RiskConfig gate
    "ProfileRiskOverrideIssue",
    "FieldDiff",
    "ProfileRiskOverridePlan",
    "AppliedRiskConfigSnapshot",
    "ProfileOverrideRejected",
    "build_risk_override_plan",
    "preview_profile_risk_config",
    "apply_profile_overrides_with_gate",
]
