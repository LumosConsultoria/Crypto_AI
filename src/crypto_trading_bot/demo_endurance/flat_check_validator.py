"""
FlatCheckValidator (FASE 29)
================================
Validador puro do estado flat final.

⚠️  ZERO importacao de rede / API. Funcao pura sobre snapshots ja
    coletados por PositionMonitor / post_session_check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Tuple


# Tolerancia de qty: abaixo disso a exposicao e tratada como ZERO.
# A Bybit Demo retorna estruturas de posicao com size="0" para o
# simbolo mesmo SEM exposicao; tais estruturas NAO sao posicao aberta.
_DEFAULT_QTY_TOLERANCE = 1e-9

# Campos de quantidade reconhecidos (ordem de preferencia).
_QTY_FIELDS = (
    "size", "qty", "position_qty", "current_qty",
    "position_size", "positionSize", "contracts",
)
# Fallback por valor nocional quando nenhum campo de qty existe.
_NOTIONAL_FIELDS = (
    "position_value", "positionValue", "notional", "notional_usd",
)


@dataclass(frozen=True)
class FlatCheckResult:
    """Resultado de validacao flat.

    Atributos:
        is_flat:                  True se TUDO esta efetivamente zerado.
        positions_count:          int >= 0 (contagem ESTRUTURAL: numero
                                  de estruturas de posicao retornadas,
                                  incluindo as com size zero).
        effective_open_positions_count: posicoes com exposicao efetiva
                                  acima da tolerancia (ou estrutura
                                  ambigua sem campo de qty reconhecido).
                                  E ESTE valor que define is_flat.
        open_orders_count:        int >= 0.
        conditional_orders_count: int >= 0.
        residual_qty:             float (>= 0; soma de qty efetiva).
        blockers:                 tupla de razoes humanas se nao flat.
    """
    is_flat: bool
    positions_count: int
    open_orders_count: int
    conditional_orders_count: int
    residual_qty: float
    blockers: Tuple[str, ...]
    effective_open_positions_count: int = 0

    def to_dict(self) -> dict:
        return {
            "is_flat": bool(self.is_flat),
            "positions_count": int(self.positions_count),
            "effective_open_positions_count": int(
                self.effective_open_positions_count
            ),
            "open_orders_count": int(self.open_orders_count),
            "conditional_orders_count":
                int(self.conditional_orders_count),
            "residual_qty": float(self.residual_qty),
            "blockers": list(self.blockers),
        }


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _position_effective_qty(position: Any) -> Optional[float]:
    """abs(qty efetiva) de UMA posicao, ou None se ambigua.

    - campo de qty reconhecido com valor numerico  -> abs(valor);
    - campo presente porem vazio ("" / None)        -> 0.0 (zerado);
    - nenhum campo de qty/nocional reconhecido      -> None (ambiguo).
    """
    if not isinstance(position, dict):
        return None
    saw_field = False
    for field in _QTY_FIELDS + _NOTIONAL_FIELDS:
        if field not in position:
            continue
        saw_field = True
        raw = position[field]
        if raw is None or str(raw).strip() == "":
            continue  # presente mas vazio => contribuicao zero
        return abs(_coerce_float(raw, 0.0))
    return 0.0 if saw_field else None


def is_effectively_flat_position(
    position: Any, tolerance: float = _DEFAULT_QTY_TOLERANCE,
) -> bool:
    """True se a posicao NAO tem exposicao efetiva.

    Estrutura ambigua (sem qualquer campo de qty/nocional) e tratada
    de forma CONSERVADORA como nao-flat (nunca mascara posicao real).
    """
    qty = _position_effective_qty(position)
    if qty is None:
        return False
    return qty <= tolerance


def _positions_qty_sum(positions: Optional[Iterable]) -> float:
    """Soma qty EFETIVA das posicoes (ambigua conta como 0 na soma)."""
    if not positions:
        return 0.0
    total = 0.0
    for p in positions:
        qty = _position_effective_qty(p)
        if qty is not None:
            total += qty
    return total


def validate_flat(
    *,
    positions: Optional[Iterable] = None,
    open_orders: Optional[Iterable] = None,
    conditional_orders: Optional[Iterable] = None,
    expected_zero_residual_qty: bool = True,
) -> FlatCheckResult:
    """Funcao pura: valida que tudo esta zerado.

    Args:
        positions:               iteravel de dicts/posicao snapshot.
        open_orders:             iteravel de dicts.
        conditional_orders:      iteravel de dicts (StopOrder etc.).
        expected_zero_residual_qty: True (default) exige soma de qty
                                    das posicoes == 0.

    Returns:
        FlatCheckResult imutavel.
    """
    positions = list(positions or [])
    open_orders = list(open_orders or [])
    conditional_orders = list(conditional_orders or [])

    positions_count = len(positions)   # ESTRUTURAL (inclui size zero)
    # Posicoes com exposicao efetiva (ou estrutura ambigua).
    effective_open_positions_count = sum(
        1 for p in positions if not is_effectively_flat_position(p)
    )
    open_orders_count = len(open_orders)
    conditional_orders_count = len(conditional_orders)
    residual_qty = _positions_qty_sum(positions)

    blockers = []
    # HOTFIX: o blocker de posicao usa a contagem EFETIVA, nao a
    # estrutural. Estruturas com size zero retornadas pela exchange
    # NAO contam como posicao aberta.
    if effective_open_positions_count > 0:
        blockers.append(
            f"effective_open_positions_count="
            f"{effective_open_positions_count} > 0 "
            f"(residual_qty={residual_qty}; "
            f"structural_positions={positions_count})"
        )
    if open_orders_count > 0:
        blockers.append(f"open_orders_count={open_orders_count} > 0")
    if conditional_orders_count > 0:
        blockers.append(
            f"conditional_orders_count={conditional_orders_count} > 0"
        )
    if expected_zero_residual_qty and \
            residual_qty > _DEFAULT_QTY_TOLERANCE:
        blockers.append(
            f"residual_qty={residual_qty} > 0 (esperado 0.0)"
        )

    is_flat = not blockers
    return FlatCheckResult(
        is_flat=is_flat,
        positions_count=positions_count,
        open_orders_count=open_orders_count,
        conditional_orders_count=conditional_orders_count,
        residual_qty=residual_qty,
        blockers=tuple(blockers),
        effective_open_positions_count=effective_open_positions_count,
    )


__all__ = [
    "FlatCheckResult",
    "is_effectively_flat_position",
    "validate_flat",
]
