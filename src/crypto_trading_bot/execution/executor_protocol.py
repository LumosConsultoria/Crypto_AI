"""
ExecutorProtocol — FASE 6
==========================
Contrato estrutural (typing.Protocol) que qualquer executor injetável no
BotEngine deve satisfazer.

⚠️  Tipagem ESTRUTURAL (duck typing verificado estaticamente):
    - PaperTrader e TestnetExecutorBotAdapter satisfazem este Protocol SEM
      herança explícita. Nada em src/ precisa herdar desta classe.
    - O Protocol existe para documentar o contrato e permitir checagem por
      mypy/pyright sem acoplar implementações.

CONTRATO MÍNIMO:
    execute(risk_result) -> Any
        Recebe um RiskResult JÁ aprovado pelo RiskEngine e devolve um
        resultado de execução (PaperExecutionResult, TestnetExecutionResult,
        etc.). A INVARIANTE de só executar sinais aprovados pertence a cada
        executor concreto — o BotEngine valida no RiskEngine antes de chamar.

⚠️  Este Protocol NÃO afrouxa nenhuma trava de segurança:
    - Não substitui ModeGuard.
    - Não substitui RiskEngine.
    - Não habilita live/mainnet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from crypto_trading_bot.risk.risk_engine import RiskResult


@runtime_checkable
class ExecutorProtocol(Protocol):
    """
    Contrato estrutural para executores usados pelo BotEngine.

    Qualquer objeto com um método `execute(risk_result) -> Any` satisfaz este
    Protocol. Usado para tipar `BotEngine(executor=...)` sem acoplar o engine
    a uma implementação concreta.

    Implementações conhecidas que satisfazem o contrato:
        - PaperTrader.execute(risk_result) -> PaperExecutionResult
        - TestnetExecutorBotAdapter.execute(risk_result) -> TestnetExecutionResult

    ⚠️  `runtime_checkable` permite `isinstance(obj, ExecutorProtocol)`, mas a
        verificação em runtime confere APENAS a presença do método `execute`,
        não sua assinatura. Use para asserts defensivos, não como trava de
        segurança (as travas reais são ModeGuard + RiskEngine).
    """

    def execute(self, risk_result: "RiskResult") -> Any:
        """
        Executa um sinal JÁ aprovado pelo RiskEngine.

        Args:
            risk_result: RiskResult com approved=True. O executor concreto
                         DEVE rejeitar approved=False (invariante própria).

        Returns:
            Resultado de execução específico do executor (estrutura livre).
        """
        ...
