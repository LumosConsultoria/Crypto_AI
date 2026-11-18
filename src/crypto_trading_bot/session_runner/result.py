"""
SessionRunner — tipos de resultado (FASE 17)
==============================================
⚠️  Frozen dataclasses, serializáveis, sem secrets.
⚠️  PROVIDER-AGNOSTIC. Não importa BybitClient/BybitDemoExecutor/httpx.

Tipos:
    SessionStopReason  — enum estável dos motivos de encerramento.
    SessionBlockEvent  — registro imutável de cada bloqueio durante a sessão.
    SessionRunResult   — relatório final imutável da sessão.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Tuple


# ---------------------------------------------------------------------------
# SessionStopReason
# ---------------------------------------------------------------------------

class SessionStopReason(str, Enum):
    """
    Motivo do encerramento da sessão.

    Valores são contrato — não renomear sem nova fase de quebra.

    MAX_CYCLES               — sessão atingiu max_cycles solicitados.
    MANUAL_STOP              — operador chamou stop() externamente.
    TIME_LIMIT               — profile.max_session_minutes ultrapassado.
    PROFILE_TRADES_LIMIT     — profile.max_trades_per_session atingido.
    PROFILE_CONSECUTIVE_LOSSES — profile.pause_after_consecutive_losses atingido.
    PROFILE_SYMBOL_NOT_ALLOWED — symbol não está em profile.allowed_symbols
                                  (pre-flight; sessão encerra antes do 1º ciclo).
    KILL_SWITCH              — kill_switch_enabled + safety state crítico.
    SAFETY_HALT_ACTIVE       — sessão encerrada por estado SAFETY_HALT_ACTIVE
                                  com kill_switch desligado, mas operador
                                  parou explicitamente.
    ERROR                    — exceção não tratada em ciclo (preservado e
                                  reportado em audit).
    """
    MAX_CYCLES = "max_cycles"
    MANUAL_STOP = "manual_stop"
    TIME_LIMIT = "time_limit"
    PROFILE_TRADES_LIMIT = "profile_trades_limit"
    PROFILE_CONSECUTIVE_LOSSES = "profile_consecutive_losses"
    PROFILE_SYMBOL_NOT_ALLOWED = "profile_symbol_not_allowed"
    KILL_SWITCH = "kill_switch"
    SAFETY_HALT_ACTIVE = "safety_halt_active"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Block sources (estáveis)
# ---------------------------------------------------------------------------

# Estes valores aparecem em SessionBlockEvent.block_source. Mantidos como
# strings literais para serialização estável; centralizadas para auditoria.
BLOCK_SAFETY_STATE = "safety_state"
BLOCK_PROFILE_CONCURRENT = "profile_concurrent"
BLOCK_PROFILE_HOURS = "profile_hours"
BLOCK_PROFILE_CONSECUTIVE_LOSSES = "profile_consecutive_losses"
BLOCK_PROFILE_TRADES_PER_SESSION = "profile_trades_per_session"
BLOCK_PROFILE_TIME_LIMIT = "profile_time_limit"
BLOCK_RISK_ENGINE = "risk_engine"

_VALID_BLOCK_SOURCES: frozenset = frozenset({
    BLOCK_SAFETY_STATE,
    BLOCK_PROFILE_CONCURRENT,
    BLOCK_PROFILE_HOURS,
    BLOCK_PROFILE_CONSECUTIVE_LOSSES,
    BLOCK_PROFILE_TRADES_PER_SESSION,
    BLOCK_PROFILE_TIME_LIMIT,
    BLOCK_RISK_ENGINE,
})

# Conjuntos auxiliares para agregação por categoria
_PROFILE_BLOCK_SOURCES: frozenset = frozenset({
    BLOCK_PROFILE_CONCURRENT,
    BLOCK_PROFILE_HOURS,
    BLOCK_PROFILE_CONSECUTIVE_LOSSES,
    BLOCK_PROFILE_TRADES_PER_SESSION,
    BLOCK_PROFILE_TIME_LIMIT,
})


# ---------------------------------------------------------------------------
# SessionBlockEvent
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionBlockEvent:
    """
    Registro imutável de um bloqueio durante a sessão.

    Frozen. metadata é MappingProxyType. NUNCA contém secrets.

    Atributos:
        cycle_index:    índice 0-based do ciclo onde o bloqueio ocorreu
                        (-1 quando pre-flight).
        block_source:   string identificadora; deve estar em
                        _VALID_BLOCK_SOURCES.
        reason:         texto sanitizado para humano-legibilidade.
        triggered_at:   timestamp UTC tz-aware.
        metadata:       Mapping imutável; campos auxiliares de auditoria.
    """
    cycle_index: int
    block_source: str
    reason: str
    triggered_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if self.block_source not in _VALID_BLOCK_SOURCES:
            raise ValueError(
                f"block_source inválido: {self.block_source!r}. "
                f"Aceitos: {sorted(_VALID_BLOCK_SOURCES)}"
            )
        if not isinstance(self.reason, str):
            raise TypeError(
                f"reason deve ser str; recebido {type(self.reason).__name__}"
            )
        if self.triggered_at.tzinfo is None:
            object.__setattr__(
                self, "triggered_at",
                self.triggered_at.replace(tzinfo=timezone.utc),
            )
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )

    def to_dict(self) -> dict:
        return {
            "cycle_index": self.cycle_index,
            "block_source": self.block_source,
            "reason": self.reason,
            "triggered_at": self.triggered_at.isoformat(),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# SessionRunResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionRunResult:
    """
    Relatório final imutável da sessão.

    Frozen. blocks é tuple imutável. NUNCA contém secrets.

    Métricas (mínimo agregado):
        total_cycles_requested:    max_cycles do config (config solicitado).
        total_cycles_completed:    quantos ciclos foram efetivamente rodados.
        trades_opened:             total acumulado de trades abertos na sessão.
        trades_closed:             total acumulado de trades fechados na sessão.
        pnl_paper:                 PnL simulado acumulado (soma dos closed).
        drawdown_paper:            pior drawdown observado durante a sessão.
        consecutive_losses_final:  contador de losses consecutivos ao final.
        blocks:                    tuple imutável de SessionBlockEvent.
        blocks_by_safety:          contador (cache).
        blocks_by_profile:         contador (cache).
        blocks_by_risk:            contador (cache).
        total_blocks:              len(blocks) — consistente com a soma.
        final_safety_state:        SafetyState.value da máquina ao final.
        stopped_reason:            SessionStopReason.
        started_at / ended_at:     timestamps UTC.
    """
    total_cycles_requested: int
    total_cycles_completed: int
    trades_opened: int
    trades_closed: int
    pnl_paper: float
    drawdown_paper: float
    consecutive_losses_final: int
    blocks: Tuple[SessionBlockEvent, ...]
    blocks_by_safety: int
    blocks_by_profile: int
    blocks_by_risk: int
    total_blocks: int
    final_safety_state: str
    stopped_reason: SessionStopReason
    started_at: datetime
    ended_at: datetime

    def __post_init__(self) -> None:
        # blocks deve ser tuple imutável
        if not isinstance(self.blocks, tuple):
            object.__setattr__(self, "blocks", tuple(self.blocks))
        # timestamps tz-aware
        for attr in ("started_at", "ended_at"):
            v: datetime = getattr(self, attr)
            if v.tzinfo is None:
                object.__setattr__(self, attr, v.replace(tzinfo=timezone.utc))
        # Consistência total_blocks
        if self.total_blocks != len(self.blocks):
            raise ValueError(
                f"total_blocks={self.total_blocks} != len(blocks)={len(self.blocks)}"
            )
        agg = self.blocks_by_safety + self.blocks_by_profile + self.blocks_by_risk
        if agg != self.total_blocks:
            raise ValueError(
                f"Inconsistência: total_blocks={self.total_blocks} != "
                f"safety({self.blocks_by_safety})+profile("
                f"{self.blocks_by_profile})+risk({self.blocks_by_risk})="
                f"{agg}"
            )

    @classmethod
    def from_blocks(
        cls,
        *,
        total_cycles_requested: int,
        total_cycles_completed: int,
        trades_opened: int,
        trades_closed: int,
        pnl_paper: float,
        drawdown_paper: float,
        consecutive_losses_final: int,
        blocks: Tuple[SessionBlockEvent, ...] | list,
        final_safety_state: str,
        stopped_reason: SessionStopReason,
        started_at: datetime,
        ended_at: datetime,
    ) -> "SessionRunResult":
        """Construtor que calcula contadores agregados a partir de `blocks`."""
        blocks_tuple = tuple(blocks)
        n_safety = sum(
            1 for b in blocks_tuple if b.block_source == BLOCK_SAFETY_STATE
        )
        n_profile = sum(
            1 for b in blocks_tuple if b.block_source in _PROFILE_BLOCK_SOURCES
        )
        n_risk = sum(
            1 for b in blocks_tuple if b.block_source == BLOCK_RISK_ENGINE
        )
        return cls(
            total_cycles_requested=total_cycles_requested,
            total_cycles_completed=total_cycles_completed,
            trades_opened=trades_opened,
            trades_closed=trades_closed,
            pnl_paper=pnl_paper,
            drawdown_paper=drawdown_paper,
            consecutive_losses_final=consecutive_losses_final,
            blocks=blocks_tuple,
            blocks_by_safety=n_safety,
            blocks_by_profile=n_profile,
            blocks_by_risk=n_risk,
            total_blocks=len(blocks_tuple),
            final_safety_state=final_safety_state,
            stopped_reason=stopped_reason,
            started_at=started_at,
            ended_at=ended_at,
        )

    def to_dict(self) -> dict:
        return {
            "total_cycles_requested": self.total_cycles_requested,
            "total_cycles_completed": self.total_cycles_completed,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "pnl_paper": self.pnl_paper,
            "drawdown_paper": self.drawdown_paper,
            "consecutive_losses_final": self.consecutive_losses_final,
            "blocks": [b.to_dict() for b in self.blocks],
            "blocks_by_safety": self.blocks_by_safety,
            "blocks_by_profile": self.blocks_by_profile,
            "blocks_by_risk": self.blocks_by_risk,
            "total_blocks": self.total_blocks,
            "final_safety_state": self.final_safety_state,
            "stopped_reason": self.stopped_reason.value,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
        }
