"""
Backtest Strategy Registry (FASE 37 Parte C)
============================================
Registro instanciavel das estrategias disponiveis ao backtest
operacional, sob nomes canonicos (os mesmos que o operador usa). NADA
hardcoded no runner: a estrategia vem do operador e eh validada contra
este registry E contra o perfil (allowed_strategies).

Erros explicitos:
  * strategy_unknown            -> nome nao registrado.
  * strategy_not_allowed_by_profile -> nome fora do allowed_strategies.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from crypto_trading_bot.research.strategy_research import (
    StrategyRegistry,
    StrategySpec,
)


class StrategySelectionError(Exception):
    """Erro de selecao de estrategia (desconhecida / barrada por perfil)."""


# Nomes canonicos (operador) -> builder de spec.
def _builders():
    from crypto_trading_bot.strategies.trend_pullback_strategy import (
        build_trend_pullback_spec,
    )
    from crypto_trading_bot.strategies.volatility_breakout_strategy import (
        build_volatility_breakout_spec,
    )
    from crypto_trading_bot.strategies\
        .trend_pullback_bidirectional_strategy import (
            build_trend_pullback_bidirectional_spec,
        )
    return {
        "trend_pullback": build_trend_pullback_spec,
        "volatility_breakout": build_volatility_breakout_spec,
        "trend_pullback_bidirectional":
            build_trend_pullback_bidirectional_spec,
    }


CANONICAL_STRATEGY_NAMES: Tuple[str, ...] = (
    "trend_pullback",
    "trend_pullback_bidirectional",
    "volatility_breakout",
)


def default_backtest_registry() -> StrategyRegistry:
    """Registry fresco com as 3 estrategias sob nomes canonicos."""
    reg = StrategyRegistry()
    for canonical, builder in _builders().items():
        base = builder()
        # Re-empacota sob o nome canonico do operador (sem mutar o base).
        reg.register(StrategySpec(
            name=canonical,
            factory=base.factory,
            description=base.description,
            default_config=dict(base.default_config),
            tags=base.tags,
        ))
    return reg


def list_backtest_strategies() -> List[str]:
    return list(CANONICAL_STRATEGY_NAMES)


def resolve_strategy_spec(
    strategy: str,
    *,
    profile_allowed: Optional[Sequence[str]] = None,
    registry: Optional[StrategyRegistry] = None,
) -> StrategySpec:
    """Valida a estrategia contra registry + perfil e retorna a spec.

    profile_allowed: tupla allowed_strategies do perfil (None/vazio =
    sem restricao de perfil). Levanta StrategySelectionError com motivo
    canonico.
    """
    if not strategy or not str(strategy).strip():
        raise StrategySelectionError(
            "strategy obrigatoria (sem default; informe --strategy)"
        )
    name = str(strategy).strip()
    reg = registry or default_backtest_registry()
    if name not in reg:
        raise StrategySelectionError(
            f"strategy_unknown: {name!r}. Disponiveis: "
            f"{reg.list_names()}"
        )
    if profile_allowed:
        allowed = {str(s).strip() for s in profile_allowed}
        if name not in allowed:
            raise StrategySelectionError(
                f"strategy_not_allowed_by_profile: {name!r} nao esta em "
                f"allowed_strategies={sorted(allowed)}"
            )
    return reg.get(name)


__all__ = [
    "CANONICAL_STRATEGY_NAMES",
    "StrategySelectionError",
    "default_backtest_registry",
    "list_backtest_strategies",
    "resolve_strategy_spec",
]
