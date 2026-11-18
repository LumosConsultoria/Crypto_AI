"""
Testes do ExchangeConfig — FASE 9 Fatia 1 (Demo Trading vs Testnet)
======================================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede.

Cobertura:
    - Precedência de resolução de ambiente:
        1) BYBIT_USE_DEMO=true → 'demo' (precedência máxima)
        2) BYBIT_ENVIRONMENT explícito → o valor informado
        3) BYBIT_USE_TESTNET (legado) → 'testnet' ou 'mainnet'
    - URLs corretas (REST + WS público + WS privado) por ambiente.
    - 'mainnet'/'live'/'production' rejeitados em BYBIT_ENVIRONMENT.
    - Defaults seguros: testnet (legado preservado).
    - has_credentials estável (sem alterar valores reais).
    - __repr__ não expõe valores de chave.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from crypto_trading_bot.config.exchange_config import (
    BYBIT_REST_URL_DEMO,
    BYBIT_REST_URL_MAINNET,
    BYBIT_REST_URL_TESTNET,
    BYBIT_WS_PRIVATE_DEMO,
    BYBIT_WS_PRIVATE_MAINNET,
    BYBIT_WS_PRIVATE_TESTNET,
    BYBIT_WS_PUBLIC_MAINNET,
    BYBIT_WS_PUBLIC_TESTNET,
    ExchangeConfig,
)


def _cfg(**kwargs) -> ExchangeConfig:
    """Constrói um ExchangeConfig isolado do .env real."""
    return ExchangeConfig(_env_file=None, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Precedência: use_demo > environment > use_testnet (legado)
# ---------------------------------------------------------------------------

class TestPrecedence:

    def test_use_demo_true_forces_demo_even_when_testnet_true(self):
        c = _cfg(use_demo=True, use_testnet=True, environment="testnet")
        assert c.resolved_environment == "demo"
        assert c.is_demo is True

    def test_environment_demo_resolves_demo(self):
        c = _cfg(environment="demo")
        assert c.resolved_environment == "demo"

    def test_environment_testnet_resolves_testnet(self):
        c = _cfg(environment="testnet")
        assert c.resolved_environment == "testnet"
        assert c.is_testnet is True

    def test_legacy_use_testnet_true_resolves_testnet(self):
        c = _cfg(use_testnet=True)
        assert c.resolved_environment == "testnet"
        assert c.is_testnet is True

    def test_legacy_use_testnet_false_resolves_mainnet(self):
        c = _cfg(use_testnet=False)
        assert c.resolved_environment == "mainnet"
        assert c.is_mainnet is True

    def test_environment_overrides_use_testnet_when_set(self):
        # environment='demo' tem precedência sobre use_testnet=True
        c = _cfg(environment="demo", use_testnet=True)
        assert c.resolved_environment == "demo"

    def test_use_demo_false_falls_through_to_environment(self):
        c = _cfg(use_demo=False, environment="testnet")
        assert c.resolved_environment == "testnet"

    def test_default_is_testnet(self):
        c = _cfg()
        # use_testnet=True por default; nenhum atalho ativado
        assert c.resolved_environment == "testnet"


# ---------------------------------------------------------------------------
# URLs por ambiente resolvido
# ---------------------------------------------------------------------------

class TestUrls:

    def test_rest_url_demo(self):
        c = _cfg(environment="demo")
        assert c.rest_url == BYBIT_REST_URL_DEMO
        assert "api-demo.bybit.com" in c.rest_url

    def test_rest_url_testnet(self):
        c = _cfg(environment="testnet")
        assert c.rest_url == BYBIT_REST_URL_TESTNET
        assert "api-testnet.bybit.com" in c.rest_url

    def test_rest_url_mainnet_legacy(self):
        c = _cfg(use_testnet=False)
        assert c.rest_url == BYBIT_REST_URL_MAINNET
        assert "testnet" not in c.rest_url
        assert "demo" not in c.rest_url

    def test_ws_public_demo_uses_mainnet_stream(self):
        # Demo Trading da Bybit reutiliza o stream público da mainnet
        # (dados de mercado reais).
        c = _cfg(use_demo=True)
        assert c.ws_url == BYBIT_WS_PUBLIC_MAINNET

    def test_ws_public_testnet(self):
        c = _cfg(environment="testnet")
        assert c.ws_url == BYBIT_WS_PUBLIC_TESTNET

    def test_ws_private_demo_uses_dedicated_stream(self):
        c = _cfg(use_demo=True)
        assert c.ws_private_url == BYBIT_WS_PRIVATE_DEMO
        assert "stream-demo.bybit.com" in c.ws_private_url

    def test_ws_private_testnet(self):
        c = _cfg(environment="testnet")
        assert c.ws_private_url == BYBIT_WS_PRIVATE_TESTNET

    def test_ws_private_mainnet_legacy(self):
        c = _cfg(use_testnet=False)
        assert c.ws_private_url == BYBIT_WS_PRIVATE_MAINNET


# ---------------------------------------------------------------------------
# Rejeição de valores mainnet/live em BYBIT_ENVIRONMENT
# ---------------------------------------------------------------------------

class TestForbiddenEnvironmentValues:

    @pytest.mark.parametrize("forbidden", [
        "mainnet", "main", "live", "production", "prod", "real",
        "MAINNET", "Live",
    ])
    def test_rejects_mainnet_like_values(self, forbidden):
        with pytest.raises(ValidationError):
            _cfg(environment=forbidden)

    @pytest.mark.parametrize("invalid", ["typo", "demoo", "test"])
    def test_rejects_invalid_strings(self, invalid):
        with pytest.raises(ValidationError):
            _cfg(environment=invalid)

    def test_empty_environment_is_treated_as_none(self):
        c = _cfg(environment="")
        # default use_testnet=True ⇒ testnet
        assert c.resolved_environment == "testnet"


# ---------------------------------------------------------------------------
# has_credentials e __repr__
# ---------------------------------------------------------------------------

class TestCredentialsAndRepr:

    def test_no_credentials_by_default(self):
        c = _cfg()
        assert c.has_credentials is False

    def test_placeholder_credentials_treated_as_absent(self):
        c = _cfg(
            api_key=SecretStr("your_testnet_api_key_here"),
            api_secret=SecretStr("your_testnet_api_secret_here"),
        )
        assert c.has_credentials is False

    def test_real_looking_credentials_present(self):
        c = _cfg(
            api_key=SecretStr("AKEY_TEST_xxx"),
            api_secret=SecretStr("ASEC_TEST_yyy"),
        )
        assert c.has_credentials is True

    def test_repr_never_leaks_secret(self):
        FAKE = "TOKEN_SHOULD_NEVER_APPEAR_XYZ"
        c = _cfg(
            api_key=SecretStr(FAKE),
            api_secret=SecretStr(FAKE),
            environment="demo",
        )
        r = repr(c)
        assert FAKE not in r
        # Mas marca o ambiente para auditabilidade
        assert "environment=demo" in r
        assert "has_credentials=True" in r
