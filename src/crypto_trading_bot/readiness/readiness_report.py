"""
ReadinessReport (FASE 35)
==========================
Relatorio consolidado do readiness supervisionado.

⚠️  CONSULTIVO: 'ready' NAO habilita live/mainnet. Decisao final eh
    SEMPRE humana e supervisionada, com gates proprios em fase futura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Tuple

from crypto_trading_bot.readiness.readiness_rules import (
    ReadinessEvidence,
)


class ReadinessVerdict(str, Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    INSUFFICIENT_HISTORY = "insufficient_history"
    # FASE 36 Bloco F - verdicts operacionais novos.
    INSUFFICIENT_INFORMATION = "insufficient_information"
    BLOCKED_MISSING_LIMITS = "blocked_missing_limits"
    BLOCKED_MISSING_CREDENTIALS = "blocked_missing_credentials"
    BLOCKED_STALE_DATA = "blocked_stale_data"
    BLOCKED_UNRESOLVED_POSITION = "blocked_unresolved_position"
    BLOCKED_UNRESOLVED_RISK_POLICY = "blocked_unresolved_risk_policy"
    BLOCKED_MISSING_OPERATOR_INPUT = "blocked_missing_operator_input"


@dataclass(frozen=True)
class ReadinessReport:
    """Resultado consolidado. Frozen, JSON-serializavel, sem secrets."""

    verdict: ReadinessVerdict
    profile_name: str
    evaluated_at: datetime
    evidence: ReadinessEvidence
    blockers: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    reports_scanned: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, ReadinessVerdict):
            raise TypeError("verdict deve ser ReadinessVerdict")
        if self.evaluated_at.tzinfo is None:
            object.__setattr__(
                self, "evaluated_at",
                self.evaluated_at.replace(tzinfo=timezone.utc),
            )
        for tup_field in ("blockers", "warnings"):
            val = getattr(self, tup_field)
            if not isinstance(val, tuple):
                object.__setattr__(self, tup_field, tuple(val))

    @property
    def is_ready(self) -> bool:
        return self.verdict is ReadinessVerdict.READY

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "profile_name": self.profile_name,
            "evaluated_at": self.evaluated_at.isoformat(),
            "evidence": self.evidence.to_dict(),
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "reports_scanned": int(self.reports_scanned),
            "note": (
                "CONSULTIVO: 'ready' NAO habilita live/mainnet. "
                "Decisao final e humana, supervisionada e gated."
            ),
        }

    def human_summary(self) -> str:
        lines = [
            "=" * 72,
            "  SUPERVISED READINESS (FASE 35) - CONSULTIVO",
            "  'ready' NAO habilita live/mainnet por si.",
            "=" * 72,
            f"  verdict:           {self.verdict.value}",
            f"  profile:           {self.profile_name}",
            f"  reports_scanned:   {self.reports_scanned}",
            f"  sessions:          {self.evidence.total_sessions}",
            f"  short clean:       "
            f"{self.evidence.short_demo_clean_count}",
            f"  long completed:    "
            f"{self.evidence.long_demo_completed_count}",
        ]
        if self.blockers:
            lines.append("  blockers:")
            for b in self.blockers:
                lines.append(f"    - {b}")
        if self.warnings:
            lines.append("  warnings:")
            for w in self.warnings:
                lines.append(f"    - {w}")
        lines.append("=" * 72)
        return "\n".join(lines)


__all__ = ["ReadinessReport", "ReadinessVerdict"]
