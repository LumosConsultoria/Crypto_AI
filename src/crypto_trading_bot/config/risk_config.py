"""
Configuração de Regras de Risco + Perfil de Conta
===================================================
Define os parâmetros de risco do sistema e o perfil genérico da conta.

⚠️  PRINCÍPIOS FUNDAMENTAIS:
    1. O RiskEngine foca em CONTROLE DE PERDA — nunca em limite de ganho.
    2. Meta de lucro (challenge_profit_target_usd) é APENAS KPI informativo.
    3. Lucro é métrica de performance, não trava de segurança.
    4. O bot é agnóstico de provider — HyroTrader é apenas um template/exemplo.
    5. A lógica central usa campos genéricos (account_size_usd, max_daily_loss_pct).
    6. Nunca tome decisões com base em provider_name.

⚠️  SEPARAÇÃO DE RESPONSABILIDADES:
    - `account_size_usd`           → base de cálculo de risco
    - `max_daily_loss_pct`         → trava de segurança (bloqueante)
    - `max_total_loss_pct`         → trava de segurança (bloqueante)
    - `challenge_profit_target_usd` → KPI informativo (NÃO bloqueante)
    - `enforce_profit_target`      → sempre False por padrão, nunca bloqueia

Sobre provider_type:
    - "personal"       → conta pessoal sem restrições de prop firm
    - "prop_challenge" → conta em fase de challenge de prop firm
    - "prop_funded"    → conta funded após aprovação
    - "exchange"       → conta direta na exchange (Bybit, Binance, etc.)
    - "custom"         → perfil totalmente personalizado pelo usuário
"""

from decimal import Decimal
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Perfis de conta pré-definidos (templates genéricos — não regras obrigatórias)
# ---------------------------------------------------------------------------
# ⚠️  Estes são EXEMPLOS DE CONFIGURAÇÃO.
# NÃO alteram limites automaticamente — configure explicitamente via .env.
# HyroTrader é apenas um exemplo de prop firm, não dependência central.

ACCOUNT_PROFILES: dict[str, dict] = {
    # Conta pessoal — sem restrições de prop firm
    "personal": {
        "provider_type": "personal",
        "provider_name": "personal",
        "is_prop_firm": False,
        "is_challenge_account": False,
        "is_funded_account": False,
        "account_size_usd": 5000.0,
        "description": "Conta pessoal/exchange. Configure limites conforme sua preferência.",
    },
    # Challenge genérico de 5k — qualquer prop firm
    "prop_challenge_5k": {
        "provider_type": "prop_challenge",
        "provider_name": "generic_prop_firm",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": 5000.0,
        "description": "Challenge genérico de 5.000 USD. Preencha os limites reais em .env.",
    },
    # Challenge genérico de 10k
    "prop_challenge_10k": {
        "provider_type": "prop_challenge",
        "provider_name": "generic_prop_firm",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": 10000.0,
        "description": "Challenge genérico de 10.000 USD. Preencha os limites reais em .env.",
    },
    # HyroTrader 5k — apenas como template/exemplo
    # ⚠️  NÃO é uma dependência central. Regras reais em docs/risk_rules.md.
    "hyrotrader_5k": {
        "provider_type": "prop_challenge",
        "provider_name": "HyroTrader",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": 5000.0,
        "description": "HyroTrader One Step 5.000 USDT — ver docs/risk_rules.md para regras exatas.",
    },
    # HyroTrader 10k — apenas como template/exemplo
    "hyrotrader_10k": {
        "provider_type": "prop_challenge",
        "provider_name": "HyroTrader",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": 10000.0,
        "description": "HyroTrader One Step 10.000 USDT — ver docs/risk_rules.md para regras exatas.",
    },
    # HyroTrader 25k — apenas como template/exemplo
    "hyrotrader_25k": {
        "provider_type": "prop_challenge",
        "provider_name": "HyroTrader",
        "is_prop_firm": True,
        "is_challenge_account": True,
        "is_funded_account": False,
        "account_size_usd": 25000.0,
        "description": "HyroTrader One Step 25.000 USDT — ver docs/risk_rules.md para regras exatas.",
    },
    # Conta funded genérica — após aprovação do challenge
    "prop_funded": {
        "provider_type": "prop_funded",
        "provider_name": "generic_prop_firm",
        "is_prop_firm": True,
        "is_challenge_account": False,
        "is_funded_account": True,
        "account_size_usd": 5000.0,
        "description": "Conta funded genérica. Preencha os limites reais em .env.",
    },
    # Perfil totalmente customizável
    "custom": {
        "provider_type": "custom",
        "provider_name": "custom",
        "is_prop_firm": False,
        "is_challenge_account": False,
        "is_funded_account": False,
        "account_size_usd": None,   # definido pelo usuário via RISK_ACCOUNT_SIZE_USD
        "description": "Perfil customizado. Configure todos os parâmetros via .env.",
    },
}


