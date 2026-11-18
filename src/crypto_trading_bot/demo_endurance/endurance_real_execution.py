"""
Endurance Real Execution (FASE 30.2) - ciclo de trade real sequencial
======================================================================
Executa UM trade real demo completo por vez:
    abrir -> SL/TP server-side -> monitorar -> fechar -> flat-check ->
    P&L -> trade_completed (so entao o runner pode considerar nova
    entrada).

⚠️  SEQUENCIAL ESTRITO: sem scale-in, sem piramidacao, sem reversao
    automatica, nunca 2a posicao com a 1a aberta.
⚠️  TUDO injetavel: testes offline usam fakes (zero rede, zero ordem
    real). Producao usa build_real_trade_lifecycle (wiring FASE 22/29).
⚠️  RiskEngine ja aprovou ANTES de execute_trade ser chamado (runner).
⚠️  SL/TP nao confirmado -> manual_review (regra 16). Flat nao
    confirmado -> manual_review (regra 17). P&L nao resolvido ->
    unresolved/manual_review (regra 18).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, Optional


class MultiOrderExecutionState(str, Enum):
    """Estados do ciclo multi-ordem sequencial (FASE 30.2)."""
    IDLE = "idle"
    WAITING_SIGNAL = "waiting_signal"
    SIGNAL_APPROVED = "signal_approved"
    ORDER_SUBMITTING = "order_submitting"
    ORDER_SUBMITTED = "order_submitted"
    SL_TP_CONFIRMING = "sl_tp_confirming"
    POSITION_MONITORING = "position_monitoring"
    WAITING_EXIT = "waiting_exit"
    EXIT_DETECTED = "exit_detected"
    FLAT_CHECKING = "flat_checking"
    PNL_RESOLVING = "pnl_resolving"
    TRADE_COMPLETED = "trade_completed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SAFETY_HALT = "safety_halt"
    SESSION_COMPLETED = "session_completed"


# Estados que ACEITAM nova entrada. position_monitoring/waiting_exit/
# flat_checking/pnl_resolving NUNCA aceitam (regras de transicao).
_ENTRY_ALLOWED_STATES = frozenset({
    MultiOrderExecutionState.IDLE,
    MultiOrderExecutionState.WAITING_SIGNAL,
    MultiOrderExecutionState.TRADE_COMPLETED,
})


def can_accept_new_entry(state: MultiOrderExecutionState) -> bool:
    """True apenas em idle/waiting_signal/trade_completed."""
    return state in _ENTRY_ALLOWED_STATES


_VALID_CLOSE_REASONS = ("tp", "sl", "reduce_only", "manual", "unknown")
_VALID_TRADE_STATUS = (
    "completed", "manual_review_required", "unresolved",
)


@dataclass
class RealTradeRecord:
    """Registro auditavel de UM trade real demo (per-trade record)."""

    trade_idx: int
    side: str
    symbol: str
    entry_price: float = 0.0
    qty: float = 0.0
    notional: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: Optional[float] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    close_reason: str = "unknown"
    realized_pnl: Optional[float] = None
    fees: Optional[float] = None
    flat_check_after_trade: Optional[bool] = None
    residual_orders_after_trade: int = 0
    status: str = "unresolved"
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        if self.close_reason not in _VALID_CLOSE_REASONS:
            self.close_reason = "unknown"
        if self.status not in _VALID_TRADE_STATUS:
            self.status = "unresolved"
        return {
            "trade_idx": int(self.trade_idx),
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "side": self.side,
            "symbol": self.symbol,
            "entry_price": float(self.entry_price),
            "qty": float(self.qty),
            "notional": float(self.notional),
            "stop_loss_price": float(self.stop_loss_price),
            "take_profit_price": self.take_profit_price,
            "sl_order_id": self.sl_order_id,
            "tp_order_id": self.tp_order_id,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "realized_pnl": self.realized_pnl,
            "fees": self.fees,
            "flat_check_after_trade": self.flat_check_after_trade,
            "residual_orders_after_trade": int(
                self.residual_orders_after_trade
            ),
            "status": self.status,
            "notes": self.notes[:200],
        }


class RealTradeLifecycle:
    """Executa UM trade real demo completo. Tudo injetavel.

    Args (todos callables/objetos injetaveis; testes usam fakes):
        gate_callable(trading_signal, snapshot) -> gate outcome
            (FASE 22 execute_demo_session_gated com dry_run=False em
            producao). Deve expor: orders_submitted/orders_filled-like
            success, sl/tp confirmation via post_check.
        sl_tp_confirmed_fn(gate_outcome) -> Optional[bool]
            True=confirmado; False=NAO confirmado (manual_review);
            None=indeterminado (manual_review).
        position_poll_fn(poll_idx) -> dict
            {"open_position_qty": float, "mark_price": float|None,
             "positions": [...], "open_orders": [...],
             "conditional_orders": [...], "error": str|None}
        max_monitor_polls: orcamento de polls por trade.
        poll_sleep_fn(seconds): espera entre polls (real em producao;
            fake em teste).
        poll_interval_seconds: intervalo entre polls.
        reduce_only_close_fn(side, qty) -> dict
            {"success": bool, "reason": str} - fallback gated;
            None desabilita fallback (-> manual_review no budget).
        flat_check_fn(snapshot_dict) -> dict
            {"is_flat": bool, "open_orders_count": int, ...}
        pnl_fetch_fn(record, exit_price, exit_reason) ->
            Optional[float] realized pnl.
        telemetry_emit(event_type, **snapshot): fail-safe.
        clock() -> datetime tz-aware.
    """

    def __init__(
        self,
        *,
        gate_callable: Callable[..., Any],
        sl_tp_confirmed_fn: Callable[[Any], Optional[bool]],
        position_poll_fn: Callable[[int], dict],
        flat_check_fn: Callable[[dict], dict],
        pnl_fetch_fn: Callable[..., Optional[float]],
        max_monitor_polls: int = 30,
        poll_interval_seconds: float = 60.0,
        poll_sleep_fn: Optional[Callable[[float], None]] = None,
        reduce_only_close_fn: Optional[Callable[..., dict]] = None,
        telemetry_emit: Optional[Callable[..., None]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not callable(gate_callable):
            raise TypeError("gate_callable deve ser callable")
        if max_monitor_polls < 1:
            raise ValueError(
                f"max_monitor_polls deve ser >= 1: {max_monitor_polls}"
            )
        self._gate = gate_callable
        self._sl_tp_confirmed = sl_tp_confirmed_fn
        self._poll = position_poll_fn
        self._flat_check = flat_check_fn
        self._pnl_fetch = pnl_fetch_fn
        self._max_polls = int(max_monitor_polls)
        self._poll_interval = float(poll_interval_seconds)
        self._poll_sleep = poll_sleep_fn or (lambda _s: None)
        self._reduce_only_close = reduce_only_close_fn
        self._emit_raw = telemetry_emit or (lambda *_a, **_k: None)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.state = MultiOrderExecutionState.IDLE

    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.isoformat()

    def _emit(self, event_type: str, **snapshot: Any) -> None:
        try:
            self._emit_raw(event_type, **snapshot)
        except Exception:  # noqa: BLE001
            pass

    def _transition(self, new_state: MultiOrderExecutionState,
                    trade_idx: int) -> None:
        old = self.state
        self.state = new_state
        self._emit(
            "state_transition", trade_idx=trade_idx,
            from_state=old.value, to_state=new_state.value,
        )

    # ------------------------------------------------------------------

    def execute_trade(
        self, *, trade_idx: int, trading_signal: Any,
        latest_snapshot: Any = None,
        deadline: Optional[datetime] = None,
    ) -> RealTradeRecord:
        """Executa o ciclo completo de UM trade. Nunca propaga excecao.

        Retorna RealTradeRecord com status:
            completed              ciclo limpo (saiu + flat + P&L)
            manual_review_required SL/TP, flat ou residual falhou
            unresolved             P&L nao resolvido (resto limpo)
        """
        record = RealTradeRecord(
            trade_idx=trade_idx,
            side=str(getattr(
                getattr(trading_signal, "side", None), "value",
                getattr(trading_signal, "side", "?"),
            )).lower(),
            symbol=str(getattr(trading_signal, "symbol", "?")),
            entry_price=float(getattr(
                trading_signal, "entry_price", 0.0,
            ) or 0.0),
            stop_loss_price=float(getattr(
                trading_signal, "stop_loss_price", 0.0,
            ) or 0.0),
            take_profit_price=getattr(
                trading_signal, "take_profit_price", None,
            ),
            notional=float(getattr(
                trading_signal, "position_size_usd", 0.0,
            ) or 0.0),
        )

        # --- 1. submit via gate FASE 22 (dry_run=False em producao) ---
        self._transition(
            MultiOrderExecutionState.ORDER_SUBMITTING, trade_idx,
        )
        try:
            gate_outcome = self._gate(
                trading_signal=trading_signal,
                latest_snapshot=latest_snapshot,
            )
        except Exception as e:  # noqa: BLE001
            record.status = "manual_review_required"
            record.notes = f"gate_exception:{type(e).__name__}"
            self._transition(
                MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                trade_idx,
            )
            return record

        submitted = bool(getattr(gate_outcome, "orders_submitted", 0)
                         or (isinstance(gate_outcome, dict)
                             and gate_outcome.get("orders_submitted")))
        if not submitted:
            record.status = "manual_review_required"
            record.notes = "gate did not submit order"
            self._transition(
                MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                trade_idx,
            )
            return record

        record.opened_at = self._now_iso()
        record.order_id = self._extract(gate_outcome, "order_id")
        record.client_order_id = self._extract(
            gate_outcome, "client_order_id",
        )
        record.qty = float(
            self._extract(gate_outcome, "qty") or record.qty or 0.0,
        )
        self._transition(
            MultiOrderExecutionState.ORDER_SUBMITTED, trade_idx,
        )
        self._emit(
            "order_submitted", trade_idx=trade_idx,
            side=record.side, symbol=record.symbol,
            entry_price=record.entry_price,
        )

        # --- 2. SL/TP server-side OBRIGATORIO (regra 16) ---
        self._transition(
            MultiOrderExecutionState.SL_TP_CONFIRMING, trade_idx,
        )
        try:
            sl_tp_ok = self._sl_tp_confirmed(gate_outcome)
        except Exception:  # noqa: BLE001
            sl_tp_ok = None
        if sl_tp_ok is not True:
            record.status = "manual_review_required"
            record.notes = "sl_tp_not_confirmed"
            self._transition(
                MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                trade_idx,
            )
            return record
        record.sl_order_id = self._extract(gate_outcome, "sl_order_id")
        record.tp_order_id = self._extract(gate_outcome, "tp_order_id")
        self._emit("sl_tp_confirmed", trade_idx=trade_idx)

        # --- 3. monitorar posicao ate sair (SL/TP server-side) ---
        self._transition(
            MultiOrderExecutionState.POSITION_MONITORING, trade_idx,
        )
        exit_price: Optional[float] = None
        exit_reason = "unknown"
        last_snap: dict = {}
        exited = False
        for poll_idx in range(self._max_polls):
            now = self._clock()
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            if deadline is not None and now >= deadline:
                break
            try:
                snap = dict(self._poll(poll_idx) or {})
            except Exception as e:  # noqa: BLE001
                snap = {"error": type(e).__name__}
            last_snap = snap
            self._emit(
                "position_snapshot", trade_idx=trade_idx,
                poll_idx=poll_idx,
                open_position_qty=snap.get("open_position_qty"),
                mark_price=snap.get("mark_price"),
                error=snap.get("error"),
            )
            if snap.get("error"):
                self._poll_sleep(self._poll_interval)
                continue
            qty_open = float(snap.get("open_position_qty", 0.0) or 0.0)
            if record.qty == 0.0 and qty_open > 0:
                record.qty = qty_open
            if qty_open == 0.0:
                exited = True
                exit_reason = "tp_sl_server_side"
                exit_price = snap.get("mark_price")
                self._transition(
                    MultiOrderExecutionState.EXIT_DETECTED, trade_idx,
                )
                self._emit(
                    "exit_detected", trade_idx=trade_idx,
                    exit_path="tp_sl_server_side",
                )
                break
            self._poll_sleep(self._poll_interval)

        # --- 3b. orcamento/deadline esgotado com posicao aberta ---
        if not exited:
            self._transition(
                MultiOrderExecutionState.WAITING_EXIT, trade_idx,
            )
            qty_open = float(
                last_snap.get("open_position_qty", 0.0) or 0.0,
            )
            closed = False
            if self._reduce_only_close is not None and qty_open > 0:
                try:
                    close_result = dict(self._reduce_only_close(
                        side=record.side, qty=qty_open,
                    ) or {})
                except Exception as e:  # noqa: BLE001
                    close_result = {
                        "success": False,
                        "reason": type(e).__name__,
                    }
                self._emit(
                    "exit_order_submitted", trade_idx=trade_idx,
                    success=bool(close_result.get("success")),
                    reason=str(close_result.get("reason", ""))[:120],
                )
                if close_result.get("success"):
                    closed = True
                    exit_reason = "reduce_only"
                    exit_price = last_snap.get("mark_price")
                    self._transition(
                        MultiOrderExecutionState.EXIT_DETECTED,
                        trade_idx,
                    )
            if not closed:
                # NUNCA clean com posicao aberta (regra 11/26).
                record.status = "manual_review_required"
                record.notes = "position_open_after_monitor_budget"
                self._transition(
                    MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                    trade_idx,
                )
                return record

        record.closed_at = self._now_iso()
        record.close_reason = self._derive_close_reason(
            exit_reason=exit_reason, exit_price=exit_price,
            record=record,
        )

        # --- 4. flat-check OBRIGATORIO pos-trade (regra 17/21) ---
        self._transition(
            MultiOrderExecutionState.FLAT_CHECKING, trade_idx,
        )
        try:
            flat = dict(self._flat_check(last_snap) or {})
        except Exception as e:  # noqa: BLE001
            flat = {"is_flat": None, "error": type(e).__name__}
        record.flat_check_after_trade = flat.get("is_flat")
        record.residual_orders_after_trade = int(
            flat.get("open_orders_count", 0) or 0,
        ) + int(flat.get("conditional_orders_count", 0) or 0)
        self._emit(
            "flat_check_done", trade_idx=trade_idx,
            is_flat=flat.get("is_flat"),
            open_orders_count=flat.get("open_orders_count"),
            conditional_orders_count=flat.get(
                "conditional_orders_count",
            ),
        )
        if flat.get("is_flat") is not True:
            record.status = "manual_review_required"
            record.notes = "flat_check_failed_after_trade"
            self._transition(
                MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                trade_idx,
            )
            return record

        # --- 5. P&L OBRIGATORIO por trade (regra 18/22) ---
        self._transition(
            MultiOrderExecutionState.PNL_RESOLVING, trade_idx,
        )
        try:
            realized = self._pnl_fetch(
                record=record, exit_price=exit_price,
                exit_reason=exit_reason,
            )
        except Exception:  # noqa: BLE001
            realized = None
        record.realized_pnl = realized
        self._emit(
            "pnl_recorded", trade_idx=trade_idx,
            realized_pnl=realized, close_reason=record.close_reason,
        )
        if realized is None:
            record.status = "unresolved"
            record.notes = "unresolved_pnl"
            self._transition(
                MultiOrderExecutionState.MANUAL_REVIEW_REQUIRED,
                trade_idx,
            )
            return record

        record.status = "completed"
        self._transition(
            MultiOrderExecutionState.TRADE_COMPLETED, trade_idx,
        )
        return record

    # ------------------------------------------------------------------

    @staticmethod
    def _extract(outcome: Any, key: str) -> Optional[Any]:
        if isinstance(outcome, dict):
            return outcome.get(key)
        return getattr(outcome, key, None)

    @staticmethod
    def _derive_close_reason(
        *, exit_reason: str, exit_price: Optional[float],
        record: RealTradeRecord,
    ) -> str:
        """tp|sl|reduce_only|manual|unknown a partir da saida."""
        if exit_reason == "reduce_only":
            return "reduce_only"
        if exit_reason == "tp_sl_server_side":
            if exit_price is None or record.entry_price <= 0:
                return "unknown"
            tp = record.take_profit_price
            sl = record.stop_loss_price
            # Distancia ao alvo mais proximo decide tp vs sl.
            dist_tp = abs(exit_price - tp) if tp else float("inf")
            dist_sl = abs(exit_price - sl) if sl else float("inf")
            if dist_tp == float("inf") and dist_sl == float("inf"):
                return "unknown"
            return "tp" if dist_tp <= dist_sl else "sl"
        if exit_reason == "manual":
            return "manual"
        return "unknown"


def env_reduce_only_enabled() -> bool:
    """Gate FASE 29 do reduceOnly close (reusado como fallback 30.2)."""
    return os.environ.get(
        "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED", "",
    ).strip().lower() in ("true", "1", "yes")


def build_real_trade_lifecycle(
    *,
    client: Any,
    executor: Any,
    provider: Any,
    risk_engine: Any,
    safety_machine: Any,
    mode_guard: Any,
    provider_registry: Any,
    profile: Any,
    effective_risk_config: Any,
    operator_token: str,
    symbol: str,
    strategy_name: str,
    max_monitor_minutes: int,
    poll_interval_seconds: float,
    telemetry_emit: Optional[Callable[..., None]] = None,
    notes: str = "",
) -> RealTradeLifecycle:
    """Factory de PRODUCAO: monta o lifecycle com wiring FASE 22/29.

    ⚠️  So usada pela CLI no caminho real gated. Testes NUNCA chamam
        esta factory — injetam fakes direto no RealTradeLifecycle.
    """
    import uuid as _uuid
    from datetime import datetime as _dt, timezone as _tz
    import time as _time
    from crypto_trading_bot.demo_endurance.production_wiring import (
        build_position_monitor,
        build_pnl_tracker,
        build_close_executor_wrapper,
        build_session_plan_factory,
    )
    from crypto_trading_bot.demo_endurance.flat_check_validator import (
        validate_flat,
    )
    from crypto_trading_bot.demo_endurance.gates_phase29 import (
        validate_phase29_close_gate,
    )
    # Lazy import com ALIAS (mesmo padrao sancionado do real_runner
    # FASE 27): o gate FASE 22 e o UNICO caminho de envio real.
    from crypto_trading_bot.demo_session_execution.gate import (
        execute_demo_session_gated as _fase22_gate,
    )

    session_plan_factory = build_session_plan_factory()
    monitor = build_position_monitor(
        client=client, symbol=symbol,
        poll_interval_seconds=poll_interval_seconds,
        max_monitor_minutes=max(1, int(max_monitor_minutes)),
    )
    pnl_tracker = build_pnl_tracker(client=client)
    close_wrapper = build_close_executor_wrapper(executor=executor)

    from types import SimpleNamespace
    _runner_plan_like = SimpleNamespace(
        symbol=symbol, strategy_name=strategy_name,
    )

    def _gate(*, trading_signal, latest_snapshot):
        # Snapshot SEMPRE fresco por trade (TTL): o lifecycle e
        # autossuficiente — ignora latest_snapshot do caller e busca
        # via provider.ensure_fresh (read-only).
        fresh_snapshot = provider.ensure_fresh(
            threshold_seconds=60.0, now=_dt.now(_tz.utc),
        )
        plan_id = f"endur30_2-{_uuid.uuid4().hex[:10]}"
        session_plan = session_plan_factory(
            plan_id=plan_id,
            live_snapshot=fresh_snapshot,
            trading_signal=trading_signal,
            runner_plan=_runner_plan_like,
            profile=profile,
            effective_risk_config=effective_risk_config,
            now=_dt.now(_tz.utc),
        )

        def _post_check():
            return executor.post_session_check(
                symbol=symbol, dry_run=False, stage="after_entry",
                expected_qty=float(
                    fresh_snapshot.blueprint.qty,
                ),
                require_sl=True,
            )

        return _fase22_gate(
            session_plan,
            risk_engine=risk_engine,
            demo_executor=executor,
            safety_machine=safety_machine,
            mode_guard=mode_guard,
            provider_registry=provider_registry,
            operator_token=operator_token,
            confirm_demo_session=True,
            dry_run=False,   # FASE 30.2: ordem REAL demo
            notes=notes[:200],
            post_session_check_fn=_post_check,
            now=_dt.now(_tz.utc),
        )

    def _sl_tp_confirmed(gate_outcome) -> Optional[bool]:
        snap = getattr(gate_outcome, "post_session_check_summary", None)
        if snap is None and isinstance(gate_outcome, dict):
            snap = gate_outcome.get("post_session_check_summary")
        if not snap:
            return None
        sl = snap.get("sl_attached")
        tp = snap.get("tp_attached")
        if sl is True and tp is True:
            return True
        if sl is False or tp is False:
            return False
        return None

    def _poll(poll_idx: int) -> dict:
        snap = monitor.poll_once(poll_idx=poll_idx)
        return {
            "open_position_qty": float(
                getattr(snap, "open_position_qty", 0.0) or 0.0,
            ),
            "mark_price": getattr(snap, "mark_price", None),
            "positions": list(getattr(snap, "positions", []) or []),
            "open_orders": list(
                getattr(snap, "open_orders", []) or [],
            ),
            "conditional_orders": list(
                getattr(snap, "conditional_orders", []) or [],
            ),
            "error": getattr(snap, "error", None),
        }

    def _flat(last_snap: dict) -> dict:
        flat = validate_flat(
            positions=last_snap.get("positions") or [],
            open_orders=last_snap.get("open_orders") or [],
            conditional_orders=(
                last_snap.get("conditional_orders") or []
            ),
        )
        d = flat.to_dict()
        d.setdefault("is_flat", getattr(flat, "is_flat", None))
        return d

    def _pnl(*, record: RealTradeRecord, exit_price, exit_reason):
        if exit_price is None:
            return None
        try:
            result = pnl_tracker.fetch_pnl(
                symbol=symbol,
                entry_price=record.entry_price,
                exit_price=float(exit_price),
                qty=record.qty,
                side=record.side,
                entry_ms=None,
                exit_ms=None,
                exit_reason=exit_reason,
            )
            return getattr(result, "realized_pnl_usd", None)
        except Exception:  # noqa: BLE001
            return None

    def _reduce_only(*, side: str, qty: float) -> dict:
        if not env_reduce_only_enabled():
            return {
                "success": False,
                "reason": "reduce_only_gate_disabled",
            }
        gate_result = validate_phase29_close_gate(
            has_open_position=True,
            position_qty=qty,
            requested_close_qty=qty,
            exit_decision_requires_reduce_only=True,
            exit_decision_should_close=True,
            safety_state="normal",
            safety_halt_recommended=False,
            close_orders_submitted_so_far=0,
            max_close_orders=1,
            operator_token=operator_token,
        )
        if not gate_result.approved:
            return {
                "success": False,
                "reason": "close_gate_rejected: "
                          + "; ".join(gate_result.blockers)[:120],
            }
        result = close_wrapper.close_position(
            symbol=symbol, position_side=side, position_qty=qty,
            dry_run=False, confirm_demo_execution=True,
        )
        return {
            "success": bool(getattr(result, "success", False)),
            "reason": str(getattr(result, "reason", ""))[:160],
        }

    max_polls = max(
        1,
        int((max_monitor_minutes * 60.0) / max(1.0,
                                               poll_interval_seconds)),
    )
    return RealTradeLifecycle(
        gate_callable=_gate,
        sl_tp_confirmed_fn=_sl_tp_confirmed,
        position_poll_fn=_poll,
        flat_check_fn=_flat,
        pnl_fetch_fn=_pnl,
        max_monitor_polls=max_polls,
        poll_interval_seconds=poll_interval_seconds,
        poll_sleep_fn=_time.sleep,   # producao: espera REAL
        reduce_only_close_fn=_reduce_only,
        telemetry_emit=telemetry_emit,
    )


__all__ = [
    "MultiOrderExecutionState",
    "RealTradeLifecycle",
    "RealTradeRecord",
    "build_real_trade_lifecycle",
    "can_accept_new_entry",
    "env_reduce_only_enabled",
]
