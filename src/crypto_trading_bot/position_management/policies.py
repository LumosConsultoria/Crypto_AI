"""
Position Management Policies (FASE 36 Bloco E2)
================================================
Scale-in (B), reducao parcial (C), reversao controlada (D) e
multi-ordem (A/E) como CAPACIDADE ARQUITETURAL — TUDO default OFF.

⚠️  ORDEM DE TRAVAS (todas obrigatorias; nenhuma implica outra):
    1. gate ENV proprio;
    2. permissao do PERFIL;
    3. LIMITES do operador (V5-V8) — ausentes => blocked_missing_limits;
    4. confirmacao humana;
    5. risco agregado REVALIDADO via RiskEngine.validate_signal
       (soberania preservada: a policy NUNCA aprova o que o
       RiskEngine reprovaria).
⚠️  Nunca soma posicao sem recalculo de risco total.
⚠️  Reducao parcial: SEMPRE reduceOnly; nunca inverte.
⚠️  Reversao nesta fase: SEMPRE manual_review (nunca automatica) e
    somente apos flat confirmado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from crypto_trading_bot.position_management.gates_position_mgmt import (
    partial_reduce_gate_enabled,
    reversal_gate_enabled,
    scale_in_gate_enabled,
)
from crypto_trading_bot.position_management.position_state import (
    AggregatedRiskSnapshot,
    PositionState,
)


_SL_POLICIES = ("never", "only_in_favor", "recalculate")


@dataclass(frozen=True)
class ScaleInLimits:
    """Limites V5-V6 — SEMPRE informados pelo operador.

    NENHUM default: campo None => blocked_missing_limits. Valores em
    testes sao FIXTURES explicitamente marcadas.
    """
    max_scale_ins_per_position: Optional[int] = None
    max_added_risk_pct: Optional[float] = None
    max_aggregated_risk_pct: Optional[float] = None
    min_entry_distance_pct: Optional[float] = None
    min_time_between_scale_ins_minutes: Optional[int] = None
    sl_move_policy: Optional[str] = None   # never|only_in_favor|recalculate

    def missing_fields(self) -> Tuple[str, ...]:
        missing = [
            name for name in (
                "max_scale_ins_per_position", "max_added_risk_pct",
                "max_aggregated_risk_pct", "min_entry_distance_pct",
                "min_time_between_scale_ins_minutes",
                "sl_move_policy",
            ) if getattr(self, name) is None
        ]
        if self.sl_move_policy is not None and \
                self.sl_move_policy not in _SL_POLICIES:
            missing.append("sl_move_policy(invalido)")
        return tuple(missing)


@dataclass(frozen=True)
class ScaleInProposal:
    """Proposta de aumento de posicao (mesmo lado, nunca reversao)."""
    symbol: str
    side: str
    add_qty: float
    add_price: float
    proposed_new_sl: Optional[float] = None
    signal_independent: bool = False
    minutes_since_last_entry: Optional[float] = None
    now: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.add_qty <= 0 or self.add_price <= 0:
            raise ValueError("add_qty/add_price devem ser > 0")
        object.__setattr__(
            self, "side", str(self.side).strip().lower(),
        )


@dataclass(frozen=True)
class ScaleInDecision:
    approved: bool
    blockers: Tuple[str, ...]
    aggregated_risk: Optional[AggregatedRiskSnapshot] = None
    effective_sl: Optional[float] = None
    requires_manual_confirmation: bool = True

    def to_dict(self) -> dict:
        return {
            "approved": bool(self.approved),
            "blockers": list(self.blockers),
            "aggregated_risk": (
                self.aggregated_risk.to_dict()
                if self.aggregated_risk else None
            ),
            "effective_sl": self.effective_sl,
            "requires_manual_confirmation": True,
        }


def evaluate_scale_in(
    *,
    profile: Any,
    limits: ScaleInLimits,
    position: PositionState,
    proposal: ScaleInProposal,
    capital_usd: float,
    risk_engine: Any,
    operator_confirmed: bool,
) -> ScaleInDecision:
    """Avalia scale-in com TODAS as travas. Nunca envia ordem."""
    blockers = []

    # 1. Gate ENV proprio.
    if not scale_in_gate_enabled():
        blockers.append(
            "gate DEMO_ALLOW_SCALE_IN_ENABLED=true ausente"
        )
    # 2. Perfil.
    if not getattr(profile, "allow_scale_in", False):
        blockers.append("profile.allow_scale_in=False")
    # 3. Limites do operador (V5-V6) — sem inventar nada.
    missing = limits.missing_fields()
    if missing:
        blockers.append(
            "blocked_missing_limits: " + ", ".join(missing)
        )
    # 4. Confirmacao humana.
    if not operator_confirmed:
        blockers.append("confirmacao humana ausente")

    # Estrutura: mesmo lado, nunca reversao via scale-in.
    if proposal.side != position.side:
        blockers.append(
            f"lado da proposta ({proposal.side}) difere da posicao "
            f"({position.side}) — reversao via scale-in proibida"
        )
    if proposal.symbol != position.symbol:
        blockers.append("symbol divergente")
    if not proposal.signal_independent:
        blockers.append(
            "sinal nao-independente (repeticao do mesmo setup)"
        )

    if blockers:
        return ScaleInDecision(
            approved=False, blockers=tuple(blockers),
        )

    # Limites quantitativos (apos travas estruturais).
    if position.scale_in_count + 1 > limits.max_scale_ins_per_position:
        blockers.append(
            f"max_scale_ins_per_position "
            f"({limits.max_scale_ins_per_position}) excedido"
        )
    distance_pct = abs(
        proposal.add_price - position.last_entry.price,
    ) / position.last_entry.price * 100.0
    if distance_pct < limits.min_entry_distance_pct:
        blockers.append(
            f"distancia {distance_pct:.4f}% < minima "
            f"{limits.min_entry_distance_pct}%"
        )
    if proposal.minutes_since_last_entry is None or \
            proposal.minutes_since_last_entry < \
            limits.min_time_between_scale_ins_minutes:
        blockers.append(
            "tempo desde a ultima entrada insuficiente/desconhecido"
        )

    # Politica de SL (V6).
    effective_sl = position.stop_loss
    if proposal.proposed_new_sl is not None:
        if limits.sl_move_policy == "never":
            blockers.append(
                "mover SL proibido (sl_move_policy=never)"
            )
        elif limits.sl_move_policy == "only_in_favor":
            in_favor = (
                proposal.proposed_new_sl > position.stop_loss
                if position.side == "buy"
                else proposal.proposed_new_sl < position.stop_loss
            )
            if not in_favor:
                blockers.append(
                    "novo SL nao e a favor (only_in_favor)"
                )
            else:
                effective_sl = proposal.proposed_new_sl
        else:  # recalculate
            effective_sl = proposal.proposed_new_sl

    # Risco agregado (NUNCA soma posicao sem recalculo).
    current_risk = abs(
        position.avg_entry_price - effective_sl,
    ) * position.qty
    added_risk = abs(proposal.add_price - effective_sl) * \
        proposal.add_qty
    snapshot = AggregatedRiskSnapshot(
        capital_usd=capital_usd,
        current_risk_usd=current_risk,
        added_risk_usd=added_risk,
        sl_used_for_calc=effective_sl,
    )
    if snapshot.added_risk_pct > limits.max_added_risk_pct:
        blockers.append(
            f"risco adicional {snapshot.added_risk_pct:.4f}% > "
            f"max {limits.max_added_risk_pct}%"
        )
    if snapshot.total_risk_pct > limits.max_aggregated_risk_pct:
        blockers.append(
            f"risco agregado {snapshot.total_risk_pct:.4f}% > "
            f"max {limits.max_aggregated_risk_pct}%"
        )

    # 5. SOBERANIA: revalida o INCREMENTO no RiskEngine real.
    if not blockers:
        try:
            from crypto_trading_bot.risk.risk_engine import (
                OrderSide, TradingSignal,
            )
            incremental = TradingSignal(
                symbol=proposal.symbol,
                side=(
                    OrderSide.BUY if proposal.side == "buy"
                    else OrderSide.SELL
                ),
                entry_price=float(proposal.add_price),
                stop_loss_price=float(effective_sl),
                take_profit_price=position.take_profit,
                position_size_usd=float(
                    proposal.add_price * proposal.add_qty,
                ),
                leverage=1.0,
                strategy_name="scale_in_incremental",
            )
            result = risk_engine.validate_signal(incremental)
            if not getattr(result, "approved", False):
                blockers.append(
                    "RiskEngine reprovou o incremento: "
                    + str(getattr(result, "reason", ""))[:120]
                )
        except Exception as e:  # noqa: BLE001
            blockers.append(
                f"falha na revalidacao de risco: {type(e).__name__}"
            )

    return ScaleInDecision(
        approved=not blockers,
        blockers=tuple(blockers),
        aggregated_risk=snapshot,
        effective_sl=effective_sl,
    )


# ---------------------------------------------------------------------------
# C. Reducao parcial
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PartialReduceDecision:
    approved: bool
    blockers: Tuple[str, ...]
    reduce_qty: float = 0.0
    remaining_qty: float = 0.0
    reduce_only: bool = True       # SEMPRE True
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "approved": bool(self.approved),
            "blockers": list(self.blockers),
            "reduce_qty": float(self.reduce_qty),
            "remaining_qty": float(self.remaining_qty),
            "reduce_only": True,
            "reason": self.reason,
        }


def evaluate_partial_reduce(
    *,
    profile: Any,
    max_reduce_pct: Optional[float],
    position: PositionState,
    reduce_qty: float,
    operator_confirmed: bool,
    reason: str = "",
) -> PartialReduceDecision:
    """Reducao parcial: reduceOnly SEMPRE; nunca inverte posicao."""
    blockers = []
    if not partial_reduce_gate_enabled():
        blockers.append(
            "gate DEMO_ALLOW_PARTIAL_REDUCE_ENABLED=true ausente"
        )
    if not getattr(profile, "allow_partial_reduce", False):
        blockers.append("profile.allow_partial_reduce=False")
    if max_reduce_pct is None:
        blockers.append(
            "blocked_missing_limits: partial_reduce_max_pct (V7)"
        )
    if not operator_confirmed:
        blockers.append("confirmacao humana ausente")
    if reduce_qty <= 0:
        blockers.append("reduce_qty deve ser > 0")
    elif reduce_qty >= position.qty:
        blockers.append(
            "reduce_qty >= posicao (reducao TOTAL/inversao proibida "
            "aqui; close integral usa o caminho reduceOnly close)"
        )
    elif max_reduce_pct is not None:
        pct = (reduce_qty / position.qty) * 100.0
        if pct > max_reduce_pct:
            blockers.append(
                f"reducao {pct:.2f}% > max {max_reduce_pct}%"
            )
    return PartialReduceDecision(
        approved=not blockers,
        blockers=tuple(blockers),
        reduce_qty=reduce_qty if not blockers else 0.0,
        remaining_qty=(
            position.qty - reduce_qty if not blockers
            else position.qty
        ),
        reason=reason[:160],
    )


# ---------------------------------------------------------------------------
# D. Reversao controlada (NESTA FASE: sempre manual review)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReversalDecision:
    approved_for_auto_execution: bool   # SEMPRE False nesta fase
    manual_review_required: bool
    blockers: Tuple[str, ...]
    reason: str = ""

    def __post_init__(self) -> None:
        if self.approved_for_auto_execution:
            raise ValueError(
                "reversao automatica e PROIBIDA nesta fase "
                "(V8: manual review only)"
            )

    def to_dict(self) -> dict:
        return {
            "approved_for_auto_execution": False,
            "manual_review_required": bool(
                self.manual_review_required
            ),
            "blockers": list(self.blockers),
            "reason": self.reason,
        }


def evaluate_reversal(
    *,
    profile: Any,
    position_flat_confirmed: bool,
    operator_confirmed: bool,
    reason: str = "",
) -> ReversalDecision:
    """Reversao: NUNCA automatica. Melhor caso => manual review."""
    blockers = []
    if not reversal_gate_enabled():
        blockers.append(
            "gate DEMO_ALLOW_REVERSAL_ENABLED=true ausente"
        )
    allow = getattr(profile, "allow_reversal", "blocked")
    if allow == "blocked":
        blockers.append("profile.allow_reversal=blocked")
    if not position_flat_confirmed:
        blockers.append(
            "posicao atual NAO esta flat confirmada — fechar e "
            "confirmar flat ANTES de considerar lado oposto"
        )
    if not operator_confirmed:
        blockers.append("confirmacao humana ausente")
    return ReversalDecision(
        approved_for_auto_execution=False,
        manual_review_required=not blockers,
        blockers=tuple(blockers),
        reason=reason[:160],
    )


# ---------------------------------------------------------------------------
# A/E. Politica multi-ordem (sequencial) consolidada
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MultiOrderPolicy:
    """Regras de aceitacao de NOVA entrada (sequencial estrito)."""

    max_open_positions: int = 1

    def can_enter_new(
        self, *, open_positions_count: int,
        open_orders_count: int, conditional_orders_count: int,
    ) -> Tuple[bool, str]:
        if open_positions_count >= self.max_open_positions:
            return False, (
                f"posicao aberta ({open_positions_count}) — "
                "sequencial estrito: aguardar flat"
            )
        if open_orders_count > 0:
            return False, "open orders pendentes"
        if conditional_orders_count > 0:
            return False, "conditional orders pendentes"
        return True, ""


__all__ = [
    "MultiOrderPolicy",
    "PartialReduceDecision",
    "ReversalDecision",
    "ScaleInDecision",
    "ScaleInLimits",
    "ScaleInProposal",
    "evaluate_partial_reduce",
    "evaluate_reversal",
    "evaluate_scale_in",
]
