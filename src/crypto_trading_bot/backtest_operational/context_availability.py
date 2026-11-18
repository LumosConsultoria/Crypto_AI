"""
Backtest Context Availability (FASE 37 Parte E)
===============================================
IA / Polymarket / Market Intelligence dentro do backtest usam APENAS
dado REAL (snapshot/dataset historico). Garantias inviolaveis:

  * NUNCA inventar contexto. Ausencia de dado => `context_available=False`.
  * NUNCA look-ahead: so snapshots com `as_of <= timestamp_do_candle`
    sao visiveis (o que era conhecido naquele instante).
  * Contexto ausente: se opcional, segue (registra unavailable); se
    obrigatorio, bloqueia com `required_context_unavailable`.
  * O relatorio distingue: `enabled` (toggle ligado) vs
    `context_available` (havia dado real) vs `decision_impact` (o dado
    realmente influenciou a decisao).

Sem este modulo o backtest jamais "imagina" sentimento de mercado.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


class LookAheadError(Exception):
    """Tentativa de usar dado futuro no backtest (bias proibido)."""


# Kinds de contexto suportados (espelha os toggles do context).
CONTEXT_KINDS: Tuple[str, ...] = (
    "ai", "polymarket", "market_intelligence",
    "funding", "open_interest", "orderbook", "news",
)


@dataclass(frozen=True)
class ContextSnapshot:
    """Snapshot REAL de contexto, datado (as_of em UTC)."""
    kind: str
    as_of: datetime
    data: Mapping[str, Any]
    source: str = "dataset"
    confidence: Optional[float] = None

    def __post_init__(self) -> None:
        if self.kind not in CONTEXT_KINDS:
            raise ValueError(f"context kind desconhecido: {self.kind!r}")
        if self.as_of.tzinfo is None:
            object.__setattr__(
                self, "as_of", self.as_of.replace(tzinfo=timezone.utc))


@dataclass(frozen=True)
class ContextAvailability:
    """Resultado da resolucao de um contexto em um instante.

    enabled            -> toggle ligado no contexto de execucao.
    context_available  -> havia dado REAL conhecido em <= timestamp.
    decision_impact    -> o dado efetivamente influenciou a decisao.
    blocked            -> contexto obrigatorio e indisponivel.
    """
    kind: str
    enabled: bool
    context_available: bool
    decision_impact: bool = False
    blocked: bool = False
    as_of: Optional[str] = None
    source: Optional[str] = None
    stale: bool = False
    reason: str = ""
    data: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "enabled": self.enabled,
            "context_available": self.context_available,
            "decision_impact": self.decision_impact,
            "blocked": self.blocked,
            "as_of": self.as_of,
            "source": self.source,
            "stale": self.stale,
            "reason": self.reason,
        }


class ContextDataset:
    """Colecao de snapshots reais por kind, ordenada por as_of.

    Resolve "o que era conhecido em <= ts" via busca binaria. NUNCA
    retorna snapshot com as_of > ts (anti look-ahead).
    """

    def __init__(
        self,
        snapshots: Optional[Sequence[ContextSnapshot]] = None,
        *,
        max_staleness_seconds: Optional[float] = None,
    ) -> None:
        self._by_kind: Dict[str, List[ContextSnapshot]] = {}
        self._ts_by_kind: Dict[str, List[datetime]] = {}
        self._max_stale = max_staleness_seconds
        for snap in (snapshots or []):
            self.add(snap)

    def add(self, snap: ContextSnapshot) -> None:
        lst = self._by_kind.setdefault(snap.kind, [])
        lst.append(snap)
        lst.sort(key=lambda s: s.as_of)
        self._ts_by_kind[snap.kind] = [s.as_of for s in lst]

    def has_kind(self, kind: str) -> bool:
        return bool(self._by_kind.get(kind))

    def get_as_of(
        self, kind: str, ts: datetime,
    ) -> Optional[ContextSnapshot]:
        """Snapshot mais recente com as_of <= ts (ou None). Anti-bias."""
        lst = self._by_kind.get(kind)
        if not lst:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        times = self._ts_by_kind[kind]
        idx = bisect.bisect_right(times, ts) - 1
        if idx < 0:
            return None
        snap = lst[idx]
        if snap.as_of > ts:  # defesa extra (nunca deveria ocorrer)
            raise LookAheadError(
                f"snapshot {kind} as_of {snap.as_of} > ts {ts}"
            )
        return snap

    def is_stale(self, snap: ContextSnapshot, ts: datetime) -> bool:
        if self._max_stale is None:
            return False
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (ts - snap.as_of).total_seconds() > self._max_stale


def resolve_context(
    *,
    kind: str,
    enabled: bool,
    dataset: Optional[ContextDataset],
    current_ts: datetime,
    required: bool = False,
    allow_missing: bool = True,
) -> ContextAvailability:
    """Resolve um contexto em `current_ts`, sem inventar e sem look-ahead.

    - toggle OFF  -> enabled=False, context_available=False.
    - toggle ON, sem dataset/snapshot <= ts -> context_available=False;
      se required e nao allow_missing -> blocked=True (reason=
      required_context_unavailable).
    - toggle ON com snapshot real -> context_available=True (decision_
      impact e marcado depois, so se o dado realmente mudar a decisao).
    """
    if not enabled:
        return ContextAvailability(
            kind=kind, enabled=False, context_available=False,
            reason="disabled",
        )

    snap = dataset.get_as_of(kind, current_ts) if dataset else None
    if snap is None:
        blocked = required and not allow_missing
        return ContextAvailability(
            kind=kind, enabled=True, context_available=False,
            blocked=blocked,
            reason=(
                "required_context_unavailable" if blocked
                else "context_unavailable"
            ),
        )

    stale = dataset.is_stale(snap, current_ts) if dataset else False
    return ContextAvailability(
        kind=kind, enabled=True, context_available=True,
        as_of=snap.as_of.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"),
        source=snap.source, stale=stale,
        reason="context_available_stale" if stale else "context_available",
        data=snap.data,
    )


def with_decision_impact(
    avail: ContextAvailability, *, impact: bool, reason: str = "",
) -> ContextAvailability:
    """Marca se o contexto disponivel influenciou a decisao."""
    return ContextAvailability(
        kind=avail.kind, enabled=avail.enabled,
        context_available=avail.context_available,
        decision_impact=bool(impact and avail.context_available),
        blocked=avail.blocked, as_of=avail.as_of, source=avail.source,
        stale=avail.stale,
        reason=reason or avail.reason, data=avail.data,
    )


__all__ = [
    "CONTEXT_KINDS",
    "ContextAvailability",
    "ContextDataset",
    "ContextSnapshot",
    "LookAheadError",
    "resolve_context",
    "with_decision_impact",
]
