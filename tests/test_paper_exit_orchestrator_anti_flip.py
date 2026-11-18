"""
PaperExitOrchestrator — Anti-flip e invariantes de fechamento (FASE 13)
========================================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Orquestrador NUNCA abre posição.
    - Opposite signal só FECHA — não dispara entry oposta.
    - record_trade_closed é chamado via close_trade (RiskEngine notificado).
    - record_trade_opened NÃO é chamado pelo orquestrador.
    - Inspeção estrutural: orquestrador não importa BybitClient/executors/httpx.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy, ExitReason, PaperExitOrchestrator,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.test_paper_trader import (
    _make_approved_risk_result,
    _make_valid_signal,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap() -> ProviderCapability:
    return ProviderCapability(
        provider_id="paper", supports_market_order=True,
        supports_reduce_only=True,
    )


def _trader_with_open_buy() -> tuple[PaperTrader, str]:
    trader = PaperTrader(
        risk_engine=RiskEngine(initial_capital=5000.0),
        exchange=MockExchange(initial_balance_usdt=5000.0),
    )
    signal = _make_valid_signal()
    result = trader.execute(_make_approved_risk_result(signal))
    return trader, result.trade.trade_id


def _candle() -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=65000.0, high=65500.0, low=64500.0, close=65000.0,
        volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Orquestrador nunca abre
# ---------------------------------------------------------------------------

class TestNeverOpens:

    def test_opposite_signal_only_closes(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        orch = PaperExitOrchestrator(trader, policy)
        sell_sig = StrategySignal.sell(
            symbol="BTCUSDT", strategy_name="x",
            entry_price=65000.0, stop_loss_price=66000.0,
            position_size_usd=200.0,
        )
        n_open_before = len(trader.open_trades)
        n_closed_before = len(trader.closed_trades)

        decisions = orch.on_candle(
            candle=_candle(), now=_NOW, latest_signal=sell_sig,
        )

        assert decisions[0].reason == ExitReason.OPPOSITE_SIGNAL
        # NÃO há nova posição aberta — orquestrador só fecha
        assert len(trader.open_trades) == n_open_before - 1
        assert len(trader.closed_trades) == n_closed_before + 1


class TestRiskEngineNotifications:

    def test_record_trade_closed_called_via_close_trade(self):
        trader, _ = _trader_with_open_buy()
        # spy em record_trade_closed
        original_closed = trader._risk_engine.record_trade_closed
        calls_closed: list[dict] = []

        def spy_closed(**kw):
            calls_closed.append(kw)
            return original_closed(**kw)

        original_opened = trader._risk_engine.record_trade_opened
        calls_opened: list = []

        def spy_opened(signal):
            calls_opened.append(signal)
            return original_opened(signal)

        with patch.object(
            trader._risk_engine, "record_trade_closed", side_effect=spy_closed
        ), patch.object(
            trader._risk_engine, "record_trade_opened", side_effect=spy_opened
        ):
            policy = ExitPolicy(provider_capability=_cap())
            orch = PaperExitOrchestrator(trader, policy)
            decisions = orch.on_candle(
                candle=Candle(
                    symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
                    open=64000.0, high=64500.0, low=63500.0, close=63700.0,
                    volume=1000.0,
                ),
                now=_NOW,
            )
            assert len(decisions) == 1

        # record_trade_closed chamado exatamente 1 vez (via close_trade)
        assert len(calls_closed) == 1
        # record_trade_opened NÃO chamado pelo orquestrador
        assert calls_opened == []


# ---------------------------------------------------------------------------
# Inspeção estrutural: paper_session não importa BybitClient/httpx
# ---------------------------------------------------------------------------

class TestStructuralIsolation:

    def _src(self) -> str:
        import crypto_trading_bot.exit_policy.paper_session as ps
        return open(ps.__file__, "r", encoding="utf-8").read()

    def test_no_bybit_client_import(self):
        src = self._src()
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "import crypto_trading_bot.exchange.bybit_client" not in src

    def test_no_executor_imports(self):
        src = self._src()
        forbidden = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
        ]
        for line in forbidden:
            assert line not in src

    def test_no_httpx(self):
        src = self._src()
        assert "import httpx" not in src
        assert "from httpx" not in src

    def test_no_api_credentials(self):
        src = self._src().lower()
        for tok in ("api_key", "api_secret", "x-bapi", "bearer "):
            assert tok not in src, f"paper_session.py não deve mencionar {tok!r}"