class RiskConfig(BaseSettings):
    """
    Parâmetros de risco e perfil de conta configuráveis.

    Todos os valores são carregados do .env com prefixo RISK_.
    O RiskEngine usa estes valores para validar todas as operações.

    ⚠️  REGRA FUNDAMENTAL: O RiskEngine controla PERDAS, não GANHOS.
    - max_daily_loss_pct, max_total_loss_pct → BLOQUEANTES (segurança)
    - challenge_profit_target_usd           → INFORMATIVO (apenas KPI)
    - enforce_profit_target                 → sempre False por padrão

    O bot é agnóstico de provider. A lógica central nunca verifica
    provider_name para tomar decisões de risco.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="RISK_",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # IDENTIFICAÇÃO E PERFIL DA CONTA
    # ⚠️  Apenas descritivos — a lógica de risco usa os campos genéricos abaixo
    # -----------------------------------------------------------------------

    account_profile_name: str = Field(
        default="custom",
        description=(
            "Nome do perfil de conta. Exemplos: 'personal', 'prop_challenge_5k', "
            "'hyrotrader_5k', 'custom'. "
            "APENAS informativo — não altera limites automaticamente. "
            "Configure os limites explicitamente via variáveis de ambiente."
        ),
    )

    provider_name: str = Field(
        default="custom",
        description=(
            "Nome do provider/corretora. Exemplos: 'personal', 'HyroTrader', "
            "'Bybit', 'generic_prop_firm'. "
            "APENAS descritivo — a lógica central NUNCA usa este campo para "
            "tomar decisões de risco."
        ),
    )

    provider_type: Literal[
        "personal", "prop_challenge", "prop_funded", "exchange", "custom"
    ] = Field(
        default="custom",
        description=(
            "Tipo/categoria do provider. "
            "'personal' → conta própria sem restrições de prop. "
            "'prop_challenge' → fase de challenge de prop firm. "
            "'prop_funded' → conta funded após aprovação. "
            "'exchange' → conta direta na exchange. "
            "'custom' → perfil customizável."
        ),
    )

    is_prop_firm: bool = Field(
        default=False,
        description="True se for conta de prop firm. Apenas informativo.",
    )

    is_challenge_account: bool = Field(
        default=False,
        description="True se estiver em fase de challenge. Apenas informativo.",
    )

    is_funded_account: bool = Field(
        default=False,
        description="True se for conta funded (após aprovação do challenge). Apenas informativo.",
    )

    # -----------------------------------------------------------------------
    # TAMANHO DA CONTA
    # -----------------------------------------------------------------------

    account_size_usd: float = Field(
        default=5000.0,
        gt=0.0,
        description=(
            "Tamanho da conta em USD. BASE de todos os cálculos de risco. "
            "Configure via RISK_ACCOUNT_SIZE_USD. "
            "NUNCA coloque este valor hardcoded em estratégias ou execução."
        ),
    )

    # -----------------------------------------------------------------------
    # LIMITES DE PERDA (BLOQUEANTES — segurança do capital)
    # -----------------------------------------------------------------------

    max_daily_loss_pct: float = Field(
        default=0.05,
        ge=0.001,
        le=1.0,
        description=(
            "Perda máxima diária como % do account_size_usd. "
            "Ex: 0.05 = 5%. BLOQUEANTE — impede novos trades quando atingido."
        ),
    )

    max_total_loss_pct: float = Field(
        default=0.10,
        ge=0.001,
        le=1.0,
        description=(
            "Perda máxima total (drawdown) como % do account_size_usd. "
            "Ex: 0.10 = 10%. BLOQUEANTE — impede novos trades quando atingido."
        ),
    )

    # -----------------------------------------------------------------------
    # LIMITES DE OPERAÇÃO
    # -----------------------------------------------------------------------

    max_trades_per_day: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Máximo de trades permitidos por dia. Bloqueio de overtrading.",
    )

    max_open_positions: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Máximo de posições abertas simultaneamente.",
    )

    max_risk_per_trade_pct: float = Field(
        default=0.01,
        ge=0.0001,
        le=0.5,
        description=(
            "Risco máximo por trade como % do account_size_usd. "
            "Ex: 0.01 = 1% da conta por operação."
        ),
    )

    max_exposure_per_asset_pct: float = Field(
        default=0.20,
        ge=0.01,
        le=1.0,
        description="Exposição máxima por ativo como % do account_size_usd.",
    )

    # -----------------------------------------------------------------------
    # ALAVANCAGEM
    # -----------------------------------------------------------------------

    max_leverage: float = Field(
        default=3.0,
        ge=1.0,
        le=100.0,
        description="Alavancagem máxima permitida. Ex: 3.0 = até 3x.",
    )

    # -----------------------------------------------------------------------
    # STOP LOSS (obrigatório por operação)
    # -----------------------------------------------------------------------

    min_stop_loss_pct: float = Field(
        default=0.005,
        ge=0.001,
        le=0.5,
        description="Stop loss mínimo obrigatório como % do preço de entrada. Ex: 0.005 = 0.5%.",
    )

    max_stop_loss_pct: float = Field(
        default=0.05,
        ge=0.001,
        le=0.5,
        description="Stop loss máximo por operação como % do preço de entrada.",
    )

    # -----------------------------------------------------------------------
    # POSICIONAMENTO
    # -----------------------------------------------------------------------

    max_position_size_pct: float = Field(
        default=0.10,
        ge=0.001,
        le=1.0,
        description="Tamanho máximo de uma posição como % do account_size_usd.",
    )

    # -----------------------------------------------------------------------
    # META DE CHALLENGE / OBJETIVO DE CONTA (APENAS KPI — NÃO BLOQUEANTE)
    # ⚠️  Lucro é métrica de performance, não trava de segurança.
    # ⚠️  Estes campos NUNCA bloqueiam trades nem encerram posições.
    # -----------------------------------------------------------------------

    challenge_profit_target_usd: Optional[float] = Field(
        default=None,
        ge=0.0,
        description=(
            "Meta de lucro do challenge em USD. APENAS KPI informativo. "
            "NÃO bloqueia trades. NÃO encerra posições. "
            "Aparece em relatórios como 'progresso em relação à meta'. "
            "Ex: 500.0 = meta de 500 USD de lucro para conta de 5k (10%)."
        ),
    )

    enforce_profit_target: bool = Field(
        default=False,
        description=(
            "Se True, permite registrar alerta quando meta for atingida. "
            "SEMPRE False por padrão — nunca bloqueia trades automaticamente. "
            "Mesmo quando True, apenas loga informação — não interfere na execução."
        ),
    )

    # -----------------------------------------------------------------------
    # Propriedades Derivadas (calculadas automaticamente)
    # -----------------------------------------------------------------------

    @property
    def max_daily_loss_usd(self) -> Decimal:
        """Perda diária máxima em USD (calculada)."""
        return Decimal(str(self.account_size_usd)) * Decimal(str(self.max_daily_loss_pct))

    @property
    def max_total_loss_usd(self) -> Decimal:
        """Perda total máxima em USD (drawdown limit calculado)."""
        return Decimal(str(self.account_size_usd)) * Decimal(str(self.max_total_loss_pct))

    @property
    def max_position_size_usd(self) -> Decimal:
        """Tamanho máximo de posição em USD (calculado)."""
        return Decimal(str(self.account_size_usd)) * Decimal(str(self.max_position_size_pct))

    @property
    def max_risk_per_trade_usd(self) -> Decimal:
        """Risco máximo por trade em USD (calculado)."""
        return Decimal(str(self.account_size_usd)) * Decimal(str(self.max_risk_per_trade_pct))

    @property
    def max_exposure_per_asset_usd(self) -> Decimal:
        """Exposição máxima por ativo em USD (calculada)."""
        return Decimal(str(self.account_size_usd)) * Decimal(str(self.max_exposure_per_asset_pct))

    @property
    def challenge_profit_target_pct(self) -> Optional[float]:
        """Meta de lucro como % do account_size_usd. None se meta não configurada."""
        if self.challenge_profit_target_usd is None:
            return None
        return self.challenge_profit_target_usd / self.account_size_usd

    # -----------------------------------------------------------------------
    # Validadores
    # -----------------------------------------------------------------------

    @field_validator("max_stop_loss_pct")
    @classmethod
    def max_sl_must_be_gte_min(cls, v: float, info: object) -> float:
        """Stop loss máximo deve ser >= mínimo."""
        min_sl = getattr(info, "data", {}).get("min_stop_loss_pct", 0)
        if min_sl and v < min_sl:
            raise ValueError(
                f"max_stop_loss_pct ({v}) deve ser >= min_stop_loss_pct ({min_sl})"
            )
        return v

    @field_validator("max_total_loss_pct")
    @classmethod
    def total_loss_must_be_gte_daily(cls, v: float, info: object) -> float:
        """Perda total deve ser >= perda diária."""
        daily = getattr(info, "data", {}).get("max_daily_loss_pct", 0)
        if daily and v < daily:
            raise ValueError(
                f"max_total_loss_pct ({v}) deve ser >= max_daily_loss_pct ({daily})"
            )
        return v

    def __repr__(self) -> str:
        challenge_info = ""
        if self.challenge_profit_target_usd is not None:
            challenge_info = (
                f", challenge_target={self.challenge_profit_target_usd:.0f}USD"
                f" [KPI-only]"
            )
        return (
            f"RiskConfig("
            f"profile={self.account_profile_name!r}, "
            f"provider={self.provider_name!r} [{self.provider_type}], "
            f"account={self.account_size_usd:.0f}USD, "
            f"daily_loss={self.max_daily_loss_pct:.1%}={float(self.max_daily_loss_usd):.0f}USD, "
            f"total_loss={self.max_total_loss_pct:.1%}={float(self.max_total_loss_usd):.0f}USD, "
            f"max_trades={self.max_trades_per_day}, "
            f"leverage={self.max_leverage}x"
            f"{challenge_info})"
        )


@lru_cache(maxsize=1)
def get_risk_config() -> RiskConfig:
    """
    Retorna a instância singleton da configuração de risco.

    Em testes, use: get_risk_config.cache_clear() para resetar.
    """
    return RiskConfig()
