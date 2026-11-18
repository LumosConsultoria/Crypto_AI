"""
ExitDecision — Modelo imutável de decisão de saída (FASE 11)
=============================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - ExitDecision é APENAS uma decisão auditável. NÃO chama executor.
    - NÃO envia ordem. NÃO chama rede. NÃO conhece provider real.
    - ExitDecision.auto_execute_blocked descreve a camada de CAPABILITY.
      Execução real exige adicionalmente: ProviderStatus permitido,
      ModeGuard adequado, ambiente correto, RiskEngine consistente e
      fase futura de integração. Capability ≠ autorização de execução.

CAMPOS:
    should_close:        decisão final (True → fechar, False → manter).
    reason:              ExitReason explicando o porquê (enum estável).
    source:              ExitSource indicando quem decidiu.
    triggered_at_idx:    índice do candle de gatilho (backtest) ou None.
    triggered_at_time:   timestamp UTC do gatilho.
    requires_reduce_only:True se o fechamento, se executado via API,
                         exige a flag reduceOnly do provider.
    auto_execute_blocked:True se a CAPABILITY do provider bloqueia o
                         fechamento automático (i.e. supports_reduce_only
                         é False ou política exige). Não é autorização —
                         é apenas a camada técnica.
    metadata:            dict imutável (MappingProxyType) para auditoria.
                         Pode conter "capability_allows_auto_close" como
                         indicador booleano. NÃO contém "execution_allowed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional


# ---------------------------------------------------------------------------
# Enums estáveis (valores são contrato — não renomear sem nova fase)
# ---------------------------------------------------------------------------

class ExitReason(str, Enum):
    """Motivo da saída. Ordem de precedência definida em ExitPolicy."""
    EMERGENCY = "emergency"
    MANUAL = "manual"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    OPPOSITE_SIGNAL = "opposite_signal"
    TIME_LIMIT = "time_limit"
    END_OF_DATA = "end_of_data"
    NONE = "none"  # usado quando should_close=False


class ExitSource(str, Enum):
    """Quem decidiu a saída (origem da regra)."""
    RULE_EMERGENCY = "rule_emergency"
    RULE_MANUAL = "rule_manual"
    RULE_SL_TP = "rule_sl_tp"
    RULE_OPPOSITE = "rule_opposite"
    RULE_TIME = "rule_time"
    SYSTEM_EOD = "system_eod"
    NONE = "none"


class PositionSide(str, Enum):
    """Lado da posição aberta. Espelha OrderSide.value sem importá-lo."""
    BUY = "buy"
    SELL = "sell"


# ---------------------------------------------------------------------------
# OpenPositionState — snapshot imutável do estado da posição
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenPositionState:
    """
    Snapshot imutável de uma posição aberta consumida pela ExitPolicy.

    Não é o BacktestTrade nem o PaperTrade — é o tipo neutro que a
    ExitPolicy entende. A conversão de BacktestTrade/PaperTrade para
    OpenPositionState é responsabilidade do chamador (futuro adapter).

    Campos:
        symbol:             Ex: "BTCUSDT".
        side:               PositionSide.BUY ou PositionSide.SELL.
        entry_price:        Preço efetivo de entrada.
        entry_time:         Timestamp UTC da entrada.
        entry_candle_idx:   Índice do candle de entrada (backtest) ou None
                            quando em modo live (sem grade de candles).
        stop_loss_price:    Preço de stop (sempre > 0).
        take_profit_price:  Preço de take profit (opcional).
        position_size_usd:  Notional em USD.
    """
    symbol: str
    side: PositionSide
    entry_price: float
    entry_time: datetime
    stop_loss_price: float
    position_size_usd: float
    entry_candle_idx: Optional[int] = None
    take_profit_price: Optional[float] = None

    def __post_init__(self) -> None:
        if self.entry_price <= 0:
            raise ValueError(
                f"entry_price deve ser positivo: {self.entry_price}"
            )
        if self.stop_loss_price <= 0:
            raise ValueError(
                f"stop_loss_price deve ser positivo: {self.stop_loss_price}"
            )
        if self.position_size_usd <= 0:
            raise ValueError(
                f"position_size_usd deve ser positivo: {self.position_size_usd}"
            )
        # Invariantes de coerência SL/TP por lado
        if self.side == PositionSide.BUY:
            if self.stop_loss_price >= self.entry_price:
                raise ValueError(
                    f"BUY: stop_loss ({self.stop_loss_price}) deve ser < "
                    f"entry ({self.entry_price})"
                )
            if (self.take_profit_price is not None
                    and self.take_profit_price <= self.entry_price):
                raise ValueError(
                    f"BUY: take_profit ({self.take_profit_price}) deve ser > "
                    f"entry ({self.entry_price})"
                )
        else:  # SELL
            if self.stop_loss_price <= self.entry_price:
                raise ValueError(
                    f"SELL: stop_loss ({self.stop_loss_price}) deve ser > "
                    f"entry ({self.entry_price})"
                )
            if (self.take_profit_price is not None
                    and self.take_profit_price >= self.entry_price):
                raise ValueError(
                    f"SELL: take_profit ({self.take_profit_price}) deve ser < "
                    f"entry ({self.entry_price})"
                )


# ---------------------------------------------------------------------------
# ExitDecision — decisão imutável de saída
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExitDecision:
    """
    Resultado imutável de ExitPolicy.evaluate().

    ⚠️  ExitDecision NÃO executa nada. Apenas declara o que fazer.
    ⚠️  auto_execute_blocked é a camada de CAPABILITY do provider.
        Mesmo com False, execução real depende de gates futuros
        (ProviderStatus, ModeGuard, ambiente, integração).
    """
    should_close: bool
    reason: ExitReason
    source: ExitSource
    triggered_at_time: datetime
    requires_reduce_only: bool
    auto_execute_blocked: bool
    triggered_at_idx: Optional[int] = None
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        # Coerência interna
        if not self.should_close:
            # should_close=False só faz sentido com reason/source NONE
            if self.reason != ExitReason.NONE:
                raise ValueError(
                    f"should_close=False exige reason=NONE, "
                    f"obtido {self.reason}"
                )
            if self.source != ExitSource.NONE:
                raise ValueError(
                    f"should_close=False exige source=NONE, "
                    f"obtido {self.source}"
                )
        else:
            if self.reason == ExitReason.NONE:
                raise ValueError("should_close=True exige reason != NONE")
            if self.source == ExitSource.NONE:
                raise ValueError("should_close=True exige source != NONE")

        # Garante metadata imutável
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )

        # Garante timestamp com tz (UTC) — sem ambiguidade no audit
        if self.triggered_at_time.tzinfo is None:
            object.__setattr__(
                self,
                "triggered_at_time",
                self.triggered_at_time.replace(tzinfo=timezone.utc),
            )


def make_hold_decision(now: datetime) -> ExitDecision:
    """
    Constrói uma ExitDecision neutra (should_close=False).

    Usada quando nenhuma regra dispara. Não emite linha de audit.
    """
    return ExitDecision(
        should_close=False,
        reason=ExitReason.NONE,
        source=ExitSource.NONE,
        triggered_at_time=now,
        requires_reduce_only=False,
        auto_execute_blocked=False,
        triggered_at_idx=None,
        metadata=MappingProxyType({}),
    )
