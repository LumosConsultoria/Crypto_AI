"""
ProfileRegistry - perfis operacionais nomeados (FASE 31)
=========================================================
Registry deterministico de perfis. Reusa as factories FASE 16
(build_personal_profile, build_prop_challenge_profile, build_custom_profile)
e adiciona os perfis do ecossistema FASE 30-35.

⚠️  REGRAS:
    - NENHUM perfil permite live/mainnet (validado no dataclass).
    - NENHUM perfil habilita ordem real sozinho: gates ENV proprios
      continuam obrigatorios (demo real, short, multi-order, AI manual
      review, prediction context). Nenhum gate implica outro.
    - prediction_market_execution_allowed=False SEMPRE.
    - Perfis sao TEMPLATES editaveis via overrides; nada hardcoded
      ignorando o perfil no runner/CLI.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Tuple

from crypto_trading_bot.operational_profile.factories import (
    build_custom_profile,
    build_personal_profile,
    build_prop_challenge_profile,
)
from crypto_trading_bot.operational_profile.profile import OperationalProfile


# Presets de duracao referenciados por perfis (FASE 30).
SHORT_DURATION_PRESETS: Tuple[str, ...] = ("30m", "1h", "2h")
LONG_DURATION_PRESETS: Tuple[str, ...] = ("24h", "3d", "7d")
ALL_DURATION_PRESETS: Tuple[str, ...] = (
    SHORT_DURATION_PRESETS + LONG_DURATION_PRESETS
)

_DEMO_PROVIDERS: Tuple[str, ...] = ("paper", "bybit_demo_linear")


def _personal(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="personal",
        allowed_symbols=("BTCUSDT",),
        allowed_sides="both",
        allowed_strategies=(
            "trend_pullback", "trend_pullback_bidirectional",
            "volatility_breakout",
        ),
        max_open_positions=1,
        max_orders_per_session=1,
        max_orders_per_day=3,
        require_sl_tp=True,
        allow_demo_real=True,
        allow_short_demo=False,          # ate gate explicito
        allow_multi_order_demo=False,    # ate gate explicito
        allow_ai_assistance=True,
        allow_ai_veto=True,
        allow_prediction_market_context=True,
        prediction_context_mode="advisory",
        allowed_prediction_providers=("polymarket_readonly",),
        allowed_duration_presets=ALL_DURATION_PRESETS,
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_environments=("paper", "demo"),
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _demo_validation(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="demo_validation",
        description=(
            "Validacao de demo real-time. Conservador; AI/prediction "
            "desligados para isolar o pipeline base."
        ),
        allowed_symbols=("BTCUSDT",),
        allowed_sides="long",
        allowed_strategies=("trend_pullback",
                            "trend_pullback_bidirectional"),
        allow_demo_real=True,
        allow_ai_assistance=False,
        allow_prediction_market_context=False,
        prediction_context_mode="disabled",
        allowed_duration_presets=SHORT_DURATION_PRESETS,
        allowed_provider_ids=_DEMO_PROVIDERS,
        conservative_mode=True,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _conservative(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="conservative",
        description="Risco reduzido; long-only; limites apertados.",
        allowed_sides="long",
        max_orders_per_day=2,
        max_consecutive_losses=1,
        conservative_mode=True,
        allowed_duration_presets=ALL_DURATION_PRESETS,
        allowed_provider_ids=_DEMO_PROVIDERS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _balanced(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="balanced",
        description="Equilibrio risco/atividade; ambos os lados em research.",
        allowed_sides="both",
        max_orders_per_day=3,
        allowed_duration_presets=ALL_DURATION_PRESETS,
        allowed_provider_ids=_DEMO_PROVIDERS,
        allow_ai_assistance=True,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _aggressive_simulation(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="aggressive_simulation",
        description=(
            "Simulacao agressiva APENAS paper/research. allow_demo_real "
            "False: nunca toca demo real."
        ),
        allowed_sides="both",
        max_orders_per_day=10,
        max_orders_per_session=5,
        max_consecutive_losses=5,
        allow_demo_real=False,
        allowed_environments=("paper",),
        allowed_provider_ids=("paper",),
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _prop_challenge(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="prop_challenge",
        allowed_sides="long",
        max_orders_per_day=2,
        max_orders_per_session=1,
        max_consecutive_losses=1,
        allow_demo_real=True,
        allow_short_demo=False,
        allow_multi_order_demo=False,
        allow_ai_assistance=True,
        allow_ai_veto=True,
        allow_prediction_market_context=False,
        prediction_context_mode="disabled",
        allowed_duration_presets=ALL_DURATION_PRESETS,
        allowed_provider_ids=_DEMO_PROVIDERS,
        risk_config_overrides={
            "max_daily_loss_pct": 0.02,
            "max_total_loss_pct": 0.05,
        },
    )
    defaults.update(ov)
    return build_prop_challenge_profile(account_size_usd=capital, **defaults)


def _long_only(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="long_only",
        description="Somente BUY/long em qualquer modo.",
        allowed_sides="long",
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _short_only(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="short_only",
        description=(
            "Somente SELL/short em research/paper. Demo real de short "
            "permanece atras de gate proprio."
        ),
        allowed_sides="short",
        allow_demo_real=False,   # short real demo exige gate + validacao
        allowed_environments=("paper", "demo"),
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _long_short(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="long_short",
        description=(
            "Ambos os lados em research/paper; short real continua gated."
        ),
        allowed_sides="both",
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _research_only(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="research_only",
        description=(
            "Pesquisa offline/backtest. NUNCA demo real. Prediction "
            "context read_only."
        ),
        provider_type="custom",
        allowed_sides="both",
        allow_demo_real=False,
        allow_ai_assistance=True,
        allow_prediction_market_context=True,
        prediction_context_mode="read_only",
        allowed_prediction_providers=("polymarket_readonly",),
        allowed_environments=("paper",),
        allowed_provider_ids=("paper",),
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_custom_profile(
        name=str(defaults.pop("name")),
        description=str(defaults.pop("description")),
        account_size_usd=capital,
        **defaults,
    )


def _ai_assisted_demo(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="ai_assisted_demo",
        description=(
            "Demo com IA consultiva + prediction advisory. IA nunca "
            "executa; gates continuam soberanos."
        ),
        allowed_sides="both",
        allow_demo_real=True,
        allow_ai_assistance=True,
        allow_ai_veto=True,
        allow_prediction_market_context=True,
        prediction_context_mode="advisory",
        allowed_prediction_providers=("polymarket_readonly",),
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _demo_multi_order_validation(
    capital: float, **ov: Any,
) -> OperationalProfile:
    """FASE 30.2 - validacao de multi-ordem real demo SEQUENCIAL.

    Perfil DEDICADO: o personal permanece com
    allow_multi_order_demo=False. Mesmo aqui, a execucao real exige
    TODOS os gates ENV (incl. DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED)
    + flags + frase + Y. Short real segue atras do gate short.
    """
    defaults: Dict[str, Any] = dict(
        name="demo_multi_order_validation",
        description=(
            "Validacao FASE 30.2: multi-ordem real demo sequencial "
            "(1 posicao por vez; sem scale-in; sem reversao). "
            "Gates ENV + frase + Y continuam obrigatorios."
        ),
        allowed_symbols=("BTCUSDT",),
        allowed_strategies=(
            "trend_pullback_bidirectional", "trend_pullback",
            "volatility_breakout",
        ),
        allowed_sides="both",      # short REAL segue gate proprio
        allow_demo_real=True,
        allow_multi_order_demo=True,
        allow_short_demo=False,
        max_open_positions=1,
        max_orders_per_session=2,
        max_orders_per_day=3,
        max_consecutive_losses=2,
        max_api_failures=3,
        require_sl_tp=True,
        max_leverage=1.0,
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_environments=("paper", "demo"),
        allowed_duration_presets=ALL_DURATION_PRESETS,
        risk_config_overrides={
            "max_daily_loss_pct": 0.01,
            "max_total_loss_pct": 0.02,
        },
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


def _live_readiness_shadow(capital: float, **ov: Any) -> OperationalProfile:
    defaults: Dict[str, Any] = dict(
        name="live_readiness_shadow",
        description=(
            "Shadow de readiness: espelha limites estilo live em demo. "
            "NUNCA live/mainnet; apenas evidencia para FASE 35."
        ),
        allowed_sides="long",
        max_orders_per_day=1,
        max_consecutive_losses=1,
        allow_demo_real=True,
        allow_ai_assistance=True,
        allow_ai_veto=True,
        allow_prediction_market_context=True,
        prediction_context_mode="read_only",
        allowed_prediction_providers=("polymarket_readonly",),
        conservative_mode=True,
        kill_switch_enabled=True,
        allowed_provider_ids=_DEMO_PROVIDERS,
        allowed_duration_presets=ALL_DURATION_PRESETS,
    )
    defaults.update(ov)
    return build_personal_profile(account_size_usd=capital, **defaults)


# Registry publico nome -> builder(capital, **overrides)
PROFILE_BUILDERS: Mapping[
    str, Callable[..., OperationalProfile]
] = {
    "personal": _personal,
    "demo_validation": _demo_validation,
    "conservative": _conservative,
    "balanced": _balanced,
    "aggressive_simulation": _aggressive_simulation,
    "prop_challenge": _prop_challenge,
    "long_only": _long_only,
    "short_only": _short_only,
    "long_short": _long_short,
    "research_only": _research_only,
    "ai_assisted_demo": _ai_assisted_demo,
    "live_readiness_shadow": _live_readiness_shadow,
    "demo_multi_order_validation": _demo_multi_order_validation,
}

SUPPORTED_PROFILE_NAMES: Tuple[str, ...] = tuple(PROFILE_BUILDERS.keys())


__all__ = [
    "ALL_DURATION_PRESETS",
    "LONG_DURATION_PRESETS",
    "PROFILE_BUILDERS",
    "SHORT_DURATION_PRESETS",
    "SUPPORTED_PROFILE_NAMES",
]
