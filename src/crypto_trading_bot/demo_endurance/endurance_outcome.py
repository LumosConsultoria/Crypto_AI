"""
DemoEnduranceOutcome - resultado de uma demo endurance (FASE 30)
=================================================================
Outcome consolidado de uma sessao demo real-time curta/longa.

⚠️  NAO reusa Demo30MinOutcome (FASE 26/29) para nao colidir com seus
    invariantes. Este eh o contrato do NOVO runner DemoEnduranceRunner.

⚠️  Frozen, JSON-serializavel, ZERO secret.

⚠️  Em wired dry-run (FASE 30), NUNCA usar ORDER_COMPLETED como se
    fosse ordem real. Usar WOULD_ORDER_COMPLETED ou
    DRY_RUN_WOULD_ORDER_COMPLETED. orders_submitted permanece 0;
    would_orders pode ser >= 1.

Campos obrigatorios do report/telemetry (spec FASE 30):
    real_time_mode, time_compressed, started_at, ended_at,
    elapsed_wall_clock_seconds, elapsed_wall_clock_minutes,
    cycle_interval_seconds, configured_duration_minutes,
    configured_duration_days, cycles_completed, expected_cycles,
    ended_reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


class EnduranceEndedReason(str, Enum):
    """Razao de encerramento de uma demo endurance.

    duration_completed:
        Janela de prazo definida foi esgotada normalmente.
    would_order_completed:
        Em dry-run, a sessao parou apos contabilizar a would-order
        (single-order default).
    dry_run_would_order_completed:
        Sinonimo explicito de would_order em wired dry-run; usado
        quando o gate foi invocado com dry_run=True e o caller quer
        deixar claro que NAO houve ordem real.
    max_would_orders_reached:
        Modo OBSERVACAO dry-run (continue_after_would_order): a
        sessao registrou multiplas would-orders e atingiu o teto
        --max-would-orders. Nenhuma ordem real; orders_submitted=0.
    order_completed:
        Reservado para fase futura com ordem REAL. Nunca usado em
        wired dry-run.
    passed_zero_trades:
        Janela esgotada sem nenhum sinal acionavel; resultado VALIDO.
    safety_halt:
        SafetyStateMachine recomendou halt.
    manual_review_required:
        Condicao que exige revisao do operador (limites, residuais...).
    api_failure:
        Falhas de API consecutivas acima do teto.
    operator_interrupted:
        Ctrl+C / interrupcao explicita do operador.
    graceful_shutdown:
        Encerramento limpo solicitado programaticamente.
    """
    DURATION_COMPLETED = "duration_completed"
    WOULD_ORDER_COMPLETED = "would_order_completed"
    DRY_RUN_WOULD_ORDER_COMPLETED = "dry_run_would_order_completed"
    MAX_WOULD_ORDERS_REACHED = "max_would_orders_reached"
    # FASE 30.2 - multi-ordem real demo sequencial.
    MAX_REAL_ORDERS_COMPLETED = "max_real_orders_completed"
    REAL_DEMO_MULTI_ORDER_COMPLETED = "real_demo_multi_order_completed"
    DURATION_COMPLETED_FLAT = "duration_completed_flat"
    DURATION_COMPLETED_WITH_NO_TRADE = "duration_completed_with_no_trade"
    ORDER_COMPLETED = "order_completed"
    PASSED_ZERO_TRADES = "passed_zero_trades"
    SAFETY_HALT = "safety_halt"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    API_FAILURE = "api_failure"
    OPERATOR_INTERRUPTED = "operator_interrupted"
    GRACEFUL_SHUTDOWN = "graceful_shutdown"


# Razoes proibidas em wired dry-run (defesa em profundidade).
_REAL_ORDER_ONLY_REASONS = frozenset({
    EnduranceEndedReason.ORDER_COMPLETED,
    EnduranceEndedReason.MAX_REAL_ORDERS_COMPLETED,
    EnduranceEndedReason.REAL_DEMO_MULTI_ORDER_COMPLETED,
})

_VALID_EXECUTION_MODES = ("wired_dry_run", "real_demo_multi_order")


@dataclass(frozen=True)
class DemoEnduranceOutcome:
    """Outcome frozen de uma sessao demo endurance (FASE 30).

    dry_run=True (wired dry-run) eh o UNICO modo da FASE 30:
        - orders_submitted DEVE ser 0;
        - ended_reason NUNCA pode ser ORDER_COMPLETED.
    """

    # Identificacao
    session_id: str
    profile_name: str
    symbol: str
    strategy_name: str

    # Modo de execucao (requisitos 5 da spec)
    real_time_mode: bool
    time_compressed: bool
    dry_run: bool

    # Prazo / relogio de parede
    started_at: datetime
    ended_at: datetime
    elapsed_wall_clock_seconds: float
    cycle_interval_seconds: float
    configured_duration_minutes: Optional[int]
    configured_duration_days: Optional[int]
    cycles_completed: int
    expected_cycles: int

    # Encerramento
    ended_reason: EnduranceEndedReason

    # Contadores de pipeline
    signals_evaluated: int = 0
    would_orders: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    safety_events: int = 0
    api_failures: int = 0

    # Tracking estruturado
    daily_summaries: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    hourly_snapshots: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    per_trade_records: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    session_summary: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    # ===================================================================
    # FASE 30.2 - campos ADITIVOS de execucao real multi-ordem
    # (defaults preservam contratos dry-run FASE 30/30.1).
    # ===================================================================
    execution_mode: str = "wired_dry_run"
    real_orders_enabled: bool = False
    max_real_orders: Optional[int] = None
    trades_completed: int = 0
    trades_open: int = 0
    trades_closed_by_tp: int = 0
    trades_closed_by_sl: int = 0
    trades_closed_by_reduce_only: int = 0
    trades_manual_review: int = 0
    total_realized_pnl: Optional[float] = None
    final_open_positions_count: int = 0
    final_open_orders_count: int = 0
    final_conditional_orders_count: int = 0
    final_flat_check_passed: Optional[bool] = None
    multi_order_gate_enabled: bool = False
    profile_multi_order_allowed: bool = False
    scale_in_allowed: bool = False        # SEMPRE False nesta fase
    auto_reversal_allowed: bool = False   # SEMPRE False nesta fase

    def __post_init__(self) -> None:
        if not isinstance(self.ended_reason, EnduranceEndedReason):
            raise TypeError(
                "ended_reason deve ser EnduranceEndedReason"
            )
        # Coerencia real-time vs time-compressed: exatamente um modo.
        if self.real_time_mode == self.time_compressed:
            raise ValueError(
                "real_time_mode e time_compressed devem ser opostos: "
                f"real_time={self.real_time_mode} "
                f"compressed={self.time_compressed}"
            )
        # FASE 30 wired dry-run: zero ordem real.
        if self.dry_run:
            if self.orders_submitted != 0:
                raise ValueError(
                    "dry_run=True exige orders_submitted == 0; "
                    f"recebido {self.orders_submitted}"
                )
            if self.orders_filled != 0:
                raise ValueError(
                    "dry_run=True exige orders_filled == 0; "
                    f"recebido {self.orders_filled}"
                )
            if self.ended_reason in _REAL_ORDER_ONLY_REASONS:
                raise ValueError(
                    "dry_run=True nao pode usar ended_reason="
                    f"{self.ended_reason.value!r}; use "
                    "would_order_completed / "
                    "dry_run_would_order_completed"
                )
        # FASE 30.2 - invariantes de execucao real.
        if self.execution_mode not in _VALID_EXECUTION_MODES:
            raise ValueError(
                f"execution_mode invalido: {self.execution_mode!r}; "
                f"aceitos: {list(_VALID_EXECUTION_MODES)}"
            )
        # Sem scale-in / sem reversao automatica nesta fase, SEMPRE.
        if self.scale_in_allowed:
            raise ValueError(
                "scale_in_allowed=True e proibido (FASE 30.2 = "
                "multi-ordem SEQUENCIAL, sem scale-in)"
            )
        if self.auto_reversal_allowed:
            raise ValueError(
                "auto_reversal_allowed=True e proibido (FASE 30.2 "
                "nao permite reversao automatica)"
            )
        if self.execution_mode == "real_demo_multi_order":
            if self.dry_run:
                raise ValueError(
                    "execution_mode=real_demo_multi_order exige "
                    "dry_run=False"
                )
            if not self.real_orders_enabled:
                raise ValueError(
                    "execution_mode=real_demo_multi_order exige "
                    "real_orders_enabled=True"
                )
            if self.max_real_orders is None or not (
                1 <= int(self.max_real_orders) <= 3
            ):
                raise ValueError(
                    "real_demo_multi_order exige max_real_orders em "
                    f"[1,3]; recebido {self.max_real_orders!r}"
                )
            if self.orders_submitted > int(self.max_real_orders):
                raise ValueError(
                    f"orders_submitted={self.orders_submitted} > "
                    f"max_real_orders={self.max_real_orders}"
                )
        else:
            # Dry-run nunca declara real_orders_enabled.
            if self.real_orders_enabled:
                raise ValueError(
                    "real_orders_enabled=True exige "
                    "execution_mode=real_demo_multi_order"
                )
        # NUNCA encerrar como concluido/clean com posicao aberta.
        if self.final_open_positions_count > 0 and self.ended_reason in (
            EnduranceEndedReason.MAX_REAL_ORDERS_COMPLETED,
            EnduranceEndedReason.REAL_DEMO_MULTI_ORDER_COMPLETED,
            EnduranceEndedReason.DURATION_COMPLETED_FLAT,
        ):
            raise ValueError(
                "posicao residual "
                f"({self.final_open_positions_count}) incompativel "
                f"com ended_reason={self.ended_reason.value!r}; use "
                "manual_review_required"
            )
        # Duracao: exatamente uma configurada.
        has_min = self.configured_duration_minutes is not None
        has_days = self.configured_duration_days is not None
        if has_min == has_days:
            raise ValueError(
                "exatamente uma de configured_duration_minutes XOR "
                "configured_duration_days"
            )
        if self.cycles_completed < 0:
            raise ValueError("cycles_completed < 0")
        if self.expected_cycles < 1:
            raise ValueError("expected_cycles < 1")
        if self.would_orders < 0:
            raise ValueError("would_orders < 0")
        if self.signals_evaluated < 0:
            raise ValueError("signals_evaluated < 0")
        if self.elapsed_wall_clock_seconds < 0:
            raise ValueError("elapsed_wall_clock_seconds < 0")
        # tz-aware
        if self.started_at.tzinfo is None:
            object.__setattr__(
                self, "started_at",
                self.started_at.replace(tzinfo=timezone.utc),
            )
        if self.ended_at.tzinfo is None:
            object.__setattr__(
                self, "ended_at",
                self.ended_at.replace(tzinfo=timezone.utc),
            )
        # Imutabilidade de colecoes
        if not isinstance(self.daily_summaries, tuple):
            object.__setattr__(
                self, "daily_summaries", tuple(self.daily_summaries),
            )
        if not isinstance(self.hourly_snapshots, tuple):
            object.__setattr__(
                self, "hourly_snapshots", tuple(self.hourly_snapshots),
            )
        if not isinstance(self.per_trade_records, tuple):
            object.__setattr__(
                self, "per_trade_records", tuple(self.per_trade_records),
            )
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if not isinstance(self.session_summary, MappingProxyType):
            object.__setattr__(
                self, "session_summary",
                MappingProxyType(dict(self.session_summary)),
            )
        # Sanitiza notes
        if not isinstance(self.notes, str):
            object.__setattr__(self, "notes", "")
        elif len(self.notes) > 200:
            object.__setattr__(self, "notes", self.notes[:200] + "...")

    @property
    def elapsed_wall_clock_minutes(self) -> float:
        return self.elapsed_wall_clock_seconds / 60.0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "profile_name": self.profile_name,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "real_time_mode": bool(self.real_time_mode),
            "time_compressed": bool(self.time_compressed),
            "dry_run": bool(self.dry_run),
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "elapsed_wall_clock_seconds": float(
                self.elapsed_wall_clock_seconds
            ),
            "elapsed_wall_clock_minutes": float(
                self.elapsed_wall_clock_minutes
            ),
            "cycle_interval_seconds": float(self.cycle_interval_seconds),
            "configured_duration_minutes": (
                int(self.configured_duration_minutes)
                if self.configured_duration_minutes is not None else None
            ),
            "configured_duration_days": (
                int(self.configured_duration_days)
                if self.configured_duration_days is not None else None
            ),
            "cycles_completed": int(self.cycles_completed),
            "expected_cycles": int(self.expected_cycles),
            "ended_reason": self.ended_reason.value,
            "signals_evaluated": int(self.signals_evaluated),
            "would_orders": int(self.would_orders),
            "orders_submitted": int(self.orders_submitted),
            "orders_filled": int(self.orders_filled),
            "safety_events": int(self.safety_events),
            "api_failures": int(self.api_failures),
            "daily_summaries": [dict(d) for d in self.daily_summaries],
            "hourly_snapshots": [dict(h) for h in self.hourly_snapshots],
            "per_trade_records": [
                dict(t) for t in self.per_trade_records
            ],
            "session_summary": dict(self.session_summary),
            "warnings": list(self.warnings),
            "notes": self.notes,
            # FASE 30.2 - execucao real multi-ordem (aditivos)
            "execution_mode": self.execution_mode,
            "real_orders_enabled": bool(self.real_orders_enabled),
            "max_real_orders": (
                int(self.max_real_orders)
                if self.max_real_orders is not None else None
            ),
            "trades_completed": int(self.trades_completed),
            "trades_open": int(self.trades_open),
            "trades_closed_by_tp": int(self.trades_closed_by_tp),
            "trades_closed_by_sl": int(self.trades_closed_by_sl),
            "trades_closed_by_reduce_only": int(
                self.trades_closed_by_reduce_only
            ),
            "trades_manual_review": int(self.trades_manual_review),
            "total_realized_pnl": self.total_realized_pnl,
            "final_open_positions_count": int(
                self.final_open_positions_count
            ),
            "final_open_orders_count": int(
                self.final_open_orders_count
            ),
            "final_conditional_orders_count": int(
                self.final_conditional_orders_count
            ),
            "final_flat_check_passed": self.final_flat_check_passed,
            "multi_order_gate_enabled": bool(
                self.multi_order_gate_enabled
            ),
            "profile_multi_order_allowed": bool(
                self.profile_multi_order_allowed
            ),
            "scale_in_allowed": False,
            "auto_reversal_allowed": False,
        }


__all__ = ["EnduranceEndedReason", "DemoEnduranceOutcome"]
