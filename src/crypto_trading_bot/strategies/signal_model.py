"""
StrategySignal — Modelo Padronizado de Sinal de Estratégia
===========================================================
Define a linguagem comum entre estratégia, BotEngine e executor.

⚠️  REGRAS DE DESIGN:
    1. Estratégias expressam sua decisão como BUY, SELL ou HOLD.
    2. HOLD significa "avaliou os dados e decidiu não operar agora".
    3. None no generate_signal() significa "estratégia inativa ou dados inválidos".
    4. HOLD/NO_TRADE NUNCA é enviado para execução.
    5. Apenas BUY/SELL com stop_loss definido passam ao RiskEngine.
    6. StrategySignal → to_trading_signal() → RiskEngine → PaperTrader.

Fluxo garantido pelo BotEngine:
    strategy.evaluate(features)
        → StrategySignal(HOLD)   → ciclo encerrado com segurança
        → StrategySignal(BUY)    → to_trading_signal() → RiskEngine → execução (se aprovado)
        → StrategySignal(SELL)   → to_trading_signal() → RiskEngine → execução (se aprovado)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from crypto_trading_bot.risk.risk_engine import TradingSignal


# ---------------------------------------------------------------------------
# Enum de Ação
# ---------------------------------------------------------------------------

class StrategyAction(str, Enum):
    """
    Ação padronizada produzida por uma estratégia.

    BUY:   Estratégia quer abrir posição longa.
    SELL:  Estratégia quer abrir posição curta / encerrar compra.
    HOLD:  Estratégia avaliou os dados e decidiu não operar neste ciclo.
           Isso é diferente de "sem dados" — é uma decisão consciente.

    HOLD nunca é enviado para execução. Só BUY e SELL chegam ao RiskEngine.
    """
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


# ---------------------------------------------------------------------------
# StrategySignal
# ---------------------------------------------------------------------------

@dataclass
class StrategySignal:
    """
    Sinal produzido por uma estratégia após avaliar os dados de mercado.

    Representa uma decisão padronizada: BUY, SELL ou HOLD.

    Para ações BUY/SELL, os campos de preço e risco são obrigatórios.
    Para HOLD, apenas action, symbol e strategy_name são relevantes.

    O BotEngine usa este modelo para:
    - Registrar a decisão no BotCycleResult
    - Decidir se deve chamar o RiskEngine
    - Garantir que HOLD jamais seja executado

    Atributos:
        action:            BUY, SELL ou HOLD (sempre preenchido)
        symbol:            Símbolo do ativo (ex: "BTCUSDT")
        strategy_name:     Nome da estratégia que gerou o sinal
        entry_price:       Preço pretendido de entrada (0.0 para HOLD)
        stop_loss_price:   Stop loss — obrigatório para BUY/SELL (0.0 para HOLD)
        take_profit_price: Alvo de lucro (None se não definido)
        position_size_usd: Tamanho da posição em USD (0.0 para HOLD)
        leverage:          Alavancagem desejada (1.0 = sem alavancagem)
        timestamp:         Momento de geração do sinal
        metadata:          Dados adicionais para auditoria
        reason:            Motivo do HOLD (para log — não usado em BUY/SELL)
    """

    action: StrategyAction
    symbol: str
    strategy_name: str

    # Parâmetros de trade (relevantes apenas para BUY/SELL)
    entry_price: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: Optional[float] = None
    position_size_usd: float = 0.0
    leverage: float = 1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""  # motivo do HOLD (para log)

    # -----------------------------------------------------------------------
    # Propriedades
    # -----------------------------------------------------------------------

    @property
    def is_actionable(self) -> bool:
        """
        True se a ação é BUY ou SELL (ou seja, deve ir ao RiskEngine).

        False se for HOLD — nunca deve ser enviado para execução.
        """
        return self.action in (StrategyAction.BUY, StrategyAction.SELL)

    @property
    def stop_loss_pct(self) -> float:
        """Percentual de stop loss em relação ao entry_price."""
        if self.entry_price <= 0:
            return 0.0
        return abs(self.entry_price - self.stop_loss_price) / self.entry_price

    # -----------------------------------------------------------------------
    # Conversão
    # -----------------------------------------------------------------------

    def to_trading_signal(self) -> "TradingSignal":
        """
        Converte este StrategySignal para TradingSignal para envio ao RiskEngine.

        ⚠️  Só pode ser chamado se is_actionable == True.
            HOLD não pode ser convertido.

        Returns:
            TradingSignal pronto para validação pelo RiskEngine.

        Raises:
            ValueError: Se action == HOLD ou parâmetros de trade inválidos.
        """
        if not self.is_actionable:
            raise ValueError(
                f"StrategySignal com action='{self.action.value}' não pode ser convertido "
                f"para TradingSignal. Apenas BUY e SELL são executáveis. "
                f"HOLD nunca deve chegar ao RiskEngine."
            )
        if self.entry_price <= 0:
            raise ValueError(
                f"entry_price inválido para conversão: {self.entry_price}"
            )
        if self.stop_loss_price <= 0:
            raise ValueError(
                f"stop_loss_price inválido para conversão: {self.stop_loss_price}"
            )

        # Import local para evitar dependência circular
        from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal

        side = OrderSide.BUY if self.action == StrategyAction.BUY else OrderSide.SELL

        return TradingSignal(
            symbol=self.symbol,
            side=side,
            entry_price=self.entry_price,
            stop_loss_price=self.stop_loss_price,
            take_profit_price=self.take_profit_price,
            position_size_usd=self.position_size_usd,
            leverage=self.leverage,
            strategy_name=self.strategy_name,
            timestamp=self.timestamp,
            metadata=self.metadata,
        )

    # -----------------------------------------------------------------------
    # Construtores convenientes
    # -----------------------------------------------------------------------

    @classmethod
    def hold(cls, symbol: str, strategy_name: str, reason: str = "") -> "StrategySignal":
        """Cria um sinal HOLD de forma conveniente."""
        return cls(
            action=StrategyAction.HOLD,
            symbol=symbol,
            strategy_name=strategy_name,
            reason=reason,
        )

    @classmethod
    def buy(
        cls,
        symbol: str,
        strategy_name: str,
        entry_price: float,
        stop_loss_price: float,
        position_size_usd: float,
        take_profit_price: Optional[float] = None,
        leverage: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "StrategySignal":
        """Cria um sinal BUY de forma conveniente."""
        return cls(
            action=StrategyAction.BUY,
            symbol=symbol,
            strategy_name=strategy_name,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usd=position_size_usd,
            leverage=leverage,
            metadata=metadata or {},
        )

    @classmethod
    def sell(
        cls,
        symbol: str,
        strategy_name: str,
        entry_price: float,
        stop_loss_price: float,
        position_size_usd: float,
        take_profit_price: Optional[float] = None,
        leverage: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "StrategySignal":
        """Cria um sinal SELL de forma conveniente."""
        return cls(
            action=StrategyAction.SELL,
            symbol=symbol,
            strategy_name=strategy_name,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usd=position_size_usd,
            leverage=leverage,
            metadata=metadata or {},
        )

    def __repr__(self) -> str:
        if self.is_actionable:
            return (
                f"StrategySignal({self.action.value.upper()} "
                f"{self.symbol} "
                f"entry={self.entry_price} "
                f"stop={self.stop_loss_price} "
                f"size={self.position_size_usd})"
            )
        return (
            f"StrategySignal(HOLD "
            f"symbol={self.symbol} "
            f"strategy={self.strategy_name}"
            f"{f' reason={self.reason!r}' if self.reason else ''})"
        )
