"""
DurationSpec - prazo definido de demo (FASE 30.0)
==================================================
Modela a duracao de uma sessao demo com PRAZO DEFINIDO. Aceita
exatamente UMA de:
    - duration_minutes  (demo curta: 30, 60, 120...)
    - duration_days     (demo longa: 1, 3, 7...)

NUNCA aceita execucao indefinida. NAO existe --no-max-time. Toda demo
tem inicio e fim definidos (requisito 9).

Frozen, JSON-serializavel, ZERO rede, ZERO secret.

cycle_interval_seconds default = 60 (requisito 2). expected_cycles eh
floor(total_wall_clock_seconds / cycle_interval_seconds).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


_DEFAULT_CYCLE_INTERVAL_SECONDS: float = 60.0
_SECONDS_PER_MINUTE: int = 60
_MINUTES_PER_DAY: int = 24 * 60
# Fronteira curta/longa: <= 2h eh "short"; > 2h ou qualquer dia eh "long".
_SHORT_MAX_MINUTES: int = 120


@dataclass(frozen=True)
class DurationSpec:
    """Especificacao de prazo de uma demo (curta ou longa).

    Exatamente uma de duration_minutes / duration_days deve ser > 0.
    """

    duration_minutes: Optional[int] = None
    duration_days: Optional[int] = None
    cycle_interval_seconds: float = _DEFAULT_CYCLE_INTERVAL_SECONDS

    def __post_init__(self) -> None:
        has_min = self.duration_minutes is not None
        has_days = self.duration_days is not None
        if has_min == has_days:
            raise ValueError(
                "informe EXATAMENTE uma de duration_minutes XOR "
                f"duration_days (min={self.duration_minutes!r}, "
                f"days={self.duration_days!r})"
            )
        if has_min and int(self.duration_minutes) <= 0:
            raise ValueError(
                f"duration_minutes deve ser > 0: {self.duration_minutes}"
            )
        if has_days and int(self.duration_days) <= 0:
            raise ValueError(
                f"duration_days deve ser > 0: {self.duration_days}"
            )
        if self.cycle_interval_seconds < 1:
            raise ValueError(
                "cycle_interval_seconds deve ser >= 1: "
                f"{self.cycle_interval_seconds}"
            )

    @property
    def total_wall_clock_seconds(self) -> float:
        """Segundos totais de relogio de parede da janela da demo."""
        if self.duration_minutes is not None:
            return float(self.duration_minutes) * _SECONDS_PER_MINUTE
        return float(self.duration_days) * _MINUTES_PER_DAY * _SECONDS_PER_MINUTE

    @property
    def total_wall_clock_minutes(self) -> float:
        return self.total_wall_clock_seconds / _SECONDS_PER_MINUTE

    @property
    def expected_cycles(self) -> int:
        """floor(total_seconds / cycle_interval_seconds). Sempre >= 1."""
        cycles = int(
            self.total_wall_clock_seconds // self.cycle_interval_seconds
        )
        return max(1, cycles)

    @property
    def kind(self) -> str:
        """'short' (<= 2h) ou 'long' (> 2h / qualquer numero de dias)."""
        if self.duration_days is not None:
            return "long"
        if int(self.duration_minutes) > _SHORT_MAX_MINUTES:
            return "long"
        return "short"

    @property
    def is_long(self) -> bool:
        return self.kind == "long"

    def to_dict(self) -> dict:
        return {
            "duration_minutes": (
                int(self.duration_minutes)
                if self.duration_minutes is not None else None
            ),
            "duration_days": (
                int(self.duration_days)
                if self.duration_days is not None else None
            ),
            "cycle_interval_seconds": float(self.cycle_interval_seconds),
            "total_wall_clock_seconds": float(self.total_wall_clock_seconds),
            "total_wall_clock_minutes": float(self.total_wall_clock_minutes),
            "expected_cycles": int(self.expected_cycles),
            "kind": self.kind,
        }

    def __repr__(self) -> str:
        if self.duration_minutes is not None:
            dur = f"{self.duration_minutes}min"
        else:
            dur = f"{self.duration_days}d"
        return (
            f"DurationSpec({dur}, interval={self.cycle_interval_seconds}s, "
            f"expected_cycles={self.expected_cycles}, kind={self.kind})"
        )


__all__ = ["DurationSpec"]
