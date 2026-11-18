"""
SessionRunnerConfig — configuração imutável do supervisor (FASE 17)
======================================================================
⚠️  Frozen dataclass; clock/sleep injetáveis para testes determinísticos.
⚠️  PROVIDER-AGNOSTIC. Não importa BybitClient/BybitDemoExecutor/httpx.

Campos:
    profile:                OperationalProfile (obrigatório).
    spec:                   StrategySpec (obrigatório) — pipeline interno.
    capital:                capital inicial (USD); deve ser > 0.
    symbol / timeframe:     símbolo e timeframe operacional.
    max_cycles:             cap supervisor (> 0).
    cycle_interval_seconds: sleep entre ciclos (>= 0; 0 = replay rápido).
    dry_run:                quando True, força HOLD em todos os ciclos
                            (mesma semântica do PaperTradingOrchestrator).
    simulated_fee_pct:      fee % aplicada por MockExchange.
    spec_config_override:   override opcional do spec.default_config.
    clock:                  callable retornando datetime UTC; default
                            datetime.now(timezone.utc). Injetável p/ testes.
    sleep:                  callable(seconds: float) → None; default
                            time.sleep. Injetável p/ testes (lambda s: None).
    safety_state_machine:   SafetyStateMachine; default cria interna em NORMAL.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from crypto_trading_bot.operational_profile import OperationalProfile
from crypto_trading_bot.operational_safety import SafetyStateMachine
from crypto_trading_bot.paper_feed import PaperFeedAdapter
from crypto_trading_bot.research.strategy_research import StrategySpec


def _default_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SessionRunnerConfig:
    """
    Configuração imutável do SessionRunner.

    ⚠️  profile, spec, capital, symbol, max_cycles são obrigatórios.
    ⚠️  clock/sleep são injetáveis para testes 100% offline e
        endurance determinística.
    """

    profile: OperationalProfile
    spec: StrategySpec
    capital: float
    symbol: str = "BTCUSDT"
    timeframe: str = "15"
    max_cycles: int = 10
    cycle_interval_seconds: float = 0.0
    dry_run: bool = False
    simulated_fee_pct: float = 0.0006
    spec_config_override: Optional[Mapping[str, Any]] = None

    # Injetáveis (defaults reais; testes substituem)
    clock: Callable[[], datetime] = field(default=_default_clock)
    sleep: Callable[[float], None] = field(default=time.sleep)
    safety_state_machine: Optional[SafetyStateMachine] = None

    # FASE 17 — Quanto o relógio virtual avança por ciclo quando o caller
    # injeta um clock fake (útil para endurance determinística). NÃO afeta
    # clock real (default); apenas testes que substituem `clock` usam.
    # Documentado como "quantos segundos virtuais um ciclo representa".
    virtual_cycle_seconds: float = 60.0

    # FASE 25 — Feed paper opcional. None preserva comportamento legado
    # (MockExchange random walk). Quando fornecido, FeedBackedMockExchange
    # substitui o random walk pelos candles deterministicos do feed.
    feed_adapter: Optional[PaperFeedAdapter] = None

    # FASE 25 — Quando True, instancia PaperExitOrchestrator com ExitPolicy
    # default (SL/TP via candle.high/low) e avalia fechamento por ciclo.
    # Default False preserva comportamento legado. Para signal exercise
    # operacional, este flag deve ser True junto com feed_adapter.
    signal_exercise: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.profile, OperationalProfile):
            raise TypeError(
                "profile deve ser OperationalProfile; "
                f"recebido {type(self.profile).__name__}"
            )
        if not isinstance(self.spec, StrategySpec):
            raise TypeError(
                "spec deve ser StrategySpec; "
                f"recebido {type(self.spec).__name__}"
            )
        if not isinstance(self.capital, (int, float)) or self.capital <= 0:
            raise ValueError(
                f"capital deve ser numérico > 0; recebido {self.capital}"
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError(
                f"symbol deve ser string não-vazia; recebido {self.symbol!r}"
            )
        if not isinstance(self.max_cycles, int) or self.max_cycles <= 0:
            raise ValueError(
                f"max_cycles deve ser int > 0; recebido {self.max_cycles}"
            )
        if not isinstance(self.cycle_interval_seconds, (int, float)) \
                or self.cycle_interval_seconds < 0:
            raise ValueError(
                f"cycle_interval_seconds deve ser >= 0; "
                f"recebido {self.cycle_interval_seconds}"
            )
        if not callable(self.clock):
            raise TypeError("clock deve ser callable() -> datetime")
        if not callable(self.sleep):
            raise TypeError("sleep deve ser callable(seconds) -> None")
        if (self.safety_state_machine is not None
                and not isinstance(self.safety_state_machine,
                                   SafetyStateMachine)):
            raise TypeError(
                "safety_state_machine deve ser SafetyStateMachine ou None"
            )
        if self.virtual_cycle_seconds < 0:
            raise ValueError(
                f"virtual_cycle_seconds deve ser >= 0; "
                f"recebido {self.virtual_cycle_seconds}"
            )
        if (self.feed_adapter is not None
                and not isinstance(self.feed_adapter, PaperFeedAdapter)):
            raise TypeError(
                "feed_adapter deve ser PaperFeedAdapter ou None"
            )
        if self.feed_adapter is not None:
            if self.feed_adapter.symbol != self.symbol:
                raise ValueError(
                    f"feed_adapter.symbol={self.feed_adapter.symbol!r} "
                    f"!= config.symbol={self.symbol!r}"
                )
            if self.feed_adapter.timeframe != self.timeframe:
                raise ValueError(
                    f"feed_adapter.timeframe={self.feed_adapter.timeframe!r} "
                    f"!= config.timeframe={self.timeframe!r}"
                )
        if not isinstance(self.signal_exercise, bool):
            raise TypeError("signal_exercise deve ser bool")
