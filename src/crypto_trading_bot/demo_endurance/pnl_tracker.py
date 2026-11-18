"""
PnLTracker (FASE 29)
==========================
Tenta resolver P&L realizado de uma posicao demo via API read-only.
Fallback explicito quando dados nao disponiveis.

⚠️  TODOS os fetches sao INJETAVEIS (callables). Producao usa
    BybitClient via factory; testes injetam fakes 100% offline.

Politica:
    Ordem de fallback:
        1. execution_list_fetch (preferencial)
        2. closed_pnl_fetch (Bybit)
        3. local_calculation (entry/exit/qty conhecidos)
        4. manual_pending (nenhuma fonte disponivel)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


_VALID_SOURCES = (
    "api_execution_list",
    "api_closed_pnl",
    "local_calculation",
    "manual_pending",
)


@dataclass(frozen=True)
class PnLResult:
    """Resultado de fetch_pnl. Frozen + JSON-serializavel."""
    realized_pnl_usd: Optional[float]
    fees_usd: Optional[float]
    pnl_source: str
    entry_price: Optional[float]
    exit_price: Optional[float]
    qty: Optional[float]
    entry_timestamp: Optional[str]
    exit_timestamp: Optional[str]
    exit_reason: Optional[str]

    def __post_init__(self) -> None:
        if self.pnl_source not in _VALID_SOURCES:
            raise ValueError(
                f"pnl_source invalido: {self.pnl_source!r}; "
                f"aceitos: {list(_VALID_SOURCES)}"
            )

    def to_dict(self) -> dict:
        return {
            "realized_pnl_usd": self.realized_pnl_usd,
            "fees_usd": self.fees_usd,
            "pnl_source": self.pnl_source,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "qty": self.qty,
            "entry_timestamp": self.entry_timestamp,
            "exit_timestamp": self.exit_timestamp,
            "exit_reason": self.exit_reason,
        }


class PnLTracker:
    """Tracker injetavel de P&L para sessao demo.

    Args:
        execution_list_fetch: callable(symbol, start_ms, end_ms) -> Optional[dict].
                              Producao usa /v5/execution/list.
        closed_pnl_fetch:     callable(symbol, start_ms, end_ms) -> Optional[dict].
                              Producao usa /v5/position/closed-pnl.

    Cada callable pode retornar None se falhar; PnLTracker tenta a
    proxima fonte na ordem definida.
    """

    def __init__(
        self,
        *,
        execution_list_fetch: Optional[Callable[..., Any]] = None,
        closed_pnl_fetch: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._execution_list_fetch = execution_list_fetch
        self._closed_pnl_fetch = closed_pnl_fetch

    def fetch_pnl(
        self,
        *,
        symbol: str,
        entry_price: float,
        exit_price: Optional[float],
        qty: float,
        side: str,
        entry_ms: int,
        exit_ms: Optional[int],
        exit_reason: Optional[str] = None,
    ) -> PnLResult:
        """Resolve P&L na ordem de fallback declarada."""
        entry_ts = (
            self._ms_to_iso(entry_ms) if entry_ms else None
        )
        exit_ts = (
            self._ms_to_iso(exit_ms) if exit_ms else None
        )

        # 1. execution_list (API)
        if self._execution_list_fetch is not None and exit_ms is not None:
            try:
                data = self._execution_list_fetch(
                    symbol=symbol, start_ms=entry_ms, end_ms=exit_ms,
                )
            except Exception:  # noqa: BLE001
                data = None
            parsed = self._parse_execution_list(data)
            if parsed is not None:
                pnl, fees = parsed
                return PnLResult(
                    realized_pnl_usd=pnl, fees_usd=fees,
                    pnl_source="api_execution_list",
                    entry_price=float(entry_price),
                    exit_price=(
                        float(exit_price) if exit_price else None
                    ),
                    qty=float(qty), entry_timestamp=entry_ts,
                    exit_timestamp=exit_ts,
                    exit_reason=exit_reason,
                )

        # 2. closed_pnl (API)
        if self._closed_pnl_fetch is not None and exit_ms is not None:
            try:
                data = self._closed_pnl_fetch(
                    symbol=symbol, start_ms=entry_ms, end_ms=exit_ms,
                )
            except Exception:  # noqa: BLE001
                data = None
            parsed = self._parse_closed_pnl(data)
            if parsed is not None:
                pnl, fees = parsed
                return PnLResult(
                    realized_pnl_usd=pnl, fees_usd=fees,
                    pnl_source="api_closed_pnl",
                    entry_price=float(entry_price),
                    exit_price=(
                        float(exit_price) if exit_price else None
                    ),
                    qty=float(qty), entry_timestamp=entry_ts,
                    exit_timestamp=exit_ts,
                    exit_reason=exit_reason,
                )

        # 3. local calculation
        if exit_price is not None and qty > 0:
            side_norm = str(side).lower().strip()
            if side_norm == "buy":
                pnl_local = (float(exit_price) - float(entry_price)) \
                    * float(qty)
            else:
                pnl_local = (float(entry_price) - float(exit_price)) \
                    * float(qty)
            return PnLResult(
                realized_pnl_usd=round(pnl_local, 4),
                fees_usd=None,
                pnl_source="local_calculation",
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                qty=float(qty), entry_timestamp=entry_ts,
                exit_timestamp=exit_ts,
                exit_reason=exit_reason,
            )

        # 4. manual pending
        return PnLResult(
            realized_pnl_usd=None,
            fees_usd=None,
            pnl_source="manual_pending",
            entry_price=float(entry_price),
            exit_price=(float(exit_price) if exit_price else None),
            qty=float(qty), entry_timestamp=entry_ts,
            exit_timestamp=exit_ts,
            exit_reason=exit_reason,
        )

    # ------------------------------------------------------------- helpers

    @staticmethod
    def _ms_to_iso(ms: int) -> str:
        from datetime import datetime, timezone
        try:
            return datetime.fromtimestamp(
                int(ms) / 1000.0, tz=timezone.utc,
            ).isoformat()
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _parse_execution_list(data: Any) -> Optional[tuple]:
        """Bybit /v5/execution/list -> agrega execPnl + execFee."""
        if not isinstance(data, dict):
            return None
        lst = (data.get("result") or {}).get("list", [])
        if not isinstance(lst, list) or not lst:
            return None
        pnl_total = 0.0
        fee_total = 0.0
        any_pnl = False
        for item in lst:
            if not isinstance(item, dict):
                continue
            try:
                if "execPnl" in item:
                    pnl_total += float(item.get("execPnl") or 0.0)
                    any_pnl = True
                if "execFee" in item:
                    fee_total += float(item.get("execFee") or 0.0)
            except (TypeError, ValueError):
                continue
        if not any_pnl:
            return None
        return (round(pnl_total, 4), round(fee_total, 4))

    @staticmethod
    def _parse_closed_pnl(data: Any) -> Optional[tuple]:
        """Bybit /v5/position/closed-pnl -> closedPnl + cumExitFee."""
        if not isinstance(data, dict):
            return None
        lst = (data.get("result") or {}).get("list", [])
        if not isinstance(lst, list) or not lst:
            return None
        pnl_total = 0.0
        fee_total = 0.0
        for item in lst:
            if not isinstance(item, dict):
                continue
            try:
                pnl_total += float(item.get("closedPnl") or 0.0)
                fee_total += float(item.get("cumExitFee") or 0.0)
            except (TypeError, ValueError):
                continue
        return (round(pnl_total, 4), round(fee_total, 4))


__all__ = ["PnLResult", "PnLTracker"]
