"""
EnduranceLimits - tetos operacionais da demo endurance (FASE 30)
=================================================================
Limites operacionais ADICIONAIS aplicados pelo DemoEnduranceRunner.

⚠️  NAO substituem nem duplicam a soberania do RiskEngine. O RiskEngine
    continua validando cada sinal individualmente. Estes limites sao
    tetos de SESSAO (por dia / por sessao / consecutivos) que o runner
    aplica por cima, sempre no sentido de RESTRINGIR.

⚠️  Frozen, JSON-serializavel, ZERO rede, ZERO secret.

⚠️  Multi-order-ready: max_orders_per_session default = 1 (single-order).
    A liberacao de multi-ordem real demo depende do gate
    DEMO_ALLOW_MULTI_ORDER_PER_SESSION (fase futura) e NUNCA deste
    dataclass sozinho.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnduranceLimits:
    """Tetos operacionais de uma sessao demo endurance.

    Todos os campos restringem; nenhum concede permissao nova.
    """

    max_orders_per_day: int = 3
    max_orders_per_session: int = 1
    max_open_positions: int = 1
    max_daily_loss_pct: float = 1.0
    max_total_loss_pct: float = 2.0
    max_consecutive_losses: int = 2
    max_api_failures: int = 3
    max_stale_data_seconds: float = 300.0
    require_sl_tp: bool = True
    flat_check_interval_minutes: int = 5

    def __post_init__(self) -> None:
        if self.max_orders_per_day < 1:
            raise ValueError(
                f"max_orders_per_day deve ser >= 1: {self.max_orders_per_day}"
            )
        if self.max_orders_per_session < 1:
            raise ValueError(
                "max_orders_per_session deve ser >= 1: "
                f"{self.max_orders_per_session}"
            )
        if self.max_open_positions < 1:
            raise ValueError(
                f"max_open_positions deve ser >= 1: {self.max_open_positions}"
            )
        if not (0 < self.max_daily_loss_pct <= 100):
            raise ValueError(
                f"max_daily_loss_pct em (0, 100]: {self.max_daily_loss_pct}"
            )
        if not (0 < self.max_total_loss_pct <= 100):
            raise ValueError(
                f"max_total_loss_pct em (0, 100]: {self.max_total_loss_pct}"
            )
        if self.max_consecutive_losses < 1:
            raise ValueError(
                "max_consecutive_losses deve ser >= 1: "
                f"{self.max_consecutive_losses}"
            )
        if self.max_api_failures < 1:
            raise ValueError(
                f"max_api_failures deve ser >= 1: {self.max_api_failures}"
            )
        if self.max_stale_data_seconds <= 0:
            raise ValueError(
                "max_stale_data_seconds deve ser > 0: "
                f"{self.max_stale_data_seconds}"
            )
        if self.flat_check_interval_minutes < 1:
            raise ValueError(
                "flat_check_interval_minutes deve ser >= 1: "
                f"{self.flat_check_interval_minutes}"
            )

    def to_dict(self) -> dict:
        return {
            "max_orders_per_day": int(self.max_orders_per_day),
            "max_orders_per_session": int(self.max_orders_per_session),
            "max_open_positions": int(self.max_open_positions),
            "max_daily_loss_pct": float(self.max_daily_loss_pct),
            "max_total_loss_pct": float(self.max_total_loss_pct),
            "max_consecutive_losses": int(self.max_consecutive_losses),
            "max_api_failures": int(self.max_api_failures),
            "max_stale_data_seconds": float(self.max_stale_data_seconds),
            "require_sl_tp": bool(self.require_sl_tp),
            "flat_check_interval_minutes": int(
                self.flat_check_interval_minutes
            ),
        }


__all__ = ["EnduranceLimits"]
