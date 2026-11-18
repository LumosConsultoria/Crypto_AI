"""
TealstreetCliGatewayAdapter — FASE 9B (esqueleto dry-run-only)
================================================================
Adapter EXPERIMENTAL para o gateway CLI + webhooks do Tealstreet.

⚠️  STATUS NO REGISTRY: DRY_RUN_ONLY. NUNCA executa ordem real nesta fase.
⚠️  Sem subprocess. Sem httpx/requests. Sem rede. Sem secrets em log/output.
⚠️  `dry_run=False` levanta NotImplementedError no construtor.
⚠️  `simulation_mode` na config DEVE ser True; outros valores são rejeitados.
⚠️  Uso com HyroTrader depende dos ToS / regras da prop firm. Esta camada NÃO
    valida ToS — apenas monta comandos e payloads localmente para auditoria.
⚠️  Tealstreet/HyroTrader/Free Trial NÃO garante performance futura.

CONTRATO:
    Satisfaz ExecutorProtocol estruturalmente (execute(risk_result)).
    Em dry_run=True: execute() retorna TealstreetDryRunResult com command
    + hook_payload MONTADOS mas NUNCA executados/enviados. Reason explica
    o que foi montado e o que faltou de config.

CONFIG:
    TealstreetGatewayConfig aceita APENAS valores não-sensíveis (caminho do
    CLI, account_id, hook_url, hook_id). Token opcional como SecretStr;
    NUNCA exposto em to_dict/repr/result. Audit_snapshot mostra somente
    flags booleanas de "configurado: sim/não" e "secret presente: sim/não".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Mapping, Optional, Tuple

from pydantic import SecretStr

from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger

if TYPE_CHECKING:
    from crypto_trading_bot.risk.risk_engine import RiskResult

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)

# Marker token público (NUNCA contém valor real de secret).
_REDACTED = "***REDACTED***"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TealstreetGatewayConfig:
    """
    Configuração local do gateway Tealstreet.

    ⚠️  NÃO armazena URLs com token embutido. NÃO retorna `hook_secret` em
        to_dict(). simulation_mode DEVE ser True nesta fase.

    Atributos:
        cli_path:        caminho do executável Tealstreet (opcional; sem secret).
        account_id:      identificador de conta (opcional; não-secret).
        hook_url:        URL pública do webhook (opcional; SEM token na URL).
        hook_id:         identificador do hook (opcional; não-secret).
        hook_secret:     SecretStr opcional. NUNCA exposto.
        simulation_mode: OBRIGATÓRIO True. Outros valores levantam ValueError.
    """
    cli_path: Optional[str] = None
    account_id: Optional[str] = None
    hook_url: Optional[str] = None
    hook_id: Optional[str] = None
    hook_secret: Optional[SecretStr] = None
    simulation_mode: bool = True

    def __post_init__(self) -> None:
        if self.simulation_mode is not True:
            raise ValueError(
                "TealstreetGatewayConfig.simulation_mode DEVE ser True nesta fase. "
                "Outros valores estão BLOQUEADOS — Tealstreet adapter é dry-run-only."
            )
        # Defesa-em-profundidade: tipos válidos para campos não-secret.
        for name in ("cli_path", "account_id", "hook_url", "hook_id"):
            v = getattr(self, name)
            if v is not None and not isinstance(v, str):
                raise ValueError(
                    f"TealstreetGatewayConfig.{name} deve ser str ou None. "
                    f"Recebido: {type(v).__name__}."
                )
        if self.hook_secret is not None and not isinstance(self.hook_secret, SecretStr):
            raise ValueError(
                "TealstreetGatewayConfig.hook_secret deve ser SecretStr ou None. "
                "Nunca passe string crua — use SecretStr('valor')."
            )

    def to_dict(self) -> dict:
        """Snapshot SANITIZADO. NUNCA inclui valor de hook_secret nem hook_url completa."""
        return {
            "cli_configured": bool(self.cli_path),
            "account_configured": bool(self.account_id),
            "hook_url_configured": bool(self.hook_url),
            "hook_id_configured": bool(self.hook_id),
            "hook_secret_present": self.hook_secret is not None,
            "simulation_mode": self.simulation_mode,
        }


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TealstreetDryRunResult:
    """Resultado imutável do adapter dry-run. SEM secrets."""
    success: bool
    reason: str
    dry_run: bool = True
    provider_id: str = "tealstreet_cli_gateway"
    operation: str = "place_order"
    command: Optional[Tuple[str, ...]] = None       # comando montado, NÃO executado
    hook_payload: Optional[Mapping[str, Any]] = None  # payload montado, NÃO enviado
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        """Snapshot sanitizado. Payload pode ser inspecionado (sem secret value)."""
        return {
            "success": self.success,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "provider_id": self.provider_id,
            "operation": self.operation,
            "command": list(self.command) if self.command is not None else None,
            "hook_payload": dict(self.hook_payload) if self.hook_payload is not None else None,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class TealstreetCliGatewayAdapter:
    """
    Adapter ESQUELETO para Tealstreet CLI + Webhook Gateway.

    Uso (DRY-RUN apenas, FASE 9B):
        cfg = TealstreetGatewayConfig(
            cli_path="/opt/tealstreet/bin/tealstreet",
            account_id="demo_account_001",
            hook_url="https://hook.example/abc",
            hook_id="abc",
            simulation_mode=True,
        )
        a = TealstreetCliGatewayAdapter(dry_run=True, config=cfg)
        # a.execute(risk_result) retorna TealstreetDryRunResult com command e
        # hook_payload MONTADOS, mas sem executar nem enviar nada.

    Tentativa real (BLOQUEADA):
        TealstreetCliGatewayAdapter(dry_run=False, config=cfg)
        # → NotImplementedError
    """

    PROVIDER_ID = "tealstreet_cli_gateway"

    def __init__(
        self,
        *,
        dry_run: bool,
        config: TealstreetGatewayConfig,
    ) -> None:
        if not isinstance(dry_run, bool):
            raise ValueError(
                "TealstreetCliGatewayAdapter.dry_run é OBRIGATÓRIO e deve ser bool. "
                f"Recebido: {dry_run!r}. Decida explicitamente."
            )
        if not dry_run:
            raise NotImplementedError(
                "TealstreetCliGatewayAdapter: integração real (subprocess CLI + HTTP "
                "webhook) NÃO está implementada na FASE 9B. dry_run=False está "
                "BLOQUEADO. Esta integração permanece DRY_RUN_ONLY até aprovação "
                "explícita futura — uso real depende dos ToS/regras HyroTrader."
            )
        if not isinstance(config, TealstreetGatewayConfig):
            raise TypeError(
                "TealstreetCliGatewayAdapter.config deve ser TealstreetGatewayConfig. "
                f"Recebido: {type(config).__name__}."
            )

        self._dry_run = dry_run
        self._config = config
        self._capability = ProviderCapability(
            provider_id=self.PROVIDER_ID,
            supports_market_order=True,
            supports_limit_order=True,
            supports_stop_loss=True,
            supports_take_profit=True,
            supports_reduce_only=False,        # Não confirmado no gateway
            supports_leverage_api=False,       # Leverage é conta HyroTrader
            supports_positions_query=False,    # Não confirmado
            supports_balance_query=False,      # Não confirmado
            supports_cancel_order=True,        # CLI tipicamente suporta cancel
            supports_webhook=True,             # webhook é mecanismo central
            supports_cli=True,                 # CLI é mecanismo central
            is_demo_environment=True,
            is_live_environment=False,
            documented_assets=("BTCUSDT",),
            confirmed=False,                   # nunca confirmed nesta fase
            confirmation_source="",
            notes=(
                "Experimental. Tealstreet oferece CLI + webhooks + simulation mode. "
                "Esta camada apenas MONTA comandos/payloads — nunca executa subprocess "
                "nem envia HTTP. Uso real com HyroTrader depende de ToS/regras da prop "
                "firm. NÃO garante performance futura."
            ),
        )
        _audit.info(
            f"TealstreetCliGatewayAdapter inicializado | dry_run={self._dry_run} | "
            f"provider_id={self.PROVIDER_ID} | "
            f"cli_configured={bool(config.cli_path)} | "
            f"account_configured={bool(config.account_id)} | "
            f"hook_configured={bool(config.hook_url) or bool(config.hook_id)} | "
            f"hook_secret_present={config.hook_secret is not None}"
        )

    # ------------------------------------------------------------------ builders

    def build_market_command(self, signal) -> Optional[Tuple[str, ...]]:
        """
        Monta os argumentos do CLI Tealstreet para uma ordem MARKET.

        ⚠️  Sintaxe é PROVISÓRIA — exata depende da doc oficial Tealstreet.
        ⚠️  `--simulation` é OBRIGATÓRIO. Nunca executa subprocess.
        ⚠️  Retorna None se `cli_path` não está configurado (mensagem segura
            via reason no execute()).

        Args:
            signal: TradingSignal com symbol, side, position_size_usd, entry_price.

        Returns:
            Tupla read-only de strings (args do CLI) ou None se cli_path ausente.
        """
        if not self._config.cli_path:
            return None

        # qty = position_size_usd / entry_price (mesmo padrão dos outros executors)
        try:
            qty = float(signal.position_size_usd) / float(signal.entry_price)
        except (TypeError, ValueError, ZeroDivisionError):
            qty = 0.0

        account = self._config.account_id or "__account_unset__"
        return (
            self._config.cli_path,
            "place",
            "--simulation",            # SEMPRE simulation; defesa-em-profundidade
            "--account", account,
            "--symbol", str(signal.symbol),
            "--side", str(signal.side.value),
            "--type", "market",
            "--qty", f"{qty:.8f}",
        )

    def build_hook_payload(self, signal) -> Optional[Mapping[str, Any]]:
        """
        Monta o payload do webhook Tealstreet para envio externo.

        ⚠️  hook_secret NUNCA é incluído. Em vez disso, payload inclui
            `hook_secret_present: bool` (boolean), permitindo ao caller
            decidir o transporte sem expor o valor.
        ⚠️  Retorna None se hook não está configurado (mensagem segura
            via reason no execute()).

        Returns:
            Dict (payload) read-only conceptual ou None se hook ausente.
        """
        if not self._config.hook_url and not self._config.hook_id:
            return None

        return {
            "hook_id": self._config.hook_id or "__hook_id_unset__",
            "simulation": True,                # SEMPRE simulation no payload
            "symbol": str(signal.symbol),
            "side": str(signal.side.value),
            "size_usd": float(signal.position_size_usd),
            "entry_price": float(signal.entry_price),
            "stop_loss": (
                float(signal.stop_loss_price)
                if signal.stop_loss_price is not None else None
            ),
            "take_profit": (
                float(signal.take_profit_price)
                if signal.take_profit_price is not None else None
            ),
            "hook_secret_present": self._config.hook_secret is not None,
            "comment": "dry-run mounted; not sent",
        }

    # ------------------------------------------------------------------ contrato

    def execute(self, risk_result: "RiskResult") -> TealstreetDryRunResult:
        """
        Monta o comando CLI + payload do webhook SEM executar nem enviar.

        INVARIANTE: rejeita risk_result.approved=False ANTES de qualquer
        montagem (igual aos demais executors).
        """
        if not risk_result.approved:
            raise ValueError(
                "TealstreetCliGatewayAdapter.execute REJEITA risk_result não aprovado. "
                "INVARIANTE: o fluxo DEVE passar pelo RiskEngine antes."
            )

        signal = risk_result.signal
        command = self.build_market_command(signal)
        payload = self.build_hook_payload(signal)

        missing = []
        if command is None:
            missing.append("cli_path")
        if payload is None:
            missing.append("hook_url+hook_id")

        if missing:
            reason = (
                f"dry_run: Tealstreet adapter montou parcialmente — "
                f"config ausente: {missing}. Nenhum subprocess executado, "
                f"nenhum HTTP enviado. Uso real depende de ToS HyroTrader "
                f"+ aprovação manual."
            )
        else:
            reason = (
                f"dry_run: Tealstreet adapter montou command CLI + hook_payload "
                f"para symbol={signal.symbol} side={signal.side.value} "
                f"size_usd={signal.position_size_usd}. Nada foi executado nem enviado. "
                f"Adapter é experimental — uso real depende de ToS HyroTrader."
            )

        _logger.info(
            f"TealstreetCliGatewayAdapter.execute: DRY-RUN | "
            f"symbol={signal.symbol} | side={signal.side.value} | "
            f"command_built={command is not None} | payload_built={payload is not None}"
        )

        return TealstreetDryRunResult(
            success=True,
            operation="place_order",
            reason=reason,
            command=command,
            hook_payload=payload,
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

    @property
    def config(self) -> TealstreetGatewayConfig:
        """Config (imutável). Snapshot sanitizado via .to_dict()."""
        return self._config

    def get_summary(self) -> dict:
        """Resumo para audit/log. SEM secrets, SEM URLs com token."""
        return {
            "provider_id": self.PROVIDER_ID,
            "dry_run": self._dry_run,
            "capability": self._capability.to_dict(),
            "config": self._config.to_dict(),
        }

    def __repr__(self) -> str:
        # NUNCA inclui valores de config completos no repr (defesa contra leak)
        return (
            f"TealstreetCliGatewayAdapter(provider_id={self.PROVIDER_ID}, "
            f"dry_run={self._dry_run}, "
            f"hook_secret_present={self._config.hook_secret is not None})"
        )
