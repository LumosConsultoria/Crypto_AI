"""
ProviderCapability — FASE 8
=============================
Modelo imutável que descreve o que um provider de execução SABE fazer.

⚠️  Descreve SUPORTE (booleans), nunca valores operacionais (capital, sizing,
    leverage, risco). Esses continuam vindo de signal/CLI/Settings.

⚠️  Defaults seguros: TODOS os flags de suporte são False; `confirmed=False`;
    `is_live_environment=False`. Adicionar suporte exige declaração explícita.

⚠️  Capability declarada (`confirmed=False`) NÃO autoriza execução real.
    A trava de execução é o ProviderRegistry + ModeGuard.assert_provider_allowed.

USO TÍPICO:
    capability = ProviderCapability(
        provider_id="binance_futures_testnet",
        supports_market_order=True,
        is_demo_environment=True,
        documented_assets=("BTCUSDT",),
        confirmed=False,  # ainda não validado por evidência operacional
        confirmation_source="",
        notes="Capabilities declaradas com base em docs públicas.",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple


class ProviderStatus(str, Enum):
    """
    Estado operacional de um provider no registry.

    ACTIVE                  — usável após registry.assert_usable (paper).
    OPT_IN                  — usável só com confirm_provider=True (segunda opção opt-in).
    DRY_RUN_ONLY            — adapter existe mas só simula; assert_usable bloqueia.
    FROZEN                  — bloqueado por decisão arquitetural; assert_usable bloqueia.
    RESTRICTED              — bloqueado por restrição externa (regulatória/regional/conta).
    UNCONFIRMED             — registrado mas sem capabilities confirmadas; assert_usable bloqueia.
    CANDIDATE_REVALIDATION  — (FASE 9 Fatia 2) evidência operacional preliminar coletada
                              (UI validada, key existe), mas requer adaptação técnica e
                              executor dedicado antes de OPT_IN. assert_usable bloqueia.
                              Semântica mais avançada que UNCONFIRMED, menos do que OPT_IN.
    """
    ACTIVE = "active"
    OPT_IN = "opt_in"
    DRY_RUN_ONLY = "dry_run_only"
    FROZEN = "frozen"
    RESTRICTED = "restricted"
    UNCONFIRMED = "unconfirmed"
    CANDIDATE_REVALIDATION = "candidate_revalidation"


@dataclass(frozen=True)
class ProviderCapability:
    """
    Capacidades declaradas de um provider de execução.

    ⚠️  Defaults seguros: tudo False, confirmed=False, is_live_environment=False.
    ⚠️  Imutável (frozen): não pode ser modificada após construção.
    ⚠️  NÃO armazena credenciais, endpoints, valores operacionais.
    """

    provider_id: str

    # Tipos de ordem suportados
    supports_market_order: bool = False
    supports_limit_order: bool = False

    # Atrelados à ordem ou separados
    supports_stop_loss: bool = False
    supports_take_profit: bool = False

    # Controles de posição
    supports_reduce_only: bool = False
    supports_leverage_api: bool = False     # set_leverage via API (vs. conta)

    # Consultas
    supports_positions_query: bool = False
    supports_balance_query: bool = False
    supports_cancel_order: bool = False

    # FASE 9B — mecanismos de transporte (descrição de canal, não de execução)
    supports_webhook: bool = False
    supports_cli: bool = False

    # Ambiente
    is_demo_environment: bool = False
    is_live_environment: bool = False

    # Documentação / evidência
    documented_assets: Tuple[str, ...] = ()
    confirmed: bool = False
    confirmation_source: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        """Snapshot sanitizado para audit_snapshot / logs. SEM credenciais."""
        return {
            "provider_id": self.provider_id,
            "supports_market_order": self.supports_market_order,
            "supports_limit_order": self.supports_limit_order,
            "supports_stop_loss": self.supports_stop_loss,
            "supports_take_profit": self.supports_take_profit,
            "supports_reduce_only": self.supports_reduce_only,
            "supports_leverage_api": self.supports_leverage_api,
            "supports_positions_query": self.supports_positions_query,
            "supports_balance_query": self.supports_balance_query,
            "supports_cancel_order": self.supports_cancel_order,
            "supports_webhook": self.supports_webhook,
            "supports_cli": self.supports_cli,
            "is_demo_environment": self.is_demo_environment,
            "is_live_environment": self.is_live_environment,
            "documented_assets": list(self.documented_assets),
            "confirmed": self.confirmed,
            "confirmation_source": self.confirmation_source,
            "notes": self.notes,
        }
