"""
ChallengeEndurance strategy factory (FASE 24)
==================================================
Helper que mapeia nome de estrategia (CLI/config) para um StrategySpec
existente do projeto. Apenas estrategias JA CRIADAS no projeto sao
expostas — esta fase NUNCA cria estrategia nova nem faz tuning.

⚠️  Provider-agnostic. NAO importa BybitClient, BybitDemoExecutor,
    httpx, requests. Apenas reusa strategies/research existentes.
⚠️  Determinista: factory retorna o StrategySpec ja registrado pelo
    builder oficial da estrategia. Sem hardcode de sizing/risco aqui.
"""

from __future__ import annotations

from typing import Mapping


SUPPORTED_STRATEGIES = (
    "trend_pullback",
    "volatility_breakout",
    "trend_pullback_bidirectional",
)


def build_strategy_spec(name: str):
    """Retorna StrategySpec existente do projeto para o nome dado.

    Apenas nomes em SUPPORTED_STRATEGIES sao aceitos. Lazy imports
    evitam carregar todas as estrategias sempre.

    Args:
        name: "trend_pullback" | "volatility_breakout".

    Returns:
        StrategySpec do projeto, pronto para SessionRunner.

    Raises:
        ValueError: nome desconhecido.
    """
    if not isinstance(name, str):
        raise ValueError("strategy name deve ser string")
    norm = name.lower().strip()
    if norm == "trend_pullback":
        from crypto_trading_bot.strategies.trend_pullback_strategy import (
            build_trend_pullback_spec,
        )
        return build_trend_pullback_spec()
    if norm == "volatility_breakout":
        from crypto_trading_bot.strategies.volatility_breakout_strategy import (
            build_volatility_breakout_spec,
        )
        return build_volatility_breakout_spec()
    if norm == "trend_pullback_bidirectional":
        from crypto_trading_bot.strategies.trend_pullback_bidirectional_strategy import (  # noqa: E501
            build_trend_pullback_bidirectional_spec,
        )
        return build_trend_pullback_bidirectional_spec()
    raise ValueError(
        f"strategy nome desconhecido: {name!r}. "
        f"Aceitas: {list(SUPPORTED_STRATEGIES)}"
    )


def describe_supported_strategies() -> Mapping[str, str]:
    """Mapping nome -> descricao curta para CLI/UI."""
    return {
        "trend_pullback": (
            "Tendencia (EMA fast > EMA slow) + pullback na zona EMA + "
            "RSI nao sobrecomprado. Conservadora; aguarda confirmacao."
        ),
        "volatility_breakout": (
            "Breakout de volatilidade via Bollinger Bands com filtro de "
            "volume. Mais sinais em mercado de range."
        ),
        "trend_pullback_bidirectional": (
            "Tendencia + pullback BIDIRECIONAL (BUY long / SELL short). "
            "Criterios e parametros proprios por lado. SELL real exige "
            "gate proprio (DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED)."
        ),
    }
