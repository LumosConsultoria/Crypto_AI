"""
TestnetExecutorBotAdapter — FASE 6
====================================
Adapta o BybitTestnetExecutor (FASE 5) ao contrato ExecutorProtocol esperado
pelo BotEngine.

PROBLEMA QUE RESOLVE:
    - BybitTestnetExecutor.execute(risk_result, dry_run=...) tem assinatura com
      `dry_run`, enquanto o BotEngine chama executor.execute(risk_result) sem
      esse parâmetro (igual ao PaperTrader).
    - Este adapter fixa `dry_run` na construção e expõe o método
      `execute(risk_result)` compatível com ExecutorProtocol.

⚠️  SEGURANÇA — INVARIANTES:
    1. `dry_run` é OBRIGATÓRIO no construtor — SEM default. Quem integra o
       executor real ao BotEngine é forçado a decidir conscientemente entre
       simulação (dry_run=True) e envio real à testnet (dry_run=False).
    2. Este adapter NÃO afrouxa nada: a trava real continua sendo o triple-lock
       do ModeGuard dentro do BybitTestnetExecutor + RiskEngine soberano.
    3. Mainnet/live permanece BLOQUEADO — o BybitTestnetExecutor recusa
       BybitClient com use_testnet=False já no __init__ (FASE 5).
    4. NENHUMA credencial é manipulada aqui. O adapter só repassa o risk_result.

⚠️  GATE MANUAL (decisão do usuário, FASE 5/6):
    Antes de QUALQUER uso com dry_run=False contra a testnet externa, a
    validação manual da FASE 5 (key demo/testnet real via
    scripts/run_testnet_diagnostic.py --safe-check) é um pré-requisito
    OBRIGATÓRIO. A implementação offline (mocks) não substitui esse gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from crypto_trading_bot.execution.bybit_testnet_executor import (
    BybitTestnetExecutor,
    TestnetExecutionResult,
)
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger

if TYPE_CHECKING:
    from crypto_trading_bot.risk.risk_engine import RiskResult

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


class TestnetExecutorBotAdapter:
    """
    Adapta BybitTestnetExecutor ao contrato ExecutorProtocol do BotEngine.

    Satisfaz ExecutorProtocol estruturalmente: expõe `execute(risk_result)`.

    Uso (manual, via scripts — nunca default do BotEngine):
        from crypto_trading_bot.execution import (
            BybitTestnetExecutor, TestnetExecutorBotAdapter,
        )

        testnet_executor = BybitTestnetExecutor(
            client=client,                       # use_testnet=True obrigatório
            mode_guard=mode_guard,
            risk_engine=risk_engine,
            confirm_testnet_execution=True,      # triple-lock testnet
        )
        # dry_run é OBRIGATÓRIO — decisão consciente:
        adapter = TestnetExecutorBotAdapter(
            testnet_executor=testnet_executor,
            dry_run=True,                        # True=simula | False=envia real
        )

        engine = BotEngine(..., executor=adapter, paper_trader=None)
        result = engine.run_once()
    """

    def __init__(
        self,
        testnet_executor: BybitTestnetExecutor,
        dry_run: bool,
    ) -> None:
        """
        Args:
            testnet_executor: Instância de BybitTestnetExecutor (FASE 5).
            dry_run:          OBRIGATÓRIO, SEM default. Se True, o executor
                              simula sem chamar a API. Se False, envia ordem
                              REAL à Bybit testnet (após triple-lock + risco).
                              A ausência de default força a decisão explícita.

        Raises:
            TypeError:  Se testnet_executor não for BybitTestnetExecutor.
            ValueError: Se dry_run não for bool.
        """
        if not isinstance(testnet_executor, BybitTestnetExecutor):
            raise TypeError(
                "TestnetExecutorBotAdapter requer uma instância de "
                f"BybitTestnetExecutor, recebido: {type(testnet_executor).__name__}."
            )
        # dry_run precisa ser um bool explícito (defesa contra None/omitido)
        if not isinstance(dry_run, bool):
            raise ValueError(
                "TestnetExecutorBotAdapter.dry_run é OBRIGATÓRIO e deve ser bool "
                "(True=simula | False=envia ordem real à testnet). "
                f"Recebido: {dry_run!r}. Decida explicitamente."
            )

        self._executor = testnet_executor
        self._dry_run = dry_run

        _audit.info(
            f"TestnetExecutorBotAdapter inicializado | dry_run={self._dry_run}"
        )
        if not self._dry_run:
            _logger.warning(
                "⚠️  TestnetExecutorBotAdapter com dry_run=False — ordens REAIS "
                "serão enviadas à Bybit TESTNET (não live). Pré-requisito: "
                "validação manual da FASE 5 com key testnet."
            )

    def execute(self, risk_result: "RiskResult") -> TestnetExecutionResult:
        """
        Repassa o risk_result ao BybitTestnetExecutor com o dry_run fixado.

        Compatível com ExecutorProtocol — assinatura idêntica ao
        PaperTrader.execute(risk_result).

        A INVARIANTE de rejeitar risk_result.approved=False é aplicada pelo
        próprio BybitTestnetExecutor.execute (levanta ValueError).

        Args:
            risk_result: RiskResult aprovado pelo RiskEngine.

        Returns:
            TestnetExecutionResult do BybitTestnetExecutor.
        """
        return self._executor.execute(risk_result, dry_run=self._dry_run)

    @property
    def is_dry_run(self) -> bool:
        """True se o adapter está em modo simulação (não envia ordem real)."""
        return self._dry_run

    @property
    def executor(self) -> BybitTestnetExecutor:
        """BybitTestnetExecutor subjacente (read-only)."""
        return self._executor

    def get_summary(self) -> dict:
        """Resumo (delega ao executor subjacente; sem secrets)."""
        summary = dict(self._executor.get_summary())
        summary["dry_run"] = self._dry_run
        return summary

    def __repr__(self) -> str:
        return (
            f"TestnetExecutorBotAdapter(dry_run={self._dry_run} | "
            f"executor=BybitTestnetExecutor)"
        )
