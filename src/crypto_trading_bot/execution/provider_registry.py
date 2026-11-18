"""
ProviderRegistry — FASE 8
===========================
Registro central de providers conhecidos pelo bot, com metadata
(capability + status + reason). É a trava de "quem pode executar".

⚠️  Registry só armazena METADATA. NÃO instancia clientes externos, NÃO
    armazena credenciais, NÃO conhece valores operacionais.

⚠️  TRAVA DE EXECUÇÃO:
    `assert_usable(provider_id, confirm_provider=False)` bloqueia:
        - FROZEN / RESTRICTED / UNCONFIRMED / DRY_RUN_ONLY → sempre
        - OPT_IN → se confirm_provider=False
    Apenas ACTIVE passa sem confirmação.

⚠️  PaperTrader continua o DEFAULT do BotEngine. O registry só DESCREVE
    providers — o caminho default não muda nesta fase.

PROVIDERS REGISTRADOS POR DEFAULT (FASE 8):
    paper                       → ACTIVE
    bybit_testnet_linear        → RESTRICTED (operador atual sem acesso)
    binance_futures_testnet     → DRY_RUN_ONLY (adapter esqueleto)
    hyrotrader_cleo_demo        → UNCONFIRMED (mecanismo desconhecido)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)


class ProviderBlockedError(RuntimeError):
    """Levantado quando o registry bloqueia o uso de um provider."""


@dataclass(frozen=True)
class ProviderEntry:
    """
    Entrada imutável do registry para um provider.

    Atributos:
        provider_id: slug único do provider.
        capability:  ProviderCapability declarada (boolean-only, sem secrets).
        status:      ProviderStatus operacional atual.
        reason:      Texto curto explicando o status (visível em audit/logs).
    """
    provider_id: str
    capability: ProviderCapability
    status: ProviderStatus
    reason: str = ""

    def to_dict(self) -> dict:
        """Snapshot sanitizado para auditoria. SEM credenciais, SEM factories."""
        return {
            "provider_id": self.provider_id,
            "status": self.status.value,
            "reason": self.reason,
            "capability": self.capability.to_dict(),
        }


class ProviderRegistry:
    """
    Registry em memória de providers conhecidos.

    Uso típico:
        from crypto_trading_bot.execution.provider_registry import get_registry
        registry = get_registry()
        registry.assert_usable("paper")                # OK (ACTIVE)
        registry.assert_usable("bybit_testnet_linear") # ProviderBlockedError
    """

    def __init__(self) -> None:
        self._entries: Dict[str, ProviderEntry] = {}

    def register(self, entry: ProviderEntry, *, replace: bool = False) -> None:
        """Registra uma entry. Levanta ValueError se já existe e replace=False."""
        if entry.provider_id in self._entries and not replace:
            raise ValueError(
                f"provider_id '{entry.provider_id}' já registrado. "
                "Use replace=True para sobrescrever."
            )
        self._entries[entry.provider_id] = entry

    def unregister(self, provider_id: str) -> None:
        """Remove uma entry (útil em testes para isolar)."""
        self._entries.pop(provider_id, None)

    def get(self, provider_id: str) -> ProviderEntry:
        """Recupera a entry. Levanta KeyError se não existe."""
        if provider_id not in self._entries:
            raise KeyError(f"provider_id '{provider_id}' não registrado.")
        return self._entries[provider_id]

    def list_available(self) -> Tuple[ProviderEntry, ...]:
        """Tupla read-only de todas as entries."""
        return tuple(self._entries.values())

    def assert_usable(
        self,
        provider_id: str,
        *,
        confirm_provider: bool = False,
    ) -> None:
        """
        Bloqueia uso de provider conforme status.

        Regras:
            ACTIVE       → passa.
            OPT_IN       → passa SOMENTE com confirm_provider=True.
            DRY_RUN_ONLY → bloqueia (real execution). Adapter ainda pode
                           ser usado em dry_run pelo caller; o registry
                           sinaliza que execução real está vedada.
            FROZEN / RESTRICTED / UNCONFIRMED → bloqueia sempre.

        Raises:
            KeyError:              provider_id não registrado.
            ProviderBlockedError:  qualquer bloqueio acima.
        """
        entry = self.get(provider_id)
        s = entry.status

        if s is ProviderStatus.ACTIVE:
            return

        if s is ProviderStatus.OPT_IN:
            if not confirm_provider:
                raise ProviderBlockedError(
                    f"provider '{provider_id}' está em OPT_IN — "
                    f"exige confirm_provider=True. reason={entry.reason}"
                )
            return

        # FROZEN | RESTRICTED | UNCONFIRMED | DRY_RUN_ONLY → bloqueia sempre
        raise ProviderBlockedError(
            f"provider '{provider_id}' está em status '{s.value}' — "
            f"bloqueado para execução. reason={entry.reason}"
        )

    def audit_snapshot(self) -> dict:
        """
        Snapshot completo do registry para auditoria.

        ⚠️  NUNCA contém credenciais, endpoints com URL completa, factories,
            instâncias de cliente. Apenas metadata declarada.
        """
        return {
            "providers": [e.to_dict() for e in self._entries.values()],
            "count": len(self._entries),
        }

    def snapshot_one(self, provider_id: str) -> Optional[dict]:
        """Snapshot de UM provider, ou None se não registrado."""
        try:
            return self.get(provider_id).to_dict()
        except KeyError:
            return None


# ---------------------------------------------------------------------------
# Default registry — populado uma vez no import deste módulo
# ---------------------------------------------------------------------------

_registry = ProviderRegistry()


def _register_defaults(registry: ProviderRegistry) -> None:
    """Registra os 4 providers conhecidos da FASE 8.

    PaperTrader → ACTIVE.
    Bybit linear → RESTRICTED (FASE 7 Estágio 3 bloqueado).
    Binance Futures Testnet → DRY_RUN_ONLY (adapter esqueleto).
    HyroTrader CLEO → UNCONFIRMED (mecanismo desconhecido).
    """

    # ---- paper (default absoluto) ----
    paper_cap = ProviderCapability(
        provider_id="paper",
        supports_market_order=True,
        supports_limit_order=False,
        supports_stop_loss=True,
        supports_take_profit=True,
        supports_reduce_only=False,
        supports_leverage_api=False,
        supports_positions_query=True,
        supports_balance_query=True,
        supports_cancel_order=False,
        is_demo_environment=True,
        is_live_environment=False,
        documented_assets=("BTCUSDT",),
        confirmed=True,
        confirmation_source="paper_trader.py — simulação determinística local",
        notes=(
            "Default seguro do BotEngine. Sem rede, sem secrets. "
            "Paper simulation NÃO garante performance futura."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="paper",
        capability=paper_cap,
        status=ProviderStatus.ACTIVE,
        reason="PaperTrader continua o default absoluto do BotEngine.",
    ))

    # ---- Bybit testnet linear (RESTRICTED) ----
    bybit_cap = ProviderCapability(
        provider_id="bybit_testnet_linear",
        supports_market_order=True,
        supports_limit_order=False,        # BybitClient só implementa market hoje
        supports_stop_loss=True,           # enviado como campo `stopLoss`
        supports_take_profit=True,         # enviado como campo `takeProfit`
        supports_reduce_only=False,        # NÃO no payload atual (auditado FASE 7)
        supports_leverage_api=False,       # leverage é conta, não payload
        supports_positions_query=True,
        supports_balance_query=True,
        supports_cancel_order=True,
        is_demo_environment=True,
        is_live_environment=False,
        documented_assets=("BTCUSDT",),
        confirmed=True,
        confirmation_source="Bybit V5 docs + FASE 5/6/7 testes offline",
        notes=(
            "Código FASE 5/6 intacto. Bloqueado por restrição regional ao produto "
            "derivativo na conta do operador (FASE 7 Estágio 3). Safe-check "
            "read-only continua válido se necessário."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="bybit_testnet_linear",
        capability=bybit_cap,
        status=ProviderStatus.RESTRICTED,
        reason=(
            "Operador atual sem acesso ao produto derivativo na conta — "
            "FASE 7 Estágio 3 bloqueado por restrição regional/regulatória. "
            "Código preservado; reclassificar para OPT_IN somente após resolução."
        ),
    ))

    # ---- Binance Futures Testnet (DRY_RUN_ONLY — adapter esqueleto) ----
    binance_cap = ProviderCapability(
        provider_id="binance_futures_testnet",
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
            "testnet.binancefuture.com. confirmed=False até evidência operacional. "
            "Adapter é esqueleto dry-run-only nesta fase — sem httpx, sem HMAC, "
            "sem internet. Testnet NÃO garante performance futura."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="binance_futures_testnet",
        capability=binance_cap,
        status=ProviderStatus.DRY_RUN_ONLY,
        reason=(
            "Cliente HTTP Binance NÃO implementado nesta fase. Adapter retorna "
            "dry_run; integração real fica em fase própria com aprovação explícita."
        ),
    ))

    # ---- Bybit Demo Trading linear (CANDIDATE_REVALIDATION — FASE 9 Fatia 2) ----
    bybit_demo_cap = ProviderCapability(
        provider_id="bybit_demo_linear",
        supports_market_order=True,
        supports_limit_order=False,         # análogo ao testnet: client só market
        supports_stop_loss=True,            # mesmo payload V5 — stopLoss/takeProfit
        supports_take_profit=True,
        # FASE 29: place_market_order ganhou param aditivo reduce_only
        # (default False preserva FASE 22 byte-a-byte). Demo Bybit
        # passa a SUPORTAR fechamento reduceOnly via API. Promocao para
        # ACTIVE continua exigindo execucao real bem-sucedida + auditoria.
        supports_reduce_only=True,
        supports_leverage_api=False,        # leverage é configurada na conta demo (UI)
        supports_positions_query=True,
        supports_balance_query=True,
        supports_cancel_order=True,
        is_demo_environment=True,
        is_live_environment=False,
        documented_assets=("BTCUSDT",),
        confirmed=False,
        confirmation_source="",
        notes=(
            "Bybit Demo Trading — endpoint https://api-demo.bybit.com (separado de "
            "testnet). Cliente já suporta `environment='demo'` (Fatia 1). Falta "
            "executor dedicado + script de safe-check real (não nesta fatia). "
            "Capabilities ainda NÃO confirmadas operacionalmente — safe-check real "
            "será requisito para confirmed=True. Demo Trading NÃO garante "
            "performance futura."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="bybit_demo_linear",
        capability=bybit_demo_cap,
        status=ProviderStatus.OPT_IN,
        reason=(
            "FASE 9 Fatia 4B: BybitDemoExecutor implementa execute(dry_run=False) "
            "via place_market_order + reconciliação (get_order_status + "
            "get_positions) + record_trade_opened em FILLED. Safe-check real já "
            "validado manualmente (Fatia 3). Status OPT_IN — assert_usable exige "
            "confirm_provider=True. Execução real continua exigindo, além disso: "
            "triple-flag-lock no script + triple-lock do ModeGuard + sizing "
            "explícito + RiskEngine.validate_signal. NÃO promovido a ACTIVE — "
            "promoção futura exige execução real bem-sucedida + auditoria de "
            "redaction in-memory durante ordem + revisão arquitetural separada."
        ),
    ))

    # ---- Tealstreet CLI Gateway (DRY_RUN_ONLY — adapter esqueleto FASE 9B) ----
    tealstreet_cap = ProviderCapability(
        provider_id="tealstreet_cli_gateway",
        supports_market_order=True,
        supports_limit_order=True,
        supports_stop_loss=True,
        supports_take_profit=True,
        supports_reduce_only=False,
        supports_leverage_api=False,
        supports_positions_query=False,
        supports_balance_query=False,
        supports_cancel_order=True,
        supports_webhook=True,
        supports_cli=True,
        is_demo_environment=True,
        is_live_environment=False,
        documented_assets=("BTCUSDT",),
        confirmed=False,
        confirmation_source="",
        notes=(
            "Experimental. Tealstreet oferece CLI + webhooks + simulation mode. "
            "Adapter da FASE 9B apenas MONTA comandos/payloads — nunca executa "
            "subprocess nem envia HTTP. dry_run=False bloqueado no construtor. "
            "Uso real com HyroTrader depende de ToS/regras da prop firm. "
            "Tealstreet/HyroTrader/Free Trial NÃO garante performance futura."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="tealstreet_cli_gateway",
        capability=tealstreet_cap,
        status=ProviderStatus.DRY_RUN_ONLY,
        reason=(
            "Adapter esqueleto (FASE 9B) — monta comandos CLI e payloads de "
            "webhook localmente sem executar nem enviar. Integração real exige "
            "fase própria com aprovação explícita + confirmação de que ToS/"
            "regras HyroTrader permitem o uso desse gateway."
        ),
    ))

    # ---- HyroTrader CLEO (UNCONFIRMED — mecanismo desconhecido) ----
    cleo_cap = ProviderCapability(
        provider_id="hyrotrader_cleo_demo",
        supports_market_order=False,
        supports_limit_order=False,
        supports_stop_loss=False,
        supports_take_profit=False,
        supports_reduce_only=False,
        supports_leverage_api=False,
        supports_positions_query=False,
        supports_balance_query=False,
        supports_cancel_order=False,
        is_demo_environment=False,         # nem isso é confirmado
        is_live_environment=False,
        documented_assets=(),
        confirmed=False,
        confirmation_source="",
        notes=(
            "Mecanismo de integração CLEO (API REST/WS, SDK, webhook TradingView, "
            "bridge MT4/MT5, FIX, arquivo, UI automation) ainda NÃO confirmado. "
            "Capabilities todas False até evidência operacional. Ver "
            "docs/hyrotrader_cleo.md para perguntas pendentes. NENHUMA execução "
            "real é possível até resposta + nova aprovação. HyroTrader Free Trial / "
            "Challenge NÃO garante performance futura."
        ),
    )
    registry.register(ProviderEntry(
        provider_id="hyrotrader_cleo_demo",
        capability=cleo_cap,
        status=ProviderStatus.UNCONFIRMED,
        reason=(
            "Mecanismo de integração não confirmado. Aguarda respostas "
            "operacionais (API/SDK/webhook/bridge?), assets, tipos de ordem "
            "suportados, e crucialmente ToS sobre automação. Ver "
            "docs/hyrotrader_cleo.md."
        ),
    ))


_register_defaults(_registry)


def get_registry() -> ProviderRegistry:
    """Retorna a instância singleton do registry default (com defaults FASE 8)."""
    return _registry
