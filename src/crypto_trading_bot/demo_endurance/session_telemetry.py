"""
Session Telemetry (FASE 28)
================================
Camada offline de observabilidade operacional para Demo30MinRealRunner.

⚠️  ZERO importacao de rede / API. Tudo trabalha sobre dicts ja
    sanitizados pelos colaboradores (provider, gate, post-check).

⚠️  NUNCA persiste:
    - api_key, api_secret;
    - Bearer / X-BAPI-SIGN / Authorization / sign= / signature;
    - origin_string;
    - .env paths;
    - operator_token completo.

Operator token aparece apenas em forma truncada (8 chars + "...").
Strings longas truncadas a 200 chars.

Append-only: SessionTelemetryRecorder.events eh tupla imutavel.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


# Tipos de evento estavel - contrato auditavel.
_VALID_EVENT_TYPES = frozenset({
    "session_start",
    "preflight_done",
    "cycle_start",
    "signal_evaluated",
    "risk_validated",
    "ensure_fresh_called",
    "gate_invoked",
    "post_check_done",
    "api_failure",
    "safety_event",
    "session_end",
    # FASE 29 - exit management (eram gravados como fallback
    # api_failure por ausencia nesta allowlist; registro ADITIVO).
    "exit_monitoring_started",
    "position_snapshot",
    "exit_policy_evaluated",
    "exit_detected",
    "exit_gate_invoked",
    "exit_order_submitted",
    "flat_check_done",
    "pnl_recorded",
    # FASE 30/30.1 - demo endurance real-time + observacao.
    "stale_market_data",
    "would_order_recorded",
    "hourly_snapshot",
    "daily_summary",
    "side_blocked_by_profile",
    "phase29_short_gate_checked",
    # FASE 32 - IA consultiva.
    "ai_context_built",
    "ai_advice_generated",
    "ai_veto_triggered",
    "ai_manual_review_requested",
    # FASE 34 - prediction markets read-only.
    "prediction_context_loaded",
    "prediction_context_stale",
    "prediction_context_unavailable",
    "prediction_market_risk_flagged",
    "prediction_context_attached_to_ai",
    # FASE 30.2 - multi-ordem real demo sequencial.
    "state_transition",
    "order_submitted",
    "sl_tp_confirmed",
    # FASE 36 - Decision Trace + Operator Inputs + Options + MI.
    "decision_trace_recorded",
    "operator_input_missing",
    "options_snapshot_emitted",
    "market_context_loaded",
    "market_context_stale",
    "market_context_unavailable",
    "scale_in_proposed",
    "scale_in_blocked",
    "partial_reduce_executed",
    "reversal_candidate_blocked",
})


# Substrings sensiveis: aparicao em valor string redige o campo
# inteiro ou substitui por "<redacted>".
_SECRET_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:", "origin_string",
)


# Strings longas sao truncadas a este limite.
_STRING_TRUNCATE = 200


def _sanitize_value(value: Any) -> Any:
    """Sanitiza valor para serializacao.

    - dict -> recursivo
    - list/tuple -> recursivo
    - str -> trunca + verifica substrings sensiveis
    - resto -> retorna como esta (numerico/bool/None)
    """
    if isinstance(value, dict):
        return {k: _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, datetime):
        return value.isoformat() if value.tzinfo else value.replace(
            tzinfo=timezone.utc).isoformat()
    return value


def _sanitize_string(text: str) -> str:
    if not isinstance(text, str):
        return text
    lower = text.lower()
    for tok in _SECRET_SUBSTRINGS:
        if tok in lower:
            return "<redacted>"
    if len(text) > _STRING_TRUNCATE:
        return text[:_STRING_TRUNCATE] + "..."
    return text


def _sanitize_operator_token(token: Optional[str]) -> str:
    """Token: max 8 chars + '...'. NUNCA aparece completo."""
    if not isinstance(token, str):
        return "<empty>"
    token = token.strip()
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return token + "..."
    return token[:8] + "..."


def _safe_path(path: str) -> Path:
    p = Path(path)
    if any(part == ".." for part in p.parts):
        raise ValueError(f"telemetry path contains '..' (rejected): {path}")
    return p


@dataclass(frozen=True)
class SessionTelemetryEvent:
    """Evento imutavel de telemetria.

    Atributos:
        event_type:  um de _VALID_EVENT_TYPES.
        cycle_idx:   indice do ciclo (None para session_start/end).
        timestamp:   tz-aware UTC.
        snapshot:    dict sanitizado (imutavel via MappingProxyType).
    """
    event_type: str
    cycle_idx: Optional[int]
    timestamp: datetime
    snapshot: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if self.event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"event_type invalido: {self.event_type!r}; "
                f"aceitos: {sorted(_VALID_EVENT_TYPES)}"
            )
        if self.cycle_idx is not None and not isinstance(
                self.cycle_idx, int
        ):
            raise TypeError("cycle_idx deve ser int ou None")
        if self.cycle_idx is not None and self.cycle_idx < 0:
            raise ValueError(
                f"cycle_idx deve ser >= 0: {self.cycle_idx}"
            )
        if self.timestamp.tzinfo is None:
            object.__setattr__(
                self, "timestamp",
                self.timestamp.replace(tzinfo=timezone.utc),
            )
        sanitized = _sanitize_value(dict(self.snapshot or {}))
        if not isinstance(sanitized, dict):
            sanitized = {}
        object.__setattr__(
            self, "snapshot", MappingProxyType(sanitized),
        )

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "cycle_idx": self.cycle_idx,
            "timestamp": self.timestamp.isoformat(),
            "snapshot": dict(self.snapshot),
        }


class SessionTelemetryRecorder:
    """Recorder append-only de eventos de sessao.

    Args:
        clock: callable() -> datetime UTC. Default datetime.now(UTC).
        operator_token: token bruto, sera SEMPRE sanitizado para o
                        snapshot via _sanitize_operator_token.
        max_events:     hard cap defensivo (default 5000). Excede ->
                        warning sanitizado registrado, novos eventos
                        sao descartados silenciosamente para nao
                        consumir memoria.
    """

    def __init__(
        self,
        *,
        clock=None,
        operator_token: str = "",
        max_events: int = 5000,
    ) -> None:
        from datetime import datetime as _dt, timezone as _tz
        self._clock = clock or (
            lambda: _dt.now(_tz.utc)
        )
        if not isinstance(max_events, int) or max_events <= 0:
            raise ValueError(
                f"max_events deve ser int > 0: {max_events}"
            )
        self._max_events = int(max_events)
        self._operator_token_sanitized = _sanitize_operator_token(
            operator_token
        )
        self._events: list = []
        self._overflow_count = 0

    @property
    def events(self) -> Tuple[SessionTelemetryEvent, ...]:
        """Tupla imutavel dos eventos registrados (append-only)."""
        return tuple(self._events)

    @property
    def operator_token_sanitized(self) -> str:
        return self._operator_token_sanitized

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    def record(
        self,
        event_type: str,
        *,
        cycle_idx: Optional[int] = None,
        snapshot: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Adiciona evento sanitizado. Idempotente em overflow."""
        if len(self._events) >= self._max_events:
            self._overflow_count += 1
            return
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        snap = dict(snapshot or {})
        # Inject operator_token sanitizado em todo snapshot.
        snap.setdefault(
            "operator_token_sanitized",
            self._operator_token_sanitized,
        )
        try:
            ev = SessionTelemetryEvent(
                event_type=event_type,
                cycle_idx=cycle_idx,
                timestamp=now,
                snapshot=snap,
            )
        except (ValueError, TypeError):
            # Defesa em profundidade: nunca explode caller.
            # Registra evento de fallback documentando o erro
            # (sem expor input bruto).
            fallback = SessionTelemetryEvent(
                event_type="api_failure",
                cycle_idx=cycle_idx,
                timestamp=now,
                snapshot={
                    "telemetry_error": "invalid event input rejected",
                    "operator_token_sanitized":
                        self._operator_token_sanitized,
                },
            )
            self._events.append(fallback)
            return
        self._events.append(ev)

    def to_json(self) -> str:
        """JSON sanitizado (lista de eventos)."""
        return json.dumps(
            [e.to_dict() for e in self._events],
            indent=2, sort_keys=True, default=str,
        )

    def to_jsonl(self) -> str:
        """JSONL: uma linha por evento (ordem cronologica de gravacao)."""
        lines = [
            json.dumps(e.to_dict(), sort_keys=True, default=str)
            for e in self._events
        ]
        return "\n".join(lines) + ("\n" if lines else "")

    def to_jsonl_file(self, path: str) -> Path:
        """Grava JSONL em arquivo sanitizado.

        Raises:
            ValueError: path contem '..' OU JSONL contem tokens sensiveis
                        apos sanitizacao (defesa adicional).
        """
        target = _safe_path(path)
        text = self.to_jsonl()
        lower = text.lower()
        for tok in _SECRET_SUBSTRINGS:
            if tok in lower:
                raise ValueError(
                    "telemetry payload contains suspicious token "
                    "after sanitization; refusing to write"
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


__all__ = [
    "SessionTelemetryEvent",
    "SessionTelemetryRecorder",
]
