"""
OperationalProfile — Perfil operacional imutável (FASE 16)
============================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - PROVIDER-AGNOSTIC. NÃO depende de provider_name == "HyroTrader"
      nem de qualquer provider específico. Use flags estruturados
      (is_prop_firm, is_challenge_account, etc.).
    - NÃO substitui RiskConfig/RiskEngine. risk_config_overrides é
      apenas configuração explícita/validável — NÃO é aplicada
      automaticamente em runtime nesta fase.
    - Frozen dataclass; campos imutáveis. Tuplas usadas para sequências
      para garantir imutabilidade.
    - Nenhum max_profit_usd obrigatório. Challenge target é apenas KPI.

CAMPOS:
    Identificação descritiva:
        name, description, provider_type
        is_prop_firm, is_challenge_account, is_funded_account
        account_size_usd (None → ler do RiskConfig em runtime)

    Regras operacionais (NÃO substituem RiskConfig):
        max_concurrent_positions      (default 1; conservador)
        max_session_minutes           (None = sem limite)
        pause_after_consecutive_losses(None = desabilitado)
        max_trades_per_session        (None = sem limite extra)
        allowed_symbols               (tupla vazia = sem restrição)
        allowed_hours_utc             (tupla vazia = 24h)
        kill_switch_enabled           (default False)
        conservative_mode             (default False)
        require_manual_ack_on_triangulation (default True; FASE 16 default seguro)

    Configurações recomendadas para RiskConfig (somente sugestão):
        risk_config_overrides         (MappingProxyType, read-only)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple


# Tipos públicos de provider/conta (estáveis — não renomear)
_VALID_PROVIDER_TYPES: frozenset = frozenset({
    "personal", "prop_challenge", "prop_funded", "exchange", "custom",
})

# FASE 31 — lados/modos validos (estaveis)
_VALID_SIDES: frozenset = frozenset({"long", "short", "both"})
_VALID_PREDICTION_MODES: frozenset = frozenset({
    "disabled", "read_only", "advisory",
})
# Ambientes proibidos SEMPRE nesta macrofase (live/mainnet bloqueados).
_FORBIDDEN_ENVIRONMENTS: frozenset = frozenset({
    "live", "mainnet", "production", "prod", "real",
})


@dataclass(frozen=True)
class OperationalProfile:
    """
    Perfil operacional imutável, provider-agnostic.

    Frozen. NÃO substitui RiskConfig nem RiskEngine — apenas agrega
    metadados e sugere/valida configurações.

    Nesta FASE 16, runtime NÃO aplica `risk_config_overrides`
    automaticamente. Esse campo é meta para validação cruzada e
    documentação operacional. Edição manual do `.env` continua sendo
    o caminho oficial para alterar o RiskConfig vigente.
    """

    # --- Identificação descritiva ---
    name: str
    description: str
    provider_type: str
    is_prop_firm: bool = False
    is_challenge_account: bool = False
    is_funded_account: bool = False
    account_size_usd: Optional[float] = None

    # --- Regras operacionais (sugestões; runtime soberano é o RiskEngine) ---
    max_concurrent_positions: int = 1
    max_session_minutes: Optional[int] = None
    pause_after_consecutive_losses: Optional[int] = None
    max_trades_per_session: Optional[int] = None
    allowed_symbols: Tuple[str, ...] = ()
    allowed_hours_utc: Tuple[Tuple[int, int], ...] = ()
    kill_switch_enabled: bool = False
    conservative_mode: bool = False
    # FASE 16 default seguro: triangulação SEMPRE exige ack humano.
    require_manual_ack_on_triangulation: bool = True

    # --- Sugestões para RiskConfig (read-only; não aplicado automaticamente) ---
    risk_config_overrides: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    # =======================================================================
    # FASE 31 — campos ADITIVOS (defaults seguros; retrocompatíveis).
    # Permissões NUNCA concedem ordem real sozinhas: gates ENV próprios
    # continuam obrigatórios (nenhum gate implica outro).
    # =======================================================================

    # Estratégias/lados permitidos
    allowed_strategies: Tuple[str, ...] = ()   # vazio = sem restrição
    allowed_sides: str = "long"                # long | short | both

    # Permissões demo (todas restritivas por default)
    allow_demo_real: bool = False
    allow_short_demo: bool = False
    allow_multi_order_demo: bool = False

    # IA de apoio (FASE 32) — consultiva; nunca executa
    allow_ai_assistance: bool = False
    allow_ai_veto: bool = False

    # Prediction markets (FASE 34) — read-only/advisory; nunca executa
    allow_prediction_market_context: bool = False
    prediction_context_mode: str = "disabled"  # disabled|read_only|advisory
    allowed_prediction_providers: Tuple[str, ...] = ()
    prediction_market_execution_allowed: bool = False  # SEMPRE False
    max_prediction_context_age_seconds: float = 300.0

    # Tetos operacionais (espelham EnduranceLimits; runner deriva de cá)
    max_orders_per_day: int = 3
    max_orders_per_session: int = 1
    max_open_positions: int = 1
    max_consecutive_losses: int = 2
    max_api_failures: int = 3
    max_stale_data_seconds: float = 300.0
    require_sl_tp: bool = True
    flat_check_interval_minutes: int = 5

    # Duração/alavancagem/provider/ambiente
    allowed_duration_presets: Tuple[str, ...] = ()  # vazio = todos
    max_leverage: float = 1.0
    allowed_provider_ids: Tuple[str, ...] = ()      # vazio = default safe
    allowed_environments: Tuple[str, ...] = ("paper", "demo")

    # FASE 36 Bloco E2 - permissoes de position management.
    # Defaults SEGUROS (OFF/blocked). Limites numericos V5-V8 NUNCA
    # vivem no perfil: vem dos Operator Inputs.
    allow_scale_in: bool = False
    allow_partial_reduce: bool = False
    allow_reversal: str = "blocked"   # blocked | manual_review_only

    def __post_init__(self) -> None:
        # name não-vazio
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(
                f"OperationalProfile.name deve ser string não-vazia; "
                f"recebido {self.name!r}"
            )
        # provider_type válido
        if self.provider_type not in _VALID_PROVIDER_TYPES:
            raise ValueError(
                f"provider_type inválido: {self.provider_type!r}. "
                f"Aceitos: {sorted(_VALID_PROVIDER_TYPES)}"
            )
        # tuplas para sequências (defensivo)
        if not isinstance(self.allowed_symbols, tuple):
            object.__setattr__(
                self, "allowed_symbols", tuple(self.allowed_symbols)
            )
        if not isinstance(self.allowed_hours_utc, tuple):
            object.__setattr__(
                self,
                "allowed_hours_utc",
                tuple(tuple(h) for h in self.allowed_hours_utc),
            )
        # risk_config_overrides imutável
        if not isinstance(self.risk_config_overrides, MappingProxyType):
            object.__setattr__(
                self,
                "risk_config_overrides",
                MappingProxyType(dict(self.risk_config_overrides)),
            )

        # ===================================================================
        # FASE 31 — validações dos campos aditivos
        # ===================================================================
        if self.allowed_sides not in _VALID_SIDES:
            raise ValueError(
                f"allowed_sides inválido: {self.allowed_sides!r}. "
                f"Aceitos: {sorted(_VALID_SIDES)}"
            )
        if self.prediction_context_mode not in _VALID_PREDICTION_MODES:
            raise ValueError(
                f"prediction_context_mode inválido: "
                f"{self.prediction_context_mode!r}. "
                f"Aceitos: {sorted(_VALID_PREDICTION_MODES)}"
            )
        # REGRA INVIOLÁVEL: execução em prediction markets NUNCA permitida
        # nesta macrofase (FASE 34 é read-only/advisory).
        if self.prediction_market_execution_allowed:
            raise ValueError(
                "prediction_market_execution_allowed=True é proibido "
                "nesta macrofase (Polymarket é read-only/advisory)"
            )
        # REGRA INVIOLÁVEL: live/mainnet bloqueados em qualquer perfil.
        for env in self.allowed_environments:
            if str(env).strip().lower() in _FORBIDDEN_ENVIRONMENTS:
                raise ValueError(
                    f"allowed_environments contém ambiente proibido: "
                    f"{env!r} (live/mainnet bloqueados)"
                )
        # Tetos numéricos
        if self.max_orders_per_day < 1:
            raise ValueError(
                f"max_orders_per_day deve ser >= 1: {self.max_orders_per_day}"
            )
        if self.max_orders_per_session < 1:
            raise ValueError(
                "max_orders_per_session deve ser >= 1: "
                f"{self.max_orders_per_session}"
            )
        if self.max_open_positions < 1:
            raise ValueError(
                f"max_open_positions deve ser >= 1: {self.max_open_positions}"
            )
        if self.max_consecutive_losses < 1:
            raise ValueError(
                "max_consecutive_losses deve ser >= 1: "
                f"{self.max_consecutive_losses}"
            )
        if self.max_api_failures < 1:
            raise ValueError(
                f"max_api_failures deve ser >= 1: {self.max_api_failures}"
            )
        if self.max_stale_data_seconds <= 0:
            raise ValueError(
                "max_stale_data_seconds deve ser > 0: "
                f"{self.max_stale_data_seconds}"
            )
        if self.flat_check_interval_minutes < 1:
            raise ValueError(
                "flat_check_interval_minutes deve ser >= 1: "
                f"{self.flat_check_interval_minutes}"
            )
        if self.max_prediction_context_age_seconds <= 0:
            raise ValueError(
                "max_prediction_context_age_seconds deve ser > 0: "
                f"{self.max_prediction_context_age_seconds}"
            )
        if self.max_leverage <= 0:
            raise ValueError(
                f"max_leverage deve ser > 0: {self.max_leverage}"
            )
        # FASE 36 E2 - reversao: enum restrito (nunca automatica).
        if self.allow_reversal not in ("blocked", "manual_review_only"):
            raise ValueError(
                f"allow_reversal invalido: {self.allow_reversal!r}; "
                "aceitos: blocked | manual_review_only"
            )
        # Tuplas defensivas (campos FASE 31)
        for tuple_field in (
            "allowed_strategies", "allowed_prediction_providers",
            "allowed_duration_presets", "allowed_provider_ids",
            "allowed_environments",
        ):
            val = getattr(self, tuple_field)
            if not isinstance(val, tuple):
                object.__setattr__(self, tuple_field, tuple(val))

    # -----------------------------------------------------------------------
    # Helpers de leitura
    # -----------------------------------------------------------------------

    @property
    def is_personal(self) -> bool:
        return self.provider_type == "personal"

    @property
    def has_restricted_symbols(self) -> bool:
        return bool(self.allowed_symbols)

    @property
    def has_restricted_hours(self) -> bool:
        return bool(self.allowed_hours_utc)

    def to_dict(self) -> dict:
        """Serialização JSON-friendly. risk_config_overrides vira dict raso."""
        return {
            "name": self.name,
            "description": self.description,
            "provider_type": self.provider_type,
            "is_prop_firm": self.is_prop_firm,
            "is_challenge_account": self.is_challenge_account,
            "is_funded_account": self.is_funded_account,
            "account_size_usd": self.account_size_usd,
            "max_concurrent_positions": self.max_concurrent_positions,
            "max_session_minutes": self.max_session_minutes,
            "pause_after_consecutive_losses": self.pause_after_consecutive_losses,
            "max_trades_per_session": self.max_trades_per_session,
            "allowed_symbols": list(self.allowed_symbols),
            "allowed_hours_utc": [list(h) for h in self.allowed_hours_utc],
            "kill_switch_enabled": self.kill_switch_enabled,
            "conservative_mode": self.conservative_mode,
            "require_manual_ack_on_triangulation":
                self.require_manual_ack_on_triangulation,
            "risk_config_overrides": dict(self.risk_config_overrides),
            # FASE 31 — campos aditivos
            "allowed_strategies": list(self.allowed_strategies),
            "allowed_sides": self.allowed_sides,
            "allow_demo_real": bool(self.allow_demo_real),
            "allow_short_demo": bool(self.allow_short_demo),
            "allow_multi_order_demo": bool(self.allow_multi_order_demo),
            "allow_ai_assistance": bool(self.allow_ai_assistance),
            "allow_ai_veto": bool(self.allow_ai_veto),
            "allow_prediction_market_context": bool(
                self.allow_prediction_market_context
            ),
            "prediction_context_mode": self.prediction_context_mode,
            "allowed_prediction_providers": list(
                self.allowed_prediction_providers
            ),
            "prediction_market_execution_allowed": bool(
                self.prediction_market_execution_allowed
            ),
            "max_prediction_context_age_seconds": float(
                self.max_prediction_context_age_seconds
            ),
            "max_orders_per_day": int(self.max_orders_per_day),
            "max_orders_per_session": int(self.max_orders_per_session),
            "max_open_positions": int(self.max_open_positions),
            "max_consecutive_losses": int(self.max_consecutive_losses),
            "max_api_failures": int(self.max_api_failures),
            "max_stale_data_seconds": float(self.max_stale_data_seconds),
            "require_sl_tp": bool(self.require_sl_tp),
            "flat_check_interval_minutes": int(
                self.flat_check_interval_minutes
            ),
            "allowed_duration_presets": list(self.allowed_duration_presets),
            "max_leverage": float(self.max_leverage),
            "allowed_provider_ids": list(self.allowed_provider_ids),
            "allowed_environments": list(self.allowed_environments),
            # FASE 36 E2
            "allow_scale_in": bool(self.allow_scale_in),
            "allow_partial_reduce": bool(self.allow_partial_reduce),
            "allow_reversal": self.allow_reversal,
        }
