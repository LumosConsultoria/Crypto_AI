"""
PaperFeedType - tipos de feed paper suportados (FASE 25 Bloco 2)
==================================================================
Tipos sao explicitos e auditaveis. Nao ha mapa automatico para rede
ou demo. Todos sao offline.
"""

from __future__ import annotations

from enum import Enum


class PaperFeedType(str, Enum):
    """Tipo de feed que alimenta o SessionRunner paper.

    MOCK_RANDOM_WALK
        Comportamento legado: MockExchange gera candles via random walk
        com volatilidade baixa. Default historico. Compatibilidade total
        com PAPER_30_MIN/60_MIN/1_DAY ja aprovados.

    SYNTHETIC_TRENDING
        Feed sintetico determinISTIco: candles de tendencia controlada
        gerados via generate_trending_candles. Cenario controlado para
        exercitar trend_pullback. Requer signal_exercise=True.

    SYNTHETIC_RANGING
        Feed sintetico determinISTIco: candles oscilando em range fixo
        via generate_ranging_candles. Cenario controlado para
        volatility_breakout. Requer signal_exercise=True.

    CACHE
        Carrega candles do DataCache local (data/historical/{symbol}_
        {timeframe}.csv). NAO baixa. Cache miss falha com erro claro.
        Requer signal_exercise=True.
    """

    MOCK_RANDOM_WALK = "mock_random_walk"
    SYNTHETIC_TRENDING = "synthetic_trending"
    SYNTHETIC_RANGING = "synthetic_ranging"
    CACHE = "cache"


# Tipos que exigem flag signal_exercise=True na CLI.
_SIGNAL_EXERCISE_REQUIRED = frozenset({
    PaperFeedType.SYNTHETIC_TRENDING,
    PaperFeedType.SYNTHETIC_RANGING,
    PaperFeedType.CACHE,
})


def requires_signal_exercise(feed_type: PaperFeedType) -> bool:
    """True se o feed_type exige flag --signal-exercise explicita."""
    return feed_type in _SIGNAL_EXERCISE_REQUIRED


def is_synthetic(feed_type: PaperFeedType) -> bool:
    """True se o feed eh gerado por fixture sintetica determinISTIca."""
    return feed_type in (
        PaperFeedType.SYNTHETIC_TRENDING,
        PaperFeedType.SYNTHETIC_RANGING,
    )
