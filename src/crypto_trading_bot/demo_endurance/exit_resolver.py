"""
ExitDecisionResolver (FASE 29)
====================================
Wraps ExitPolicy (FASE 11) com ProviderCapability adequada para
caminho FASE 29 (bybit_demo_linear com supports_reduce_only=True).

⚠️  Funcao pura. NAO envia ordem. NAO chama rede. Resolve decisao
    com base em snapshot da posicao + candle atual + signal opcional.

⚠️  Reaproveita: ExitPolicy.evaluate da FASE 11 + ExitDecision +
    OpenPositionState + PositionSide.

⚠️  apply_demo_real do runner determina dry_run no gate; ExitDecision
    eh sempre obtida com requires_reduce_only respeitando capability.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


# Defaults conservadores FASE 29.
DEFAULT_MAX_TIME_IN_POSITION_SECONDS = 25 * 60  # 25 min
DEFAULT_ALLOW_OPPOSITE_SIGNAL = False
DEFAULT_EMERGENCY_CLOSE_ENABLED = True


def build_phase29_exit_policy(
    *,
    max_time_in_position_seconds: int = (
        DEFAULT_MAX_TIME_IN_POSITION_SECONDS
    ),
    allow_close_on_opposite_signal: bool = (
        DEFAULT_ALLOW_OPPOSITE_SIGNAL
    ),
    emergency_close_enabled: bool = DEFAULT_EMERGENCY_CLOSE_ENABLED,
):
    """Constroi ExitPolicy FASE 29 com ProviderCapability adequada.

    Lazy import - nao puxa rede.
    """
    from crypto_trading_bot.execution.provider_capability import (
        ProviderCapability,
    )
    from crypto_trading_bot.exit_policy.exit_policy import ExitPolicy

    # Capability declarativa para bybit_demo_linear (FASE 29).
    capability = ProviderCapability(
        provider_id="bybit_demo_linear",
        supports_market_order=True,
        supports_stop_loss=True,
        supports_take_profit=True,
        supports_reduce_only=True,   # FASE 29
        supports_positions_query=True,
        supports_balance_query=True,
        supports_cancel_order=True,
        is_demo_environment=True,
        is_live_environment=False,
        documented_assets=("BTCUSDT",),
        confirmed=False,  # capability declarativa; nao autoriza per se
        confirmation_source="",
        notes=(
            "FASE 29 - reduceOnly close via API liberado. ModeGuard + "
            "execute_demo_close_gated + post_session_check(flat_check) "
            "continuam soberanos."
        ),
    )
    return ExitPolicy(
        provider_capability=capability,
        max_time_in_position_candles=None,
        max_time_in_position_seconds=max_time_in_position_seconds,
        allow_close_on_opposite_signal=allow_close_on_opposite_signal,
        require_reduce_only_for_auto_close=True,
        emergency_close_enabled=emergency_close_enabled,
    )


def build_open_position_state_from_snapshot(
    snapshot: dict,
    *,
    symbol: str,
    entry_price: float,
    entry_time: datetime,
    stop_loss: float,
    take_profit: Optional[float],
    position_size_usd: float,
) -> Any:
    """Cria OpenPositionState a partir de snapshot de posicao live."""
    from crypto_trading_bot.exit_policy.exit_decision import (
        OpenPositionState, PositionSide,
    )

    side_raw = str(snapshot.get("side") or "buy").lower().strip()
    side_enum = (
        PositionSide.BUY if side_raw == "buy" else PositionSide.SELL
    )
    return OpenPositionState(
        symbol=symbol,
        side=side_enum,
        entry_price=float(entry_price),
        entry_time=entry_time,
        stop_loss_price=float(stop_loss),
        take_profit_price=(
            float(take_profit) if take_profit is not None else None
        ),
        position_size_usd=float(position_size_usd),
        entry_candle_idx=None,
    )


class ExitDecisionResolver:
    """Wrapper de ExitPolicy.evaluate para FASE 29.

    Args:
        exit_policy:  ExitPolicy ja construida (ou usar
                      build_phase29_exit_policy()).
        clock:        callable() -> datetime UTC; default agora.
    """

    def __init__(self, *, exit_policy: Any, clock=None) -> None:
        self._exit_policy = exit_policy
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )

    @property
    def exit_policy(self) -> Any:
        return self._exit_policy

    def resolve(
        self,
        *,
        position: Any,
        candle: Optional[Any] = None,
        candle_idx: Optional[int] = None,
        latest_signal: Optional[Any] = None,
        emergency_active: bool = False,
        manual_close_requested: bool = False,
    ) -> Any:
        """Delega para ExitPolicy.evaluate; sempre retorna ExitDecision."""
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return self._exit_policy.evaluate(
            position=position,
            candle=candle,
            candle_idx=candle_idx,
            now=now,
            latest_signal=latest_signal,
            manual_close_requested=manual_close_requested,
            emergency_active=emergency_active,
        )


__all__ = [
    "DEFAULT_MAX_TIME_IN_POSITION_SECONDS",
    "DEFAULT_ALLOW_OPPOSITE_SIGNAL",
    "DEFAULT_EMERGENCY_CLOSE_ENABLED",
    "ExitDecisionResolver",
    "build_phase29_exit_policy",
    "build_open_position_state_from_snapshot",
]
