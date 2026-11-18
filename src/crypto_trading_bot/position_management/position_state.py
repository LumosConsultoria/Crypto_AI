"""
PositionState / ExposureState / AggregatedRiskSnapshot (Bloco E2)
==================================================================
Modelos puros de estado de posicao e risco agregado.

⚠️  NAO substituem o RiskEngine (soberano): o risco agregado e
    COMPUTADO aqui e SEMPRE revalidado via RiskEngine.validate_signal
    antes de qualquer aprovacao (adapter em policies.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Optional, Tuple


@dataclass(frozen=True)
class PositionEntry:
    """Uma entrada (fill) que compoe a posicao."""
    price: float
    qty: float
    entered_at: datetime

    def __post_init__(self) -> None:
        if self.price <= 0 or self.qty <= 0:
            raise ValueError("price/qty devem ser > 0")
        if self.entered_at.tzinfo is None:
            object.__setattr__(
                self, "entered_at",
                self.entered_at.replace(tzinfo=timezone.utc),
            )

    def to_dict(self) -> dict:
        return {
            "price": float(self.price),
            "qty": float(self.qty),
            "entered_at": self.entered_at.isoformat(),
        }


@dataclass(frozen=True)
class PositionState:
    """Posicao aberta (possivelmente com multiplas entradas)."""

    symbol: str
    side: str                       # buy | sell
    entries: Tuple[PositionEntry, ...]
    stop_loss: float
    take_profit: Optional[float] = None

    def __post_init__(self) -> None:
        side = str(self.side).strip().lower()
        if side not in ("buy", "sell"):
            raise ValueError(f"side invalido: {self.side!r}")
        object.__setattr__(self, "side", side)
        if not self.entries:
            raise ValueError("posicao exige >= 1 entrada")
        if not isinstance(self.entries, tuple):
            object.__setattr__(self, "entries", tuple(self.entries))
        if self.stop_loss <= 0:
            raise ValueError("stop_loss obrigatorio (> 0)")

    @property
    def qty(self) -> float:
        return sum(e.qty for e in self.entries)

    @property
    def avg_entry_price(self) -> float:
        total_qty = self.qty
        return sum(e.price * e.qty for e in self.entries) / total_qty

    @property
    def notional_usd(self) -> float:
        return self.avg_entry_price * self.qty

    @property
    def scale_in_count(self) -> int:
        """Entradas ALEM da inicial."""
        return len(self.entries) - 1

    @property
    def last_entry(self) -> PositionEntry:
        return self.entries[-1]

    def risk_to_stop_usd(self) -> float:
        """Risco total ate o SL atual (sempre >= 0)."""
        return abs(self.avg_entry_price - self.stop_loss) * self.qty

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": float(self.qty),
            "avg_entry_price": round(float(self.avg_entry_price), 8),
            "notional_usd": round(float(self.notional_usd), 6),
            "stop_loss": float(self.stop_loss),
            "take_profit": self.take_profit,
            "scale_in_count": int(self.scale_in_count),
            "entries": [e.to_dict() for e in self.entries],
            "risk_to_stop_usd": round(
                float(self.risk_to_stop_usd()), 6,
            ),
        }


@dataclass(frozen=True)
class ExposureState:
    """Exposicao agregada da conta."""

    per_symbol_notional: Mapping[str, float] = field(
        default_factory=lambda: MappingProxyType({})
    )
    open_positions_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.per_symbol_notional, MappingProxyType):
            object.__setattr__(
                self, "per_symbol_notional",
                MappingProxyType(dict(self.per_symbol_notional)),
            )

    @property
    def total_notional(self) -> float:
        return sum(self.per_symbol_notional.values())

    def to_dict(self) -> dict:
        return {
            "per_symbol_notional": dict(self.per_symbol_notional),
            "open_positions_count": int(self.open_positions_count),
            "total_notional": round(float(self.total_notional), 6),
        }


@dataclass(frozen=True)
class AggregatedRiskSnapshot:
    """Risco da posicao ANTES e DEPOIS de uma proposta.

    Percentuais relativos ao capital da SESSAO (operator input).
    """

    capital_usd: float
    current_risk_usd: float
    added_risk_usd: float
    sl_used_for_calc: float

    def __post_init__(self) -> None:
        if self.capital_usd <= 0:
            raise ValueError("capital_usd deve ser > 0")

    @property
    def total_risk_usd(self) -> float:
        return self.current_risk_usd + self.added_risk_usd

    @property
    def current_risk_pct(self) -> float:
        return (self.current_risk_usd / self.capital_usd) * 100.0

    @property
    def added_risk_pct(self) -> float:
        return (self.added_risk_usd / self.capital_usd) * 100.0

    @property
    def total_risk_pct(self) -> float:
        return (self.total_risk_usd / self.capital_usd) * 100.0

    def to_dict(self) -> dict:
        return {
            "capital_usd": float(self.capital_usd),
            "current_risk_usd": round(float(self.current_risk_usd), 6),
            "added_risk_usd": round(float(self.added_risk_usd), 6),
            "total_risk_usd": round(float(self.total_risk_usd), 6),
            "current_risk_pct": round(
                float(self.current_risk_pct), 4,
            ),
            "added_risk_pct": round(float(self.added_risk_pct), 4),
            "total_risk_pct": round(float(self.total_risk_pct), 4),
            "sl_used_for_calc": float(self.sl_used_for_calc),
        }


__all__ = [
    "AggregatedRiskSnapshot",
    "ExposureState",
    "PositionEntry",
    "PositionState",
]
