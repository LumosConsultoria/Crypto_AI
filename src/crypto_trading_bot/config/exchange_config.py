"""
Configuração de Exchange
=========================
Parâmetros de conexão com exchanges de criptomoedas.

⚠️  SEGURANÇA:
    - Chaves de API são carregadas EXCLUSIVAMENTE via variáveis de ambiente.
    - Nunca coloque chaves diretamente neste arquivo.
    - Em modo paper, as chaves não são necessárias.
    - Em modo testnet, use APENAS chaves de testnet.
    - Em modo demo (Bybit Demo Trading), use APENAS chaves de demo.
    - Chaves de produção só são usadas se enable_live_trading=true.

⚠️  FATIA 1 (separação Demo vs Testnet):
    - `BYBIT_ENVIRONMENT` (testnet | demo) controla explicitamente o ambiente.
    - `BYBIT_USE_DEMO=true` é o atalho mais alto na precedência.
    - `BYBIT_USE_TESTNET` continua existindo para retrocompatibilidade.
    - Mainnet NÃO é selecionável via os campos novos — só pelo fallback
      legado de `use_testnet=False`, ainda sujeito a `assert_live_allowed`.
"""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field, field_validator, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Constantes públicas — endpoints REST da Bybit V5.
BYBIT_REST_URL_MAINNET = "https://api.bybit.com"
BYBIT_REST_URL_TESTNET = "https://api-testnet.bybit.com"
BYBIT_REST_URL_DEMO = "https://api-demo.bybit.com"

# WebSocket — demo trading usa o stream PÚBLICO da mainnet (dados de mercado
# reais), com stream PRIVADO próprio.
BYBIT_WS_PUBLIC_MAINNET = "wss://stream.bybit.com/v5/public"
BYBIT_WS_PUBLIC_TESTNET = "wss://stream-testnet.bybit.com/v5/public"
BYBIT_WS_PRIVATE_MAINNET = "wss://stream.bybit.com/v5/private"
BYBIT_WS_PRIVATE_TESTNET = "wss://stream-testnet.bybit.com/v5/private"
BYBIT_WS_PRIVATE_DEMO = "wss://stream-demo.bybit.com/v5/private"


