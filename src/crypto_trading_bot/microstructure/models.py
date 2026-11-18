"""
Modelos da microestrutura (FASE 63). Timestamps em SEGUNDOS epoch (float) para
janelas sub-segundo. Tudo serializavel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

Level = Tuple[float, float]            # (price, size)


@dataclass(frozen=True)
class Trade:
    ts: float
    price: float
    size: float
    side: str                          # "buy" | "sell" (lado AGRESSOR/taker)


@dataclass(frozen=True)
class BookSnapshot:
    ts: float
    bids: Sequence[Level]              # desc por preco
    asks: Sequence[Level]             # asc por preco

    def best_bid(self) -> Optional[Level]:
        return self.bids[0] if self.bids else None

    def best_ask(self) -> Optional[Level]:
        return self.asks[0] if self.asks else None

    def mid(self) -> Optional[float]:
        b, a = self.best_bid(), self.best_ask()
        return (a[0] + b[0]) / 2 if (b and a) else None

    def spread(self) -> Optional[float]:
        b, a = self.best_bid(), self.best_ask()
        return (a[0] - b[0]) if (b and a) else None

    def microprice(self) -> Optional[float]:
        b, a = self.best_bid(), self.best_ask()
        if not (b and a):
            return None
        qb, qa = b[1], a[1]
        return ((b[0] * qa + a[0] * qb) / (qa + qb)) if (qa + qb) > 0 \
            else self.mid()

    def depth(self, side: str, levels: int = 10) -> float:
        seq = self.bids if side == "bid" else self.asks
        return sum(s for _, s in list(seq)[:levels])


@dataclass(frozen=True)
class Tick:
    """Um poll: snapshot do book + trades novos desde o poll anterior."""
    ts: float
    book: BookSnapshot
    trades: Sequence[Trade] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"ts": self.ts,
                "bids": [list(x) for x in self.book.bids],
                "asks": [list(x) for x in self.book.asks],
                "trades": [{"ts": t.ts, "price": t.price, "size": t.size,
                            "side": t.side} for t in self.trades]}


@dataclass(frozen=True)
class RiskParams:
    capital_usd: float = 5000.0
    risk_pct: float = 0.005            # 0,5% primario
    max_open_positions: int = 1
    leverage: float = 1.0
    min_hard_stop_pct: float = 0.005   # piso soberano 0,5%
    taker_fee_bps: float = 6.0         # por lado (Bybit linear taker ~0,06%)


@dataclass(frozen=True)
class Signal:
    ts: float
    direction: str                     # "long" | "short"
    entry_ref: float                   # mid no instante
    features: Mapping = field(default_factory=dict)
    vetoes: Sequence[str] = field(default_factory=tuple)   # vazio = aprovado

    @property
    def approved(self) -> bool:
        return len(self.vetoes) == 0

    def to_dict(self) -> dict:
        return {"ts": self.ts, "direction": self.direction,
                "entry_ref": self.entry_ref, "approved": self.approved,
                "vetoes": list(self.vetoes), "features": dict(self.features)}


@dataclass(frozen=True)
class ShadowTrade:
    entry_ts: float
    exit_ts: float
    direction: str
    entry_fill: float
    exit_fill: float
    notional_usd: float
    stop_price: float
    gross_pnl_usd: float
    fees_usd: float
    slippage_usd: float
    net_pnl_usd: float
    exit_reason: str                   # soft_ofi|soft_aggr|soft_time|tp|hard_stop
    hold_seconds: float

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)

__all__ = ["Level", "Trade", "BookSnapshot", "Tick", "RiskParams", "Signal",
           "ShadowTrade"]
