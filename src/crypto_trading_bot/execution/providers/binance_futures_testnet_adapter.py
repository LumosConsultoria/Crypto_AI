"""
BinanceFuturesTestnetAdapter — FASE 8 (esqueleto dry-run)
===========================================================
Adapter ESQUELETO para Binance Futures Testnet (testnet.binancefuture.com).

⚠️  NESTA FASE: dry-run-only. SEM httpx, SEM HMAC, SEM internet.
⚠️  `dry_run=False` levanta NotImplementedError no construtor — o adapter
    NUNCA pode ser instanciado para envio real nesta fase. Aguarda fase
    própria com aprovação explícita.

⚠️  Capabilities DECLARADAS com base em docs públicas
    (https://binance-docs.github.io/apidocs/futures/en/). `confirmed=False`
    até evidência operacional. Não tira o status DRY_RUN_ONLY do registry.

⚠️  PaperTrader continua o default do BotEngine. Este adapter é OPT-IN
    no roadmap, e mesmo OPT-IN exige confirmação explícita no ModeGuard.

⚠️  Testnet NÃO garante performance futura. Mainnet permanece BLOQUEADO.

CONTRATO:
    Satisfaz ExecutorProtocol estruturalmente (método execute(risk_result)).
    Em dry_run=True: execute() retorna BinanceDryRunResult(success=True, ...).
    Em dry_run=False: construtor levanta NotImplementedError (defesa-em-profundidade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger

if TYPE_CHECKING:
    from crypto_trading_bot.risk.risk_engine import RiskResult

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


@dataclass(frozen=True)
class BinanceDryRunResult:
    """Resultado imutável do adapter dry-run. SEM credenciais, SEM endpoint."""
    success: bool
    reason: str
    dry_run: bool = True
    provider_id: str = "binance_futures_testnet"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Campos PARALELOS aos demais executors (PaperExecutionResult / TestnetExecutionResult):
    # operation define qual operação foi simulada.
    operation: str = "place_order"

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "provider_id": self.provider_id,
            "operation": self.operation,
            "timestamp": self.timestamp.isoformat(),
        }


class BinanceFuturesTestnetAdapter:
    """
    Adapter ESQUELETO para Binance Futures Testnet.

    Uso (DRY-RUN apenas, FASE 8):
        adapter = BinanceFuturesTestnetAdapter(dry_run=True)
        # adapter.capability descreve o que está DECLARADO (não confirmado).
        # adapter.execute(risk_result) retorna BinanceDryRunResult(success=True).

    Tentativa real (BLOQUEADA nesta fase):
        BinanceFuturesTestnetAdapter(dry_run=False)
        # → NotImplementedError
    """

    PROVIDER_ID = "binance_futures_testnet"

    def __init__(self, dry_run: bool) -> None:
        """
        Args:
            dry_run: OBRIGATÓRIO, SEM default. Deve ser bool.
                     - True  → adapter simula; execute() retorna sucesso fake.
                     - False → levanta NotImplementedError IMEDIATAMENTE.
        """
        if not isinstance(dry_run, bool):
            raise ValueError(
                "BinanceFuturesTestnetAdapter.dry_run é OBRIGATÓRIO e deve ser bool. "
                f"Recebido: {dry_run!r}. Decida explicitamente."
            )
        if not dry_run:
            raise NotImplementedError(
                "BinanceFuturesTestnetAdapter: integração real (cliente HTTP + HMAC) "
                "NÃO está implementada na FASE 8. dry_run=False está BLOQUEADO. "
                "Esta integração fica em fase própria, com aprovação explícita."
            )

        self._dry_run = dry_run
        self._capability = ProviderCapability(
            provider_id=self.PROVIDER_ID,
            supports_market_order=True,
            supports_limit_order=True,
            supports_stop_loss=True,
            supports_take_profit=True,
            supports_reduce_only=True,
            supports_leverage_api=True,
            supports_positions_query=True,
            supports_balance_query=True,
            supports_cancel_order=True,
            is_demo_environment=True,
            is_live_environment=False,
            documented_assets=("BTCUSDT",),
            confirmed=False,
            confirmation_source="",
            notes=(
                "Capabilities DECLARADAS com base em docs públicas de "
                "testnet.binancefuture.com. confirmed=False até evidência "
                "operacional. Adapter é esqueleto — execute() em dry_run=True "
                "simula sem chamada HTTP. dry_run=False não é permitido."
            ),
        )
        _audit.info(
            f"BinanceFuturesTestnetAdapter inicializado | dry_run={self._dry_run} | "
            f"provider_id={self.PROVIDER_ID}"
        )

    # ------------------------------------------------------------------ contrato

    def execute(self, risk_result: "RiskResult") -> BinanceDryRunResult:
        """
        Simula a execução de uma ordem aprovada pelo RiskEngine.

        INVARIANTE: rejeita risk_result.approved=False (igual aos demais executors).

        ⚠️  ESTA FASE: apenas dry-run. Nenhuma chamada HTTP é feita.
        """
        if not risk_result.approved:
            raise ValueError(
                "BinanceFuturesTestnetAdapter.execute REJEITA risk_result não aprovado. "
                "INVARIANTE: o fluxo DEVE passar pelo RiskEngine antes."
            )

        signal = risk_result.signal
        _logger.info(
            f"BinanceFuturesTestnetAdapter.execute: DRY-RUN | "
            f"symbol={signal.symbol} | side={signal.side.value} | "
            f"size_usd={signal.position_size_usd}"
        )
        return BinanceDryRunResult(
            success=True,
            operation="place_order",
            reason=(
                f"dry_run: BinanceFuturesTestnetAdapter simulou ordem "
                f"symbol={signal.symbol} side={signal.side.value} "
                f"size_usd={signal.position_size_usd}. Nenhuma chamada HTTP feita. "
                "Integração real pendente de fase própria."
            ),
        )

    # ------------------------------------------------------------------ propriedades

    @property
    def is_dry_run(self) -> bool:
        return self._dry_run

    @property
    def provider_id(self) -> str:
        return self.PROVIDER_ID

    @property
    def capability(self) -> ProviderCapability:
        return self._capability

    def get_summary(self) -> dict:
        """Resumo para audit/log. SEM credenciais."""
        return {
            "provider_id": self.PROVIDER_ID,
            "dry_run": self._dry_run,
            "capability": self._capability.to_dict(),
        }

    def __repr__(self) -> str:
        return (
            f"BinanceFuturesTestnetAdapter(provider_id={self.PROVIDER_ID}, "
            f"dry_run={self._dry_run}, capability.confirmed={self._capability.confirmed})"
        )
