"""
MarketContextProvider (FASE 36 Bloco D)
========================================
Interface READ-ONLY de fontes de contexto de mercado.

⚠️  REGRAS: somente leitura; nunca aposta/ordem; nunca decide trade;
    nunca sobrepoe RiskEngine; fonte ausente NUNCA e condicao
    obrigatoria (registra unavailable/stale/inconclusive e segue);
    contexto so REDUZ permissao (cautela/manual review).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional, Protocol, Tuple, \
    runtime_checkable


@dataclass(frozen=True)
class ContextSlice:
    """Resultado de UMA fonte de contexto (sanitizado)."""

    source: str
    available: bool
    fetched_at: Optional[datetime] = None
    ttl_seconds: float = 300.0
    stale: bool = False
    conclusive: bool = True
    confidence: float = 0.0          # 0..1
    risk_flags: Tuple[str, ...] = field(default_factory=tuple)
    data: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence em [0,1]")
        if not isinstance(self.risk_flags, tuple):
            object.__setattr__(
                self, "risk_flags", tuple(self.risk_flags),
            )
        if not isinstance(self.data, MappingProxyType):
            object.__setattr__(
                self, "data", MappingProxyType(dict(self.data)),
            )
        if self.fetched_at is not None and \
                self.fetched_at.tzinfo is None:
            object.__setattr__(
                self, "fetched_at",
                self.fetched_at.replace(tzinfo=timezone.utc),
            )

    def age_seconds(self, now: Optional[datetime] = None) -> float:
        if self.fetched_at is None:
            return float("inf")
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return max(0.0, (now - self.fetched_at).total_seconds())

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "available": bool(self.available),
            "fetched_at": (
                self.fetched_at.isoformat()
                if self.fetched_at else None
            ),
            "ttl_seconds": float(self.ttl_seconds),
            "stale": bool(self.stale),
            "conclusive": bool(self.conclusive),
            "confidence": float(self.confidence),
            "risk_flags": list(self.risk_flags),
            "data": dict(self.data),
            "error": self.error,
        }


def unavailable_slice(source: str, error: str = "") -> ContextSlice:
    """Fonte indisponivel: registrada, nunca bloqueante."""
    return ContextSlice(
        source=source, available=False, conclusive=False,
        error=error[:120] or "unavailable",
    )


@runtime_checkable
class MarketContextProvider(Protocol):
    """Protocolo de fonte read-only."""

    @property
    def source_name(self) -> str: ...

    def fetch(self) -> ContextSlice: ...


__all__ = [
    "ContextSlice",
    "MarketContextProvider",
    "unavailable_slice",
]
