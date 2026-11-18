"""
HyroTraderCleoAdapter — FASE 8 (UNCONFIRMED — mecanismo desconhecido)
========================================================================
Adapter ESQUELETO para CLEO (plataforma HyroTrader).

⚠️  CRÍTICO: o MECANISMO de integração CLEO (API REST/WS, SDK, webhook
    TradingView, bridge MT4/MT5, FIX, arquivo, UI automation) AINDA NÃO
    FOI CONFIRMADO. Ver docs/hyrotrader_cleo.md para perguntas pendentes.

⚠️  Sem essa confirmação, este adapter:
    1. Capabilities TODAS False, `confirmed=False`.
    2. `dry_run=False` levanta NotImplementedError no construtor.
    3. `execute(risk_result)` em dry_run=True retorna SEMPRE
       `success=False` com mensagem explicando que o mecanismo é
       desconhecido. O bot NUNCA acredita que CLEO executou.

⚠️  GATE ADICIONAL (ToS):
    Prop firms tipicamente PROÍBEM bots no painel de execução. Antes de
    qualquer execução real em CLEO, é obrigatório validar:
    (a) automação permitida pelos ToS de HyroTrader;
    (b) modo demo/free trial acessível à conta;
    (c) mecanismo técnico de integração existente.

⚠️  HyroTrader Free Trial / Challenge / Demo NÃO garante performance futura.
⚠️  Mainnet/live permanece BLOQUEADO. assert_live_allowed intocado.

CONTRATO:
    Satisfaz ExecutorProtocol estruturalmente (método execute(risk_result)).
    Em dry_run=True: execute() retorna CleoDryRunResult(success=False, ...).
    Em dry_run=False: construtor levanta NotImplementedError.
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


CLEO_MECHANISM_UNDEFINED_REASON = (
    "cleo-mechanism-undefined: o mecanismo de integração CLEO (API REST/WS, SDK, "
    "webhook TradingView, bridge MT4/MT5, FIX, arquivo, UI automation) ainda "
    "NÃO foi confirmado. Ver docs/hyrotrader_cleo.md para perguntas pendentes. "
    "Nenhuma execução real é possível até resposta + nova aprovação explícita."
)


@dataclass(frozen=True)
class CleoDryRunResult:
    """Resultado imutável do adapter CLEO. SEMPRE success=False nesta fase."""
    success: bool
    reason: str
    dry_run: bool = True
    provider_id: str = "hyrotrader_cleo_demo"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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


class HyroTraderCleoAdapter:
    """
    Adapter ESQUELETO para HyroTrader CLEO.

    Uso (apenas dry-run, FASE 8):
        adapter = HyroTraderCleoAdapter(dry_run=True)
        # adapter.capability tem TODOS os flags False, confirmed=False.
        # adapter.execute(risk_result) retorna CleoDryRunResult(success=False)
        # explicando que o mecanismo não foi confirmado.

    Tentativa real (BLOQUEADA):
        HyroTraderCleoAdapter(dry_run=False)
        # → NotImplementedError ("cleo-mechanism-undefined: ...")
    """

    PROVIDER_ID = "hyrotrader_cleo_demo"

    def __init__(self, dry_run: bool) -> None:
        """
        Args:
            dry_run: OBRIGATÓRIO, SEM default. Deve ser bool.
                     - True  → adapter "funciona" mas execute() sempre falha
                              com cleo-mechanism-undefined.
                     - False → levanta NotImplementedError IMEDIATAMENTE.
        """
        if not isinstance(dry_run, bool):
            raise ValueError(
                "HyroTraderCleoAdapter.dry_run é OBRIGATÓRIO e deve ser bool. "
                f"Recebido: {dry_run!r}. Decida explicitamente."
            )
        if not dry_run:
            raise NotImplementedError(
                f"HyroTraderCleoAdapter: {CLEO_MECHANISM_UNDEFINED_REASON} "
                "dry_run=False está BLOQUEADO até confirmação do mecanismo."
            )

        self._dry_run = dry_run
        self._capability = ProviderCapability(
            provider_id=self.PROVIDER_ID,
            supports_market_order=False,
            supports_limit_order=False,
            supports_stop_loss=False,
            supports_take_profit=False,
            supports_reduce_only=False,
            supports_leverage_api=False,
            supports_positions_query=False,
            supports_balance_query=False,
            supports_cancel_order=False,
            is_demo_environment=False,
            is_live_environment=False,
            documented_assets=(),
            confirmed=False,
            confirmation_source="",
            notes=(
                "Mecanismo de integração CLEO não confirmado. Todas as "
                "capacidades False até resposta às perguntas em "
                "docs/hyrotrader_cleo.md. Inclui validação obrigatória dos ToS "
                "HyroTrader sobre AUTOMAÇÃO antes de qualquer execução real."
            ),
        )
        _audit.info(
            f"HyroTraderCleoAdapter inicializado | dry_run={self._dry_run} | "
            f"provider_id={self.PROVIDER_ID} | status=UNCONFIRMED"
        )

    # ------------------------------------------------------------------ contrato

    def execute(self, risk_result: "RiskResult") -> CleoDryRunResult:
        """
        Em qualquer cenário (dry_run=True), retorna success=False explicando
        que o mecanismo de integração CLEO ainda NÃO foi confirmado.

        INVARIANTE: rejeita risk_result.approved=False (igual aos demais executors)
        ANTES de qualquer outra checagem.

        ⚠️  Por design, o bot NUNCA acredita que CLEO executou nesta fase.
        """
        if not risk_result.approved:
            raise ValueError(
                "HyroTraderCleoAdapter.execute REJEITA risk_result não aprovado. "
                "INVARIANTE: o fluxo DEVE passar pelo RiskEngine antes."
            )

        _logger.warning(
            f"HyroTraderCleoAdapter.execute: BLOQUEADO — mecanismo CLEO não "
            f"confirmado. symbol={risk_result.signal.symbol}"
        )
        return CleoDryRunResult(
            success=False,
            operation="place_order",
            reason=CLEO_MECHANISM_UNDEFINED_REASON,
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
        """Resumo para audit/log. SEM credenciais, SEM URL."""
        return {
            "provider_id": self.PROVIDER_ID,
            "dry_run": self._dry_run,
            "capability": self._capability.to_dict(),
            "mechanism_confirmed": False,
        }

    def __repr__(self) -> str:
        return (
            f"HyroTraderCleoAdapter(provider_id={self.PROVIDER_ID}, "
            f"dry_run={self._dry_run}, mechanism_confirmed=False)"
        )
