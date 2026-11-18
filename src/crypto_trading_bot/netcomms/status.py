"""
NetComms — modelo de status de comunicacao de rede (infra; FASE 43
realocado da antiga UI). Status VISIVEL/auditavel de cada operacao de
rede. NUNCA contem secret/header/signature. presence/estado apenas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

STATES = (
    "not_configured", "disconnected", "connecting", "connected", "ready",
    "stale", "failed", "blocked", "rate_limited", "manual_review_required",
)


@dataclass(frozen=True)
class ConnectionStatus:
    operation: str
    state: str
    detail: str = ""
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    last_error_sanitized: Optional[str] = None
    latency_ms: Optional[float] = None
    gated: bool = True

    def __post_init__(self) -> None:
        if self.state not in STATES:
            object.__setattr__(self, "state", "failed")

    def to_dict(self) -> dict:
        # presence-only / sem secret.
        return {
            "operation": self.operation, "state": self.state,
            "detail": self.detail, "last_success": self.last_success,
            "last_failure": self.last_failure,
            "last_error_sanitized": self.last_error_sanitized,
            "latency_ms": self.latency_ms, "gated": self.gated,
        }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["ConnectionStatus", "STATES", "now_iso"]
