"""
DecisionTrace - explicabilidade por decisao (FASE 36 Bloco A)
==============================================================
Registro AUDITAVEL e LEGIVEL de CADA decisao do bot: entrada, nao
entrada (skip), bloqueio, manual review, saida, hold, candidato a
scale-in/reducao/reversao.

⚠️  100% offline/puro. ZERO rede. ZERO secret (campos tecnicos
    apenas; sanitizacao adicional na telemetria).
⚠️  O trace NUNCA decide nada — apenas registra o que cada camada
    (estrategia, RiskEngine, perfil, gates, IA, MI) decidiu e por que.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


class FinalDecision(str, Enum):
    """Decisao final de um ciclo/evento."""
    ENTER = "enter"
    SKIP = "skip"
    BLOCK = "block"
    REVIEW = "review"
    CLOSE = "close"
    HOLD = "hold"
    SCALE_IN_CANDIDATE = "scale_in_candidate"
    REDUCE = "reduce"
    REVERSE_CANDIDATE = "reverse_candidate"


@dataclass(frozen=True)
class DecisionTraceEntry:
    """UMA decisao auditavel. Frozen, JSON-serializavel.

    Campos opcionais default None/() — estrategias/camadas que nao
    fornecem um dado deixam o campo vazio (nunca inventado).
    """

    # Identificacao
    trace_id: str
    cycle_idx: int
    timestamp: datetime
    session_id: str = ""

    # Estrategia / contexto de mercado
    strategy_id: Optional[str] = None
    strategy_name: Optional[str] = None
    strategy_version: Optional[str] = None
    profile_name: Optional[str] = None
    provider_id: Optional[str] = None
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    candle_price: Optional[float] = None
    indicators: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    signal_side: Optional[str] = None
    signal_confidence: Optional[float] = None
    entry_reason_technical: Optional[str] = None
    rejection_reason_technical: Optional[str] = None

    # RiskEngine (soberano)
    risk_decision: Optional[str] = None        # approved | rejected
    risk_reason: Optional[str] = None
    estimated_risk_usd: Optional[float] = None
    estimated_risk_pct: Optional[float] = None
    exposure_before: Optional[float] = None
    exposure_after: Optional[float] = None

    # Plano de trade
    planned_sl: Optional[float] = None
    planned_tp: Optional[float] = None
    risk_reward: Optional[float] = None
    qty: Optional[float] = None
    notional_usd: Optional[float] = None
    leverage: Optional[float] = None

    # Estado da conta ANTES da decisao
    position_before: Optional[Mapping[str, Any]] = None
    open_orders_before: Optional[int] = None
    conditional_orders_before: Optional[int] = None

    # IA (consultiva)
    ai_used: bool = False
    ai_not_used_reason: Optional[str] = None
    ai_status: Optional[str] = None          # neutral|caution|veto|manual_review
    ai_reason: Optional[str] = None

    # Market Intelligence / prediction (read-only)
    market_intelligence_used: bool = False
    mi_not_used_reason: Optional[str] = None
    mi_sources_used: Tuple[str, ...] = field(default_factory=tuple)
    mi_sources_stale: Tuple[str, ...] = field(default_factory=tuple)
    mi_sources_unavailable: Tuple[str, ...] = field(
        default_factory=tuple,
    )
    mi_risk_flags: Tuple[str, ...] = field(default_factory=tuple)
    news_used: bool = False
    funding_used: bool = False
    open_interest_used: bool = False
    orderbook_used: bool = False
    liquidity_correlation_used: bool = False
    context_inconclusive: bool = False

    # Gates
    gates_approved: Tuple[str, ...] = field(default_factory=tuple)
    gates_blocked: Tuple[str, ...] = field(default_factory=tuple)

    # Decisao final
    final_decision: FinalDecision = FinalDecision.HOLD
    final_reason: str = ""

    # Pos-encerramento (quando aplicavel)
    realized_pnl: Optional[float] = None
    trade_idx: Optional[int] = None

    # FASE 36 pos-demo 3: diagnostico de alinhamento SL x piso de risco.
    planned_sl_pct: Optional[float] = None
    min_sl_pct_required: Optional[float] = None
    sl_gap_to_min_pct: Optional[float] = None
    risk_rejection_category: Optional[str] = None
    recommended_action: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.final_decision, FinalDecision):
            raise TypeError(
                "final_decision deve ser FinalDecision"
            )
        if self.timestamp.tzinfo is None:
            object.__setattr__(
                self, "timestamp",
                self.timestamp.replace(tzinfo=timezone.utc),
            )
        if not isinstance(self.indicators, MappingProxyType):
            object.__setattr__(
                self, "indicators",
                MappingProxyType(dict(self.indicators)),
            )
        if self.position_before is not None and not isinstance(
            self.position_before, MappingProxyType,
        ):
            object.__setattr__(
                self, "position_before",
                MappingProxyType(dict(self.position_before)),
            )
        for tup_field in (
            "mi_sources_used", "mi_sources_stale",
            "mi_sources_unavailable", "mi_risk_flags",
            "gates_approved", "gates_blocked",
        ):
            val = getattr(self, tup_field)
            if not isinstance(val, tuple):
                object.__setattr__(self, tup_field, tuple(val))

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "cycle_idx": int(self.cycle_idx),
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "profile_name": self.profile_name,
            "provider_id": self.provider_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "candle_price": self.candle_price,
            "indicators": dict(self.indicators),
            "signal_side": self.signal_side,
            "signal_confidence": self.signal_confidence,
            "entry_reason_technical": self.entry_reason_technical,
            "rejection_reason_technical":
                self.rejection_reason_technical,
            "risk_decision": self.risk_decision,
            "risk_reason": self.risk_reason,
            "estimated_risk_usd": self.estimated_risk_usd,
            "estimated_risk_pct": self.estimated_risk_pct,
            "exposure_before": self.exposure_before,
            "exposure_after": self.exposure_after,
            "planned_sl": self.planned_sl,
            "planned_tp": self.planned_tp,
            "risk_reward": self.risk_reward,
            "qty": self.qty,
            "notional_usd": self.notional_usd,
            "leverage": self.leverage,
            "position_before": (
                dict(self.position_before)
                if self.position_before is not None else None
            ),
            "open_orders_before": self.open_orders_before,
            "conditional_orders_before":
                self.conditional_orders_before,
            "ai_used": bool(self.ai_used),
            "ai_not_used_reason": self.ai_not_used_reason,
            "ai_status": self.ai_status,
            "ai_reason": self.ai_reason,
            "market_intelligence_used": bool(
                self.market_intelligence_used
            ),
            "mi_not_used_reason": self.mi_not_used_reason,
            "mi_sources_used": list(self.mi_sources_used),
            "mi_sources_stale": list(self.mi_sources_stale),
            "mi_sources_unavailable": list(
                self.mi_sources_unavailable
            ),
            "mi_risk_flags": list(self.mi_risk_flags),
            "news_used": bool(self.news_used),
            "funding_used": bool(self.funding_used),
            "open_interest_used": bool(self.open_interest_used),
            "orderbook_used": bool(self.orderbook_used),
            "liquidity_correlation_used": bool(
                self.liquidity_correlation_used
            ),
            "context_inconclusive": bool(self.context_inconclusive),
            "gates_approved": list(self.gates_approved),
            "gates_blocked": list(self.gates_blocked),
            "final_decision": self.final_decision.value,
            "final_reason": self.final_reason[:300],
            "realized_pnl": self.realized_pnl,
            "trade_idx": self.trade_idx,
            "planned_sl_pct": self.planned_sl_pct,
            "min_sl_pct_required": self.min_sl_pct_required,
            "sl_gap_to_min_pct": self.sl_gap_to_min_pct,
            "risk_rejection_category": self.risk_rejection_category,
            "recommended_action": self.recommended_action,
        }


__all__ = ["DecisionTraceEntry", "FinalDecision"]
