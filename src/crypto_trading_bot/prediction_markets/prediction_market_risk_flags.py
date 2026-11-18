"""
PredictionMarketRiskFlags (FASE 34)
====================================
Flags de risco derivadas de eventos de prediction market.

⚠️  CONSULTIVO apenas: flags NUNCA alteram TradingSignal, RiskResult,
    perfil ou estrategia. Servem para enriquecer contexto, alimentar
    IA (advisory) e relatorios.
"""

from __future__ import annotations

from typing import List, Optional

from crypto_trading_bot.prediction_markets.market_event_model import (
    MarketEvent,
)


# Flags estaveis (nao renomear; usados em telemetry/report/readiness)
FLAG_MACRO_EVENT_VOLATILITY = "macro_event_volatility"
FLAG_RAPID_PROBABILITY_SHIFT = "rapid_probability_shift"
FLAG_LOW_LIQUIDITY = "low_liquidity_signal"
FLAG_HIGH_BTC_RELEVANCE = "high_btc_relevance"

ALL_RISK_FLAGS = (
    FLAG_MACRO_EVENT_VOLATILITY,
    FLAG_RAPID_PROBABILITY_SHIFT,
    FLAG_LOW_LIQUIDITY,
    FLAG_HIGH_BTC_RELEVANCE,
)

# Thresholds documentados (consultivos; editaveis)
RAPID_SHIFT_24H_THRESHOLD_PP = 5.0    # pontos percentuais em 24h
LOW_LIQUIDITY_THRESHOLD = 10000.0     # USD
HIGH_BTC_RELEVANCE_THRESHOLD = 0.7
MACRO_CATEGORIES = (
    "macro", "rates", "inflation", "fed", "cpi", "payroll",
    "regulation", "geopolitics", "election", "war",
)


def derive_risk_flags(event: MarketEvent) -> List[str]:
    """Deriva flags de risco consultivas de um MarketEvent."""
    flags: List[str] = []
    if event.category in MACRO_CATEGORIES and \
            abs(event.probability_change_24h) >= \
            RAPID_SHIFT_24H_THRESHOLD_PP:
        flags.append(FLAG_MACRO_EVENT_VOLATILITY)
    if abs(event.probability_change_24h) >= \
            RAPID_SHIFT_24H_THRESHOLD_PP or \
            abs(event.probability_change_1h) >= \
            (RAPID_SHIFT_24H_THRESHOLD_PP / 2.0):
        flags.append(FLAG_RAPID_PROBABILITY_SHIFT)
    if 0 < event.liquidity < LOW_LIQUIDITY_THRESHOLD:
        flags.append(FLAG_LOW_LIQUIDITY)
    if event.btc_relevance_score >= HIGH_BTC_RELEVANCE_THRESHOLD:
        flags.append(FLAG_HIGH_BTC_RELEVANCE)
    return flags


def highest_priority_flag(flags: List[str]) -> Optional[str]:
    """Flag de maior prioridade (ordem de ALL_RISK_FLAGS)."""
    for flag in ALL_RISK_FLAGS:
        if flag in flags:
            return flag
    return None


__all__ = [
    "ALL_RISK_FLAGS",
    "FLAG_HIGH_BTC_RELEVANCE",
    "FLAG_LOW_LIQUIDITY",
    "FLAG_MACRO_EVENT_VOLATILITY",
    "FLAG_RAPID_PROBABILITY_SHIFT",
    "HIGH_BTC_RELEVANCE_THRESHOLD",
    "LOW_LIQUIDITY_THRESHOLD",
    "MACRO_CATEGORIES",
    "RAPID_SHIFT_24H_THRESHOLD_PP",
    "derive_risk_flags",
    "highest_priority_flag",
]
