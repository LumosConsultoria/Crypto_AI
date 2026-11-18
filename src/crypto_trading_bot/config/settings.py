"""
Configurações Gerais do Sistema
================================
Carrega e valida as configurações principais a partir de variáveis de ambiente.

Usa pydantic-settings para validação automática de tipos e valores.
"""

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(str, Enum):
    """Modos de operação disponíveis."""
    PAPER = "paper"       # Simulação local sem API
    TESTNET = "testnet"   # Bybit testnet (sem dinheiro real)
    DEMO = "demo"         # FASE 9 Fatia 2 — Bybit Demo Trading (separado de testnet)
    LIVE = "live"         # PRODUÇÃO — bloqueado por padrão


class Settings(BaseSettings):
    """
    Configurações principais do sistema.

    Todos os valores são carregados do arquivo .env.
    Valores padrão garantem que o modo mais seguro seja sempre o default.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- MODO DE OPERAÇÃO ---
    trading_mode: TradingMode = Field(
        default=TradingMode.PAPER,
        description="Modo de operação: paper | testnet | live",
    )

    # Trava dupla para execução real — AMBAS devem ser true para live
    enable_live_trading: bool = Field(
        default=False,
        description="Habilitar live trading? Deve ser false por padrão.",
    )

    # FASE 5 — Trava DUPLA para execução em testnet (não afrouxa live).
    # Mesmo com TRADING_MODE=testnet, ordens privadas só são enviadas se
    # ENABLE_TESTNET_EXECUTION=true E o chamador passar confirm_testnet_execution=True.
    enable_testnet_execution: bool = Field(
        default=False,
        description=(
            "Habilitar execução em Bybit testnet? Deve ser false por padrão. "
            "Mesmo com TRADING_MODE=testnet, esta flag DEVE ser true E a chamada "
            "deve incluir confirm_testnet_execution=True explicitamente."
        ),
    )

    # FASE 9 Fatia 2 — Trava DUPLA para execução em Bybit Demo Trading
    # (ambiente separado de testnet). Espelha o padrão testnet sem afrouxar live.
    # Mesmo com TRADING_MODE=demo, ordens privadas só são enviadas se
    # ENABLE_DEMO_EXECUTION=true E o chamador passar confirm_demo_execution=True.
    enable_demo_execution: bool = Field(
        default=False,
        description=(
            "Habilitar execução em Bybit Demo Trading? Deve ser false por padrão. "
            "Mesmo com TRADING_MODE=demo, esta flag DEVE ser true E a chamada "
            "deve incluir confirm_demo_execution=True explicitamente. "
            "Demo Trading usa endpoint https://api-demo.bybit.com (separado de testnet)."
        ),
    )

    # FASE 6 — Tipo de executor usado pelo BotEngine.
    # Aceita SOMENTE "paper" (default seguro) ou "testnet". NUNCA "live".
    # ⚠️  Isto NÃO substitui o triple-lock do testnet nem afrouxa live: mesmo
    #     com executor_type=testnet, o BybitTestnetExecutor ainda exige
    #     ENABLE_TESTNET_EXECUTION=true + confirm_testnet_execution=True.
    executor_type: Literal["paper", "testnet"] = Field(
        default="paper",
        description=(
            "Executor do BotEngine: 'paper' (default seguro) ou 'testnet'. "
            "'live' é REJEITADO — execução real de mainnet nunca é integrada ao "
            "BotEngine. Mesmo com 'testnet', o triple-lock do ModeGuard se aplica."
        ),
    )

    # FASE 8 — Identificador do provider consultado pelo ProviderRegistry.
    # Ortogonal a `executor_type` (que é wiring no BotEngine). `provider_id`
    # é METADATA + status no registry (paper ACTIVE, bybit RESTRICTED,
    # binance DRY_RUN_ONLY, cleo UNCONFIRMED). NÃO transforma nenhum provider
    # externo em default. PaperTrader continua o caminho default absoluto.
    # ⚠️  Valores mainnet/live são REJEITADOS no validator.
    provider_id: Literal[
        "paper",
        "bybit_testnet_linear",
        "bybit_demo_linear",
        "binance_futures_testnet",
        "hyrotrader_cleo_demo",
        "tealstreet_cli_gateway",
    ] = Field(
        default="paper",
        description=(
            "Provider ID consultado pelo ProviderRegistry. Default 'paper'. "
            "'live'/'mainnet'/'bybit_mainnet'/'binance_mainnet'/'hyrotrader_real' "
            "são REJEITADOS. Mudar este valor NÃO autoriza execução real — o "
            "registry + ModeGuard.assert_provider_allowed continuam soberanos."
        ),
    )

    # --- CAPITAL SIMULADO ---
    paper_trading_initial_balance: float = Field(
        default=5000.0,
        ge=100.0,
        description="Saldo inicial simulado para paper trading (USD)",
    )
    paper_trading_currency: str = Field(
        default="USDT",
        description="Moeda base do paper trading",
    )

    # --- PARÂMETROS GERAIS ---
    default_symbol: str = Field(
        default="BTCUSDT",
        description="Símbolo principal para trading",
    )
    default_timeframe: str = Field(
        default="15",
        description="Timeframe padrão em minutos (ex: 1, 5, 15, 60, 240, D)",
    )

    # --- LOGS ---
    log_level: str = Field(
        default="INFO",
        description="Nível de log: DEBUG | INFO | WARNING | ERROR | CRITICAL",
    )
    log_dir: Path = Field(
        default=Path("logs"),
        description="Diretório para arquivos de log",
    )
    log_retention_days: int = Field(
        default=30,
        ge=0,
        description="Reter logs por N dias (0 = sem rotação)",
    )

    @field_validator("trading_mode", mode="before")
    @classmethod
    def validate_trading_mode(cls, v: object) -> str:
        """Garante que o modo 'live' só seja aceito se explicitamente configurado.
        
        Aceita tanto strings quanto instâncias de TradingMode (enum).
        """
        # Se já for um enum TradingMode, retorna o valor diretamente
        if isinstance(v, TradingMode):
            return v.value
        valid = {m.value for m in TradingMode}
        str_v = str(v).lower()
        if str_v not in valid:
            raise ValueError(f"trading_mode inválido: '{v}'. Use: {valid}")
        return str_v

    @field_validator("executor_type", mode="before")
    @classmethod
    def validate_executor_type(cls, v: object) -> str:
        """
        FASE 6 — Garante que executor_type seja apenas 'paper' ou 'testnet'.

        'live' (e qualquer variante) é EXPLICITAMENTE rejeitado: a execução
        real de mainnet NUNCA é integrada ao BotEngine. Esta é uma trava de
        segurança independente do triple-lock de live (assert_live_allowed).
        """
        str_v = str(v).lower().strip()
        if str_v in {"live", "mainnet", "real", "production", "prod"}:
            raise ValueError(
                f"executor_type='{v}' é PROIBIDO. A execução live/mainnet nunca "
                "é integrada ao BotEngine. Use 'paper' (default) ou 'testnet'."
            )
        valid = {"paper", "testnet"}
        if str_v not in valid:
            raise ValueError(
                f"executor_type inválido: '{v}'. Use: {valid}"
            )
        return str_v

    @field_validator("provider_id", mode="before")
    @classmethod
    def validate_provider_id(cls, v: object) -> str:
        """
        FASE 8 — Rejeita valores mainnet/live independente de qualquer outro
        controle. Esta trava é INDEPENDENTE de trading_mode/executor_type.
        """
        str_v = str(v).lower().strip()
        forbidden = {
            "live", "mainnet", "real", "production", "prod",
            "bybit_mainnet", "binance_mainnet", "hyrotrader_real",
            "bybit_live", "binance_live",
        }
        if str_v in forbidden:
            raise ValueError(
                f"provider_id='{v}' é PROIBIDO. Providers mainnet/live nunca são "
                "integrados ao BotEngine. Use 'paper' (default), 'bybit_testnet_linear', "
                "'binance_futures_testnet' ou 'hyrotrader_cleo_demo'."
            )
        valid = {
            "paper", "bybit_testnet_linear", "bybit_demo_linear",
            "binance_futures_testnet", "hyrotrader_cleo_demo",
            "tealstreet_cli_gateway",
        }
        if str_v not in valid:
            raise ValueError(
                f"provider_id inválido: '{v}'. Use: {valid}"
            )
        return str_v

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = str(v).upper()
        if upper not in valid:
            raise ValueError(f"log_level inválido: '{v}'. Use: {valid}")
        return upper

    @property
    def is_paper_mode(self) -> bool:
        """Verdadeiro se o sistema está em modo paper trading."""
        return self.trading_mode == TradingMode.PAPER

    @property
    def is_testnet_mode(self) -> bool:
        """Verdadeiro se o sistema está em modo testnet."""
        return self.trading_mode == TradingMode.TESTNET

    @property
    def is_demo_mode(self) -> bool:
        """FASE 9 Fatia 2 — Verdadeiro se o sistema está em modo demo (Bybit Demo Trading)."""
        return self.trading_mode == TradingMode.DEMO

    @property
    def is_live_mode(self) -> bool:
        """Verdadeiro APENAS se trading_mode=live E enable_live_trading=true."""
        return (
            self.trading_mode == TradingMode.LIVE
            and self.enable_live_trading is True
        )

    @property
    def is_safe_mode(self) -> bool:
        """Verdadeiro se o sistema está em modo seguro (sem ordens reais)."""
        return not self.is_live_mode

    @property
    def is_testnet_execution_enabled(self) -> bool:
        """
        FASE 5 — Verdadeiro APENAS se trading_mode=testnet E enable_testnet_execution=true.

        Esta property é a base para ModeGuard.assert_testnet_execution_allowed.
        NÃO afeta is_live_mode nem afrouxa qualquer trava de live trading.
        """
        return (
            self.trading_mode == TradingMode.TESTNET
            and self.enable_testnet_execution is True
        )

    @property
    def is_demo_execution_enabled(self) -> bool:
        """
        FASE 9 Fatia 2 — Verdadeiro APENAS se trading_mode=demo E enable_demo_execution=true.

        Base para ModeGuard.assert_demo_execution_allowed.
        NÃO afeta is_live_mode nem afrouxa qualquer trava de live trading.
        NÃO afeta is_testnet_execution_enabled — demo e testnet são paralelos.
        """
        return (
            self.trading_mode == TradingMode.DEMO
            and self.enable_demo_execution is True
        )

    def __repr__(self) -> str:
        return (
            f"Settings(mode={self.trading_mode}, "
            f"symbol={self.default_symbol}, "
            f"live_enabled={self.enable_live_trading})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Retorna a instância singleton das configurações.

    Usa lru_cache para garantir que o .env seja lido apenas uma vez.
    Em testes, use: get_settings.cache_clear() para resetar o cache.
    """
    return Settings()
