"""
TradeCycleContext + TradeCycleContextForAI (FASE 30/32)
========================================================
Contexto que flui por cada ciclo do DemoEnduranceRunner.

⚠️  SEPARACAO OBRIGATORIA (ajuste do operador):
    - TradeCycleContext: INTERNO ao runner. Pode referenciar snapshots
      tecnicos completos.
    - TradeCycleContextForAI: SANITIZADO. A IA NUNCA recebe secrets,
      headers, API key/secret, payloads sensiveis nem objetos mutaveis
      de execucao (client/executor/risk_engine/mode_guard). Derivado
      EXCLUSIVAMENTE via to_ai_context().

Fluxo oficial por ciclo:
    market data -> prediction context (opt) -> features -> strategy ->
    signal -> RiskEngine -> AI support (opt) -> gates -> dry-run gate ->
    would-order -> telemetry -> sleep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional


@dataclass(frozen=True)
class TradeCycleContext:
    """Contexto INTERNO de um ciclo. Imutavel.

    NUNCA serializado diretamente para IA — use to_ai_context().
    """

    cycle_idx: int
    wall_clock: datetime
    symbol: str
    profile_name: str
    signal_snapshot: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    risk_summary: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    prediction_context_dict: Optional[Mapping[str, Any]] = None
    ai_advice_dict: Optional[Mapping[str, Any]] = None
    gate_result: Optional[Mapping[str, Any]] = None
    market_meta: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        for map_field in ("signal_snapshot", "risk_summary", "market_meta"):
            val = getattr(self, map_field)
            if not isinstance(val, MappingProxyType):
                object.__setattr__(
                    self, map_field, MappingProxyType(dict(val)),
                )
        for opt_field in (
            "prediction_context_dict", "ai_advice_dict", "gate_result",
        ):
            val = getattr(self, opt_field)
            if val is not None and not isinstance(val, MappingProxyType):
                object.__setattr__(
                    self, opt_field, MappingProxyType(dict(val)),
                )

    def to_ai_context(self) -> Dict[str, Any]:
        """Deriva TradeCycleContextForAI (payload sanitizado p/ IA).

        Reusa build_ai_context (FASE 32), que aplica denylist de
        tokens sensiveis + truncamento. O contexto de prediction ja
        chega como dict consultivo (adapter FASE 32/34) e eh
        re-sanitizado por defesa em profundidade.
        """
        from crypto_trading_bot.ai_assistant.context_builder import (
            build_ai_context,
        )
        return build_ai_context(
            symbol=self.symbol,
            profile_name=self.profile_name,
            cycle_idx=self.cycle_idx,
            signal_snapshot=dict(self.signal_snapshot),
            risk_summary=dict(self.risk_summary),
            prediction_context=(
                dict(self.prediction_context_dict)
                if self.prediction_context_dict is not None else None
            ),
            market_meta=dict(self.market_meta),
        )


__all__ = ["TradeCycleContext"]
