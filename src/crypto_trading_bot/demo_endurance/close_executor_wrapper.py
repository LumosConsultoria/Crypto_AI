"""
CloseExecutorWrapper (FASE 29)
====================================
Thin wrapper sobre BybitDemoExecutor.submit_reduce_only_close.
Compoe defesa em profundidade: triple checks ANTES de chamar o
executor real.

⚠️  NAO chama rede. Apenas delega ao executor injetado.
⚠️  Reaproveita a sanitizacao + ModeGuard ja em
    BybitDemoExecutor.submit_reduce_only_close.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class CloseExecutionResult:
    """Resultado da chamada wrapper."""
    success: bool
    operation: str  # "reduce_only_close"
    reason: str
    order_id: Optional[str] = None
    manual_review_required: bool = False
    safety_halt_recommended: bool = False
    snapshot: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "success": bool(self.success),
            "operation": self.operation,
            "reason": self.reason,
            "order_id": self.order_id,
            "manual_review_required":
                bool(self.manual_review_required),
            "safety_halt_recommended":
                bool(self.safety_halt_recommended),
            "snapshot": dict(self.snapshot) if self.snapshot else None,
        }


def _opposite_side(side: str) -> str:
    s = str(side).lower().strip()
    if s == "buy":
        return "sell"
    if s == "sell":
        return "buy"
    raise ValueError(f"side invalido: {side!r}")


class CloseExecutorWrapper:
    """Wrapper FASE 29 sobre BybitDemoExecutor.submit_reduce_only_close.

    Args:
        executor: BybitDemoExecutor (FASE 22) OU mock com
                  submit_reduce_only_close compativel.
    """

    def __init__(self, *, executor: Any) -> None:
        if executor is None:
            raise ValueError("executor obrigatorio")
        if not hasattr(executor, "submit_reduce_only_close"):
            raise TypeError(
                "executor deve ter submit_reduce_only_close"
            )
        self._executor = executor

    def close_position(
        self,
        *,
        symbol: str,
        position_side: str,
        position_qty: float,
        dry_run: bool = True,
        confirm_demo_execution: bool = False,
    ) -> CloseExecutionResult:
        """Chama submit_reduce_only_close com defesas.

        Validacoes locais ANTES de delegar:
            - position_qty > 0
            - position_side in {buy, sell}
            - dry_run + confirm coerentes
        """
        if position_qty <= 0:
            return CloseExecutionResult(
                success=False, operation="reduce_only_close",
                reason="position_qty <= 0",
                manual_review_required=True,
            )
        try:
            opp = _opposite_side(position_side)
        except ValueError as e:
            return CloseExecutionResult(
                success=False, operation="reduce_only_close",
                reason=str(e)[:160], manual_review_required=True,
            )
        if not dry_run and not confirm_demo_execution:
            return CloseExecutionResult(
                success=False, operation="reduce_only_close",
                reason=(
                    "dry_run=False exige confirm_demo_execution=True"
                ),
                manual_review_required=True,
            )

        try:
            result = self._executor.submit_reduce_only_close(
                symbol=symbol,
                side=opp,
                qty=float(position_qty),
                dry_run=bool(dry_run),
                confirm_demo_execution=bool(confirm_demo_execution),
            )
        except Exception as e:  # noqa: BLE001
            return CloseExecutionResult(
                success=False, operation="reduce_only_close",
                reason=(
                    f"executor raised {type(e).__name__}: "
                    f"{str(e)[:120]}"
                ),
                manual_review_required=True,
                safety_halt_recommended=True,
            )

        # Result eh DemoExecutionResult-like.
        success = bool(getattr(result, "success", False))
        reason = str(getattr(result, "reason", ""))[:200]
        manual_review = bool(
            getattr(result, "manual_review_required", False)
        )
        safety_halt = bool(
            getattr(result, "safety_halt_recommended", False)
        )
        order_id = None
        snapshot = None
        # extrair order_id se houver trade interno
        try:
            to_dict = getattr(result, "to_dict", None)
            if callable(to_dict):
                snapshot = to_dict()
        except Exception:  # noqa: BLE001
            snapshot = None

        return CloseExecutionResult(
            success=success, operation="reduce_only_close",
            reason=reason,
            order_id=order_id,
            manual_review_required=manual_review,
            safety_halt_recommended=safety_halt,
            snapshot=snapshot,
        )


__all__ = ["CloseExecutionResult", "CloseExecutorWrapper"]
