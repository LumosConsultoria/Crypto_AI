"""
PositionMonitor (FASE 29)
==============================
Monitoramento read-only da posicao demo apos entrada gated.

⚠️  Todos os fetches sao INJETAVEIS (callables). Producao usa
    BybitClient via factory; testes injetam fakes.

⚠️  ZERO importacao de rede top-level. ZERO ordem.

Cada poll snapshota:
    - positions (qty, side, entry_price, mark_price, unrealized_pnl);
    - open_orders;
    - conditional_orders;
    - mark_price (best-effort).

Telemetria position_snapshot eh emitida fora deste modulo (pelo
runner ou pelo caller).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional


DEFAULT_POLL_INTERVAL_SECONDS = 60.0
DEFAULT_MAX_MONITOR_MINUTES = 30
API_FAILURE_STRIKES_THRESHOLD = 3


@dataclass
class PositionSnapshot:
    """Snapshot single de um ciclo de monitor."""
    timestamp: datetime
    poll_idx: int
    positions: List[dict] = field(default_factory=list)
    open_orders: List[dict] = field(default_factory=list)
    conditional_orders: List[dict] = field(default_factory=list)
    mark_price: Optional[float] = None
    error: Optional[str] = None  # sanitizado quando preenchido

    @property
    def open_position_qty(self) -> float:
        total = 0.0
        for p in self.positions:
            if isinstance(p, dict):
                try:
                    total += abs(float(
                        p.get("size") or p.get("qty") or 0.0
                    ))
                except (TypeError, ValueError):
                    continue
        return total

    @property
    def is_flat(self) -> bool:
        return (
            self.open_position_qty == 0.0
            and len(self.open_orders) == 0
            and len(self.conditional_orders) == 0
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat()
            if self.timestamp.tzinfo
            else self.timestamp.replace(
                tzinfo=timezone.utc
            ).isoformat(),
            "poll_idx": int(self.poll_idx),
            "positions_count": len(self.positions),
            "open_orders_count": len(self.open_orders),
            "conditional_orders_count": len(self.conditional_orders),
            "open_position_qty": float(self.open_position_qty),
            "mark_price": self.mark_price,
            "error": self.error,
        }


class PositionMonitor:
    """Monitora posicao demo via callables injetaveis.

    Args:
        symbol:                    "BTCUSDT".
        positions_fetch:           callable(symbol) -> list[dict].
        orders_fetch:              callable(symbol) -> list[dict].
        conditional_orders_fetch:  callable(symbol) -> list[dict].
        ticker_fetch:              callable(symbol) -> Optional[float] (mark).
        poll_interval_seconds:     default 60.0.
        max_monitor_minutes:       default 30.
        clock:                     callable() -> datetime UTC.
        sleep:                     callable(seconds) -> None.
    """

    def __init__(
        self,
        *,
        symbol: str,
        positions_fetch: Callable[..., Any],
        orders_fetch: Callable[..., Any],
        conditional_orders_fetch: Callable[..., Any],
        ticker_fetch: Optional[Callable[..., Any]] = None,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_monitor_minutes: int = DEFAULT_MAX_MONITOR_MINUTES,
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
    ) -> None:
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol deve ser string nao-vazia")
        if poll_interval_seconds <= 0:
            raise ValueError(
                f"poll_interval_seconds > 0: {poll_interval_seconds}"
            )
        if max_monitor_minutes <= 0:
            raise ValueError(
                f"max_monitor_minutes > 0: {max_monitor_minutes}"
            )
        self._symbol = symbol
        self._positions_fetch = positions_fetch
        self._orders_fetch = orders_fetch
        self._conditional_orders_fetch = conditional_orders_fetch
        self._ticker_fetch = ticker_fetch
        self._poll_interval_seconds = float(poll_interval_seconds)
        self._max_monitor_minutes = int(max_monitor_minutes)
        self._clock = clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._sleep = sleep or (lambda s: None)
        self._strike_count = 0

    @property
    def symbol(self) -> str:
        return self._symbol

    @property
    def max_monitor_minutes(self) -> int:
        return self._max_monitor_minutes

    @property
    def poll_interval_seconds(self) -> float:
        return self._poll_interval_seconds

    @property
    def api_failure_strikes(self) -> int:
        return self._strike_count

    def poll_once(self, *, poll_idx: int) -> PositionSnapshot:
        """Roda um poll. NAO levanta excecao; encapsula erro em
        snapshot.error sanitizado."""
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        positions: List[dict] = []
        open_orders: List[dict] = []
        conditional_orders: List[dict] = []
        mark_price: Optional[float] = None
        error: Optional[str] = None

        try:
            res = self._positions_fetch(symbol=self._symbol)
            if isinstance(res, list):
                positions = [p for p in res if isinstance(p, dict)]
        except Exception as e:  # noqa: BLE001
            error = self._sanitize_error(e, "positions_fetch")
            self._strike_count += 1
            return PositionSnapshot(
                timestamp=now, poll_idx=poll_idx, error=error,
            )

        try:
            res = self._orders_fetch(symbol=self._symbol)
            if isinstance(res, list):
                open_orders = [o for o in res if isinstance(o, dict)]
        except Exception as e:  # noqa: BLE001
            error = self._sanitize_error(e, "orders_fetch")
            self._strike_count += 1
            return PositionSnapshot(
                timestamp=now, poll_idx=poll_idx,
                positions=positions, error=error,
            )

        try:
            res = self._conditional_orders_fetch(symbol=self._symbol)
            if isinstance(res, list):
                conditional_orders = [
                    c for c in res if isinstance(c, dict)
                ]
        except Exception as e:  # noqa: BLE001
            error = self._sanitize_error(
                e, "conditional_orders_fetch",
            )
            self._strike_count += 1
            return PositionSnapshot(
                timestamp=now, poll_idx=poll_idx,
                positions=positions, open_orders=open_orders,
                error=error,
            )

        if self._ticker_fetch is not None:
            try:
                tick = self._ticker_fetch(symbol=self._symbol)
                if isinstance(tick, (int, float)):
                    mark_price = float(tick)
            except Exception:  # noqa: BLE001
                mark_price = None

        # Sucesso: reseta strike count.
        self._strike_count = 0
        return PositionSnapshot(
            timestamp=now, poll_idx=poll_idx,
            positions=positions,
            open_orders=open_orders,
            conditional_orders=conditional_orders,
            mark_price=mark_price,
        )

    def has_too_many_failures(self) -> bool:
        return self._strike_count >= API_FAILURE_STRIKES_THRESHOLD

    def sleep_until_next_poll(self) -> None:
        self._sleep(self._poll_interval_seconds)

    @staticmethod
    def _sanitize_error(exc: Exception, source: str) -> str:
        """Sanitiza mensagem de erro removendo possiveis secrets."""
        try:
            from crypto_trading_bot.exchange.bybit_client import (
                redact_ret_msg,
            )
            raw = redact_ret_msg(str(exc))
        except Exception:  # noqa: BLE001
            raw = str(exc)
        return f"{source}:{type(exc).__name__}:{raw[:120]}"


__all__ = [
    "API_FAILURE_STRIKES_THRESHOLD",
    "DEFAULT_MAX_MONITOR_MINUTES",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "PositionMonitor",
    "PositionSnapshot",
]
