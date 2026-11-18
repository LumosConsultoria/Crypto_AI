"""
BotCycleResult — Resultado Padronizado de um Ciclo do BotEngine
================================================================
Registra todo o estado de um ciclo de decisão para auditoria e diagnóstico.

Cada chamada a BotEngine.run_once() retorna um BotCycleResult.

Campos obrigatórios (per especificação):
    - symbol:          Ativo avaliado no ciclo
    - action:          O que aconteceu neste ciclo
    - risk_approved:   O RiskEngine aprovou o sinal?
    - executed:        O trade foi executado no PaperTrader?
    - reason:          Motivo detalhado (para log e auditoria)
    - timestamp:       Quando o ciclo ocorreu
    - strategy_name:   Nome da estratégia usada

Actions possíveis:
    "pending"          — ciclo ainda em execução (estado inicial)
    "safety_blocked"   — ModeGuard bloqueou
    "no_candles"       — MarketData não retornou candles
    "insufficient_data"— FeatureEngine: dados insuficientes
    "strategy_inactive"— Estratégia não está em estado RUNNING
    "hold"             — Estratégia avaliou e decidiu HOLD/NO_TRADE
    "risk_blocked"     — RiskEngine bloqueou o sinal
    "executed"         — Trade simulado executado com sucesso
    "error"            — Erro inesperado no ciclo
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from crypto_trading_bot.strategies.signal_model import StrategySignal
    from crypto_trading_bot.risk.risk_engine import RiskResult


# ---------------------------------------------------------------------------
# BotCycleResult
# ---------------------------------------------------------------------------

@dataclass
class BotCycleResult:
    """
    Resultado completo de um ciclo de decisão do BotEngine.

    Contém todo o rastreamento necessário para auditoria:
    o que aconteceu, por que, qual estratégia decidiu, o RiskEngine aprovou?

    ⚠️  risk_approved=False e executed=False são os estados seguros padrão.
        Apenas um ciclo que passou por RiskEngine E PaperTrader tem
        risk_approved=True E executed=True.

    Atributos:
        cycle:           Número sequencial do ciclo
        symbol:          Ativo avaliado
        mode:            Modo de operação (paper/testnet/live)
        strategy_name:   Nome da estratégia que avaliou os dados
        action:          O que aconteceu neste ciclo (ver docstring do módulo)
        risk_approved:   True apenas se RiskEngine aprovou
        executed:        True apenas se PaperTrader executou
        reason:          Motivo detalhado (bloqueio, hold, erro, etc.)
        timestamp:       Timestamp do início do ciclo
        n_candles:       Quantos candles foram processados
        strategy_signal: StrategySignal retornado pela estratégia (se gerou)
        risk_result:     RiskResult do RiskEngine (se chegou lá)
        trade:           PaperTrade executado (se executed=True) — legado
        executor_result: Resultado bruto do executor injetado (FASE 6) —
                         PaperExecutionResult ou TestnetExecutionResult
    """

    # Campos obrigatórios
    cycle: int
    symbol: str
    mode: str
    strategy_name: str
    action: str = "pending"

    # Invariante de segurança: False por padrão
    risk_approved: bool = False
    executed: bool = False

    # Rastreamento
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    n_candles: int = 0

    # Objetos completos para auditoria (preenchidos conforme o ciclo avança)
    strategy_signal: Optional[Any] = None   # StrategySignal
    risk_result: Optional[Any] = None       # RiskResult
    trade: Optional[Any] = None             # PaperTrade (legado — preservado)

    # FASE 6 — Resultado do executor injetado (PaperExecutionResult OU
    # TestnetExecutionResult OU outro que satisfaça ExecutorProtocol).
    # Campo PARALELO a `trade`: não substitui o legado. Quando o executor é o
    # PaperTrader, `trade` continua preenchido com o PaperTrade (retrocompat).
    executor_result: Optional[Any] = None   # PaperExecutionResult | TestnetExecutionResult | ...

    # FASE 8 — Snapshot read-only do provider configurado (do ProviderRegistry).
    # Campo PARALELO opcional. Não substitui executor_result nem trade.
    # Populado pelo BotEngine no início do ciclo se houver provider_id válido
    # e registry disponível. None se não houver. NUNCA contém credenciais.
    provider_snapshot: Optional[Any] = None   # dict sanitizado (provider_id, status, capability)

    # -----------------------------------------------------------------------
    # Propriedades de conveniência
    # -----------------------------------------------------------------------

    @property
    def was_safe(self) -> bool:
        """True se o ciclo terminou em estado seguro (sem execução indevida)."""
        # Um ciclo é seguro se:
        # - Não foi executado, OU
        # - Foi executado com aprovação explícita do RiskEngine
        return (not self.executed) or (self.executed and self.risk_approved)

    @property
    def trade_executed(self) -> bool:
        """True se um trade simulado foi executado com todas as verificações."""
        return self.executed and self.risk_approved and self.action == "executed"

    @property
    def was_hold(self) -> bool:
        """True se a estratégia avaliou os dados e decidiu HOLD."""
        return self.action == "hold"

    @property
    def was_blocked_by_risk(self) -> bool:
        """True se o RiskEngine bloqueou o sinal."""
        return self.action == "risk_blocked"

    def to_dict(self) -> dict:
        """
        Serializa o resultado para um dicionário (para log, JSON, auditoria).

        Otimizado para logging — omite campos pesados (signal, trade completos).
        """
        return {
            "cycle": self.cycle,
            "symbol": self.symbol,
            "mode": self.mode,
            "strategy_name": self.strategy_name,
            "action": self.action,
            "risk_approved": self.risk_approved,
            "executed": self.executed,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "n_candles": self.n_candles,
            "has_signal": self.strategy_signal is not None,
            "signal_action": (
                self.strategy_signal.action.value
                if self.strategy_signal is not None
                else None
            ),
            "risk_block_reason": (
                self.risk_result.block_reason.value
                if (self.risk_result is not None and self.risk_result.block_reason)
                else None
            ),
            "was_safe": self.was_safe,
        }

    def __repr__(self) -> str:
        status = "✅" if self.trade_executed else ("⛔" if self.was_blocked_by_risk else "⏸")
        return (
            f"BotCycleResult("
            f"{status} "
            f"cycle={self.cycle} | "
            f"action={self.action} | "
            f"risk={self.risk_approved} | "
            f"exec={self.executed} | "
            f"symbol={self.symbol})"
        )
