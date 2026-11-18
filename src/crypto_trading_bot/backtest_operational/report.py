"""
Backtest Operational Report (FASE 37 Parte F/I)
===============================================
Relatorio do backtest operacional. Distingue claramente, por contexto
externo (IA/Polymarket/MI/funding/OI/orderbook/news):

    enabled            -> toggle estava ligado
    context_available  -> havia dado REAL conhecido no instante
    decision_impact    -> o dado efetivamente influenciou a decisao

Tambem agrega o resultado do motor de backtest (validado) e a lista de
Decision Traces. NUNCA mistura "ligado" com "teve efeito".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ContextAvailabilitySummary:
    """Agregado por kind de contexto ao longo do backtest."""
    kind: str
    enabled: bool
    decision_points: int = 0
    context_available_count: int = 0
    decision_impact_count: int = 0
    unavailable_count: int = 0
    stale_count: int = 0
    blocked_count: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "enabled": self.enabled,
            "decision_points": self.decision_points,
            "context_available_count": self.context_available_count,
            "decision_impact_count": self.decision_impact_count,
            "unavailable_count": self.unavailable_count,
            "stale_count": self.stale_count,
            "blocked_count": self.blocked_count,
        }


@dataclass(frozen=True)
class BacktestOperationalReport:
    """Relatorio consolidado do backtest operacional (paridade demo)."""

    schema: str = "backtest_operational_report_v1"
    # --- Identificacao / dataset ---
    strategy: str = ""
    profile: Optional[str] = None
    symbol: str = ""
    timeframe: str = ""
    rows: int = 0
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    source_type: str = "unknown"          # real | synthetic_fake | csv
    dataset_checksum: Optional[str] = None

    # --- Contexto de execucao (todos os toggles) ---
    execution_context: Mapping[str, Any] = field(default_factory=dict)
    real_execution_allowed: bool = False  # SEMPRE False

    # --- Resultado do motor (validado) ---
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    total_pnl_usd: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    profit_factor: Optional[float] = None
    expectancy_usd: float = 0.0
    risk_blocked_count: int = 0
    # FASE 37.3: bloqueios agregados por categoria (RiskEngine).
    blocked_reasons_summary: Mapping[str, int] = field(default_factory=dict)
    final_capital: float = 0.0
    total_fees_usd: float = 0.0
    total_slippage_usd: float = 0.0

    # --- Contexto externo: enabled vs available vs impact ---
    context_availability: Tuple[ContextAvailabilitySummary, ...] = field(
        default_factory=tuple)

    # --- Decision traces (Parte H) ---
    decision_traces: Tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple)
    decision_trace_count: int = 0

    # --- Readiness (consultivo) ---
    readiness_status: Optional[str] = None

    # --- Estado de execucao (FASE 37.1) ---
    partial: bool = False          # relatorio parcial (ex.: interrompido)
    interrupted: bool = False      # KeyboardInterrupt durante o backtest
    candles_processed: Optional[int] = None  # candles processados ate parar
    elapsed_seconds: Optional[float] = None

    # --- Avisos / notas ---
    synthetic_data_warning: bool = False
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "strategy": self.strategy,
            "profile": self.profile,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "rows": self.rows,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "source_type": self.source_type,
            "dataset_checksum": self.dataset_checksum,
            "execution_context": dict(self.execution_context),
            "real_execution_allowed": self.real_execution_allowed,
            "results": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "win_rate_pct": self.win_rate_pct,
                "total_pnl_usd": self.total_pnl_usd,
                "max_drawdown_pct": self.max_drawdown_pct,
                "avg_win_usd": self.avg_win_usd,
                "avg_loss_usd": self.avg_loss_usd,
                "profit_factor": self.profit_factor,
                "expectancy_usd": self.expectancy_usd,
                "risk_blocked_count": self.risk_blocked_count,
                "blocked_reasons_summary": dict(self.blocked_reasons_summary),
                "final_capital": self.final_capital,
                "total_fees_usd": self.total_fees_usd,
                "total_slippage_usd": self.total_slippage_usd,
            },
            "context_availability": [
                c.to_dict() for c in self.context_availability
            ],
            "decision_trace_count": self.decision_trace_count,
            "decision_traces": [dict(t) for t in self.decision_traces],
            "readiness_status": self.readiness_status,
            "partial": self.partial,
            "interrupted": self.interrupted,
            "candles_processed": self.candles_processed,
            "elapsed_seconds": self.elapsed_seconds,
            "synthetic_data_warning": self.synthetic_data_warning,
            "warnings": list(self.warnings),
            "notes": list(self.notes),
        }


__all__ = [
    "BacktestOperationalReport",
    "ContextAvailabilitySummary",
]
