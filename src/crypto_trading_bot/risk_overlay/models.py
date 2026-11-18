"""
Modelos do Risk Overlay (FASE 57). Tudo simples/serializavel; input manual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass(frozen=True)
class RiskLimits:
    """Limites do perfil operacional (RiskConfig efetivo / HyroTrader)."""
    capital_usd: float = 5000.0
    max_risk_per_trade_pct: float = 0.005      # 0,5% => US$25
    max_daily_loss_pct: float = 0.04           # 4% => US$200
    max_total_loss_pct: float = 0.06           # 6% => equity floor 4700
    max_exposure_pct: float = 1.0              # leverage 1x => notional<=capital
    max_leverage: float = 1.0
    max_open_positions: int = 1
    min_stop_loss_pct: float = 0.005           # piso soberano

    @property
    def max_risk_per_trade_usd(self) -> float:
        return round(self.max_risk_per_trade_pct * self.capital_usd, 2)

    @property
    def max_daily_loss_usd(self) -> float:
        return round(self.max_daily_loss_pct * self.capital_usd, 2)

    @property
    def equity_floor_usd(self) -> float:
        return round(self.capital_usd * (1.0 - self.max_total_loss_pct), 2)

    def to_dict(self) -> dict:
        return {"capital_usd": self.capital_usd,
                "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
                "max_risk_per_trade_usd": self.max_risk_per_trade_usd,
                "max_daily_loss_pct": self.max_daily_loss_pct,
                "max_daily_loss_usd": self.max_daily_loss_usd,
                "max_total_loss_pct": self.max_total_loss_pct,
                "equity_floor_usd": self.equity_floor_usd,
                "max_exposure_pct": self.max_exposure_pct,
                "max_leverage": self.max_leverage,
                "max_open_positions": self.max_open_positions,
                "min_stop_loss_pct": self.min_stop_loss_pct}


@dataclass(frozen=True)
class Position:
    symbol: str
    side: str                                  # "long" | "short"
    notional_usd: float
    entry_price: float
    mark_price: float
    stop_loss_price: Optional[float] = None
    unrealized_pnl_usd: Optional[float] = None
    funding_rate: Optional[float] = None       # taxa corrente (opcional)

    def qty(self) -> float:
        return (self.notional_usd / self.entry_price) if self.entry_price else 0.0

    def stop_dist_pct(self) -> Optional[float]:
        if self.stop_loss_price is None or self.entry_price <= 0:
            return None
        return abs(self.entry_price - self.stop_loss_price) / self.entry_price

    def risk_to_stop_usd(self) -> Optional[float]:
        d = self.stop_dist_pct()
        return round(d * self.notional_usd, 2) if d is not None else None

    def unrealized(self) -> float:
        if self.unrealized_pnl_usd is not None:
            return float(self.unrealized_pnl_usd)
        if self.entry_price <= 0:
            return 0.0
        sign = 1.0 if self.side.lower() in ("long", "buy") else -1.0
        return round(sign * (self.mark_price / self.entry_price - 1.0)
                     * self.notional_usd, 2)

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "side": self.side,
                "notional_usd": self.notional_usd, "entry_price": self.entry_price,
                "mark_price": self.mark_price,
                "stop_loss_price": self.stop_loss_price,
                "stop_dist_pct": (round(self.stop_dist_pct(), 6)
                                  if self.stop_dist_pct() is not None else None),
                "risk_to_stop_usd": self.risk_to_stop_usd(),
                "unrealized_pnl_usd": self.unrealized(),
                "funding_rate": self.funding_rate}


@dataclass(frozen=True)
class AccountState:
    equity_usd: float
    balance_usd: float
    realized_pnl_today_usd: float = 0.0
    day: Optional[str] = None

    def to_dict(self) -> dict:
        return {"equity_usd": self.equity_usd, "balance_usd": self.balance_usd,
                "realized_pnl_today_usd": self.realized_pnl_today_usd,
                "day": self.day}


@dataclass(frozen=True)
class Alert:
    code: str
    severity: str                              # info|low|medium|high|critical
    scope: str                                 # "account" | "position:<sym>"
    message: str
    recommendation: str
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "scope": self.scope,
                "message": self.message, "recommendation": self.recommendation,
                "evidence": dict(self.evidence)}


__all__ = ["RiskLimits", "Position", "AccountState", "Alert", "SEVERITY_ORDER"]