class ExchangeConfig(BaseSettings):
    """
    Configuração de conexão com a Bybit.

    Chaves são carregadas do .env com prefixo BYBIT_.
    Em modo paper, as chaves são ignoradas e nenhuma conexão é feita.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BYBIT_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- CREDENCIAIS ---
    # Usam SecretStr para evitar exposição acidental em logs

    api_key: Optional[SecretStr] = Field(
        default=None,
        description=(
            "Chave de API da Bybit. "
            "Use APENAS chaves de testnet OU demo enquanto em fase de testes."
        ),
    )

    api_secret: Optional[SecretStr] = Field(
        default=None,
        description="Secret de API da Bybit. Nunca exponha este valor.",
    )

    # --- ENDPOINT ---

    use_testnet: bool = Field(
        default=True,
        description=(
            "(Legado) Usar endpoint de testnet da Bybit? "
            "Padrão: True. Em FASE 9-Fatia 1, sua precedência cai para 3º lugar — "
            "BYBIT_USE_DEMO e BYBIT_ENVIRONMENT têm prioridade."
        ),
    )

    # FASE 9 — Fatia 1: separação Demo Trading vs Testnet.
    # ⚠️  Mainnet NÃO é selecionável aqui. Para mainnet (read-only público),
    #     use o fallback legado use_testnet=False + assert_live_allowed para
    #     qualquer caminho privado.
    environment: Optional[Literal["testnet", "demo"]] = Field(
        default=None,
        description=(
            "Ambiente Bybit explícito. None → deduzir de use_demo/use_testnet. "
            "Aceita apenas 'testnet' ou 'demo'. Mainnet não é selecionável aqui."
        ),
    )

    use_demo: bool = Field(
        default=False,
        description=(
            "Atalho de PRECEDÊNCIA MÁXIMA: True força environment='demo' "
            "(https://api-demo.bybit.com). Default False mantém o comportamento "
            "anterior baseado em use_testnet."
        ),
    )

    # --- CONFIGURAÇÕES DE CONEXÃO ---

    recv_window: int = Field(
        default=5000,
        ge=1000,
        le=20000,
        description="Janela de tempo para requisições (ms). Padrão: 5000ms.",
    )

    request_timeout: int = Field(
        default=10,
        ge=1,
        le=60,
        description="Timeout para requisições HTTP (segundos).",
    )

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @field_validator("environment", mode="before")
    @classmethod
    def validate_environment(cls, v: object) -> Optional[str]:
        """Aceita só 'testnet'/'demo'/None. Rejeita 'mainnet' e variantes live."""
        if v is None or v == "":
            return None
        str_v = str(v).lower().strip()
        forbidden = {
            "mainnet", "main", "live", "production", "prod", "real",
        }
        if str_v in forbidden:
            raise ValueError(
                f"BYBIT_ENVIRONMENT='{v}' é PROIBIDO. Mainnet/live não é "
                "selecionável via este campo. Use 'testnet' ou 'demo'."
            )
        valid = {"testnet", "demo"}
        if str_v not in valid:
            raise ValueError(
                f"BYBIT_ENVIRONMENT inválido: '{v}'. Use: {valid} ou deixe vazio."
            )
        return str_v

    # -----------------------------------------------------------------------
    # Propriedades derivadas
    # -----------------------------------------------------------------------

    @property
    def resolved_environment(self) -> str:
        """
        Ambiente efetivo, com a precedência definida na Fatia 1:

            1. use_demo=True              → 'demo'
            2. environment definido       → o valor informado
            3. use_testnet=True (legado)  → 'testnet'
            4. caso contrário             → 'mainnet' (somente read-only público)

        Returns:
            "demo" | "testnet" | "mainnet"
        """
        if self.use_demo:
            return "demo"
        if self.environment is not None:
            return self.environment
        if self.use_testnet:
            return "testnet"
        return "mainnet"

    @property
    def is_demo(self) -> bool:
        """Verdadeiro se o ambiente resolvido é 'demo'."""
        return self.resolved_environment == "demo"

    @property
    def is_testnet(self) -> bool:
        """Verdadeiro se o ambiente resolvido é 'testnet'."""
        return self.resolved_environment == "testnet"

    @property
    def is_mainnet(self) -> bool:
        """
        Verdadeiro se o ambiente resolvido é 'mainnet' (legado/read-only).
        ⚠️  Endpoints PRIVADOS continuam bloqueados em mainnet pelo BybitClient.
        """
        return self.resolved_environment == "mainnet"

    @property
    def rest_url(self) -> str:
        """URL base da API REST conforme o ambiente resolvido."""
        env = self.resolved_environment
        if env == "demo":
            return BYBIT_REST_URL_DEMO
        if env == "testnet":
            return BYBIT_REST_URL_TESTNET
        return BYBIT_REST_URL_MAINNET

    @property
    def ws_url(self) -> str:
        """URL do WebSocket público. Demo usa o stream público da mainnet."""
        env = self.resolved_environment
        if env == "testnet":
            return BYBIT_WS_PUBLIC_TESTNET
        # demo e mainnet compartilham o stream público da mainnet
        return BYBIT_WS_PUBLIC_MAINNET

    @property
    def ws_private_url(self) -> str:
        """URL do WebSocket privado (autenticado) conforme o ambiente."""
        env = self.resolved_environment
        if env == "demo":
            return BYBIT_WS_PRIVATE_DEMO
        if env == "testnet":
            return BYBIT_WS_PRIVATE_TESTNET
        return BYBIT_WS_PRIVATE_MAINNET

    @property
    def has_credentials(self) -> bool:
        """Verdadeiro se as credenciais estão configuradas."""
        return (
            self.api_key is not None
            and self.api_secret is not None
            and self.api_key.get_secret_value() not in ("", "your_testnet_api_key_here")
            and self.api_secret.get_secret_value() not in ("", "your_testnet_api_secret_here")
        )

    def __repr__(self) -> str:
        """Representação segura — nunca expõe chaves."""
        return (
            f"ExchangeConfig("
            f"environment={self.resolved_environment}, "
            f"testnet={self.is_testnet}, "
            f"demo={self.is_demo}, "
            f"has_credentials={self.has_credentials}, "
            f"url={self.rest_url})"
        )


@lru_cache(maxsize=1)
def get_exchange_config() -> ExchangeConfig:
    """
    Retorna a instância singleton da configuração de exchange.

    Em testes, use: get_exchange_config.cache_clear() para resetar.
    """
    return ExchangeConfig()
