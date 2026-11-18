"""
Matriz de providers — capability ≠ autorização (FASE 11)
=========================================================
⚠️  100% offline. Constrói ProviderCapability localmente para refletir
    o estado declarado no ProviderRegistry, SEM importá-lo nem chamar
    rede. Nenhum provider é promovido aqui.

Esta matriz prova:
    - Bybit Demo:        supports_reduce_only=False → auto_blocked=True
    - Bybit Testnet:     supports_reduce_only=False → auto_blocked=True
    - Binance Testnet:   supports_reduce_only=True  → auto_blocked=False
                         **MAS:** isso é APENAS camada de capability —
                         execução real continua dependendo de
                         ProviderStatus + ModeGuard + integração futura.
    - Tealstreet:        supports_reduce_only=False → auto_blocked=True
    - HyroTrader CLEO:   supports_reduce_only=False → auto_blocked=True
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy,
    OpenPositionState,
    PositionSide,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Snapshot da matriz de capability (espelha src/, lido somente para teste)
# ---------------------------------------------------------------------------
# Tupla (provider_id, supports_reduce_only_expected)
_PROVIDER_MATRIX: Tuple[Tuple[str, bool], ...] = (
    ("bybit_demo_linear", False),
    ("bybit_testnet_linear", False),
    ("binance_futures_testnet", True),
    ("tealstreet_cli_gateway", False),
    ("hyrotrader_cleo_demo", False),
)


def _cap(provider_id: str, supports_ro: bool) -> ProviderCapability:
    """Constrói capability local — não chama ProviderRegistry."""
    return ProviderCapability(
        provider_id=provider_id,
        supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _buy_pos() -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT", side=PositionSide.BUY,
        entry_price=65000.0, entry_time=_NOW,
        stop_loss_price=64000.0, take_profit_price=67000.0,
        position_size_usd=200.0, entry_candle_idx=10,
    )


def _sl_candle() -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=64500.0, high=65000.0, low=63500.0, close=64000.0,
        volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Matriz parametrizada
# ---------------------------------------------------------------------------

class TestProviderMatrix:

    @pytest.mark.parametrize("provider_id,supports_ro", _PROVIDER_MATRIX)
    def test_auto_execute_blocked_reflects_capability(
        self, provider_id: str, supports_ro: bool
    ):
        policy = ExitPolicy(
            provider_capability=_cap(provider_id, supports_ro),
        )
        d = policy.evaluate(
            position=_buy_pos(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        assert d.should_close is True
        # auto_execute_blocked == NOT supports_reduce_only (camada técnica)
        assert d.auto_execute_blocked is (not supports_ro), (
            f"{provider_id}: auto_execute_blocked esperado "
            f"{not supports_ro}, obtido {d.auto_execute_blocked}"
        )
        assert d.metadata["capability_allows_auto_close"] is supports_ro
        assert d.metadata["provider_id"] == provider_id


class TestBybitDemoStaysManual:

    def test_bybit_demo_close_must_be_manual_or_future_gated(self):
        """
        Capability do Bybit Demo NÃO suporta reduceOnly →
        auto-close por API permanece bloqueado nesta fase.
        Fechamento da Bybit Demo continua manual pela UI ou
        atrás de gate de fase futura.
        """
        policy = ExitPolicy(
            provider_capability=_cap("bybit_demo_linear", supports_ro=False),
        )
        d = policy.evaluate(
            position=_buy_pos(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        assert d.auto_execute_blocked is True


class TestBinanceCapabilityIsNotPromotion:

    def test_binance_capability_true_but_not_execution_authorization(self):
        """
        Mesmo com supports_reduce_only=True, a Binance Futures Testnet
        continua DRY_RUN_ONLY no ProviderRegistry. A ExitPolicy reporta
        a camada técnica, mas a documentação e os testes deixam claro:
        execução real depende de ProviderStatus + ModeGuard + fase futura.

        Aqui validamos especificamente que:
            - metadata expõe capability_allows_auto_close
            - metadata NÃO expõe execution_allowed
            - metadata NÃO promove o provider
        """
        policy = ExitPolicy(
            provider_capability=_cap("binance_futures_testnet", supports_ro=True),
        )
        d = policy.evaluate(
            position=_buy_pos(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        # Camada técnica
        assert d.auto_execute_blocked is False
        # Mas nada na decisão promove ou autoriza
        assert "execution_allowed" not in d.metadata
        assert "provider_status" not in d.metadata
        assert "mode_guard_passed" not in d.metadata
        # Apenas registra o provider_id e a flag técnica
        assert d.metadata["capability_allows_auto_close"] is True
        assert d.metadata["provider_id"] == "binance_futures_testnet"


class TestExitPolicyDoesNotImportProviders:

    def test_exit_policy_module_does_not_import_real_providers(self):
        import crypto_trading_bot.exit_policy.exit_policy as ep_mod
        src = open(ep_mod.__file__, "r", encoding="utf-8").read()
        forbidden = [
            "from crypto_trading_bot.execution.providers",
            "from crypto_trading_bot.execution.provider_registry",
        ]
        for line in forbidden:
            assert line not in src, (
                f"ExitPolicy deve permanecer provider-agnostic: {line}"
            )
