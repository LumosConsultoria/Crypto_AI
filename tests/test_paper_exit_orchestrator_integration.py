"""
PaperExitOrchestrator — Integração + invariantes (FASE 13)
============================================================
⚠️  100% offline. ZERO rede. ZERO API key. ZERO ordem.

Cobertura:
    - Construtor exige PaperTrader + ExitPolicy (tipos validados).
    - Sem posições abertas → retorna lista vazia.
    - Sem instanciar orquestrador, PaperTrader continua intocado.
    - on_candle não abre posição.
    - Properties read-only paper_trader e exit_policy.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy, PaperExitOrchestrator
from crypto_trading_bot.risk.risk_engine import RiskEngine

from tests.test_paper_trader import (
    _make_approved_risk_result,
    _make_valid_signal,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap(supports_ro: bool = True) -> ProviderCapability:
    return ProviderCapability(
        provider_id="paper", supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _trader() -> PaperTrader:
    return PaperTrader(
        risk_engine=RiskEngine(initial_capital=5000.0),
        exchange=MockExchange(initial_balance_usdt=5000.0),
    )


def _candle(close: float = 65000.0) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=close, high=close * 1.001, low=close * 0.999,
        close=close, volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Construtor
# ---------------------------------------------------------------------------

class TestConstructor:

    def test_requires_paper_trader(self):
        policy = ExitPolicy(provider_capability=_cap())
        with pytest.raises(TypeError, match="PaperTrader"):
            PaperExitOrchestrator("not_a_trader", policy)  # type: ignore[arg-type]

    def test_requires_exit_policy(self):
        trader = _trader()
        with pytest.raises(TypeError, match="ExitPolicy"):
            PaperExitOrchestrator(trader, "not_a_policy")  # type: ignore[arg-type]

    def test_properties_readonly(self):
        trader = _trader()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        assert orch.paper_trader is trader
        assert orch.exit_policy is policy


# ---------------------------------------------------------------------------
# Sem posições / sem efeito
# ---------------------------------------------------------------------------

class TestNoOpenPositions:

    def test_empty_returns_empty_list(self):
        trader = _trader()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(candle=_candle(), now=_NOW)
        assert decisions == []

    def test_trader_state_unchanged(self):
        trader = _trader()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        before_open = dict(trader.open_trades)
        before_closed = list(trader.closed_trades)
        orch.on_candle(candle=_candle(), now=_NOW)
        assert trader.open_trades == before_open
        assert trader.closed_trades == before_closed


# ---------------------------------------------------------------------------
# Sem instanciar o orquestrador, PaperTrader continua igual
# ---------------------------------------------------------------------------

class TestPaperTraderUnchangedWithoutOrchestrator:

    def test_execute_close_legacy_path_intact(self):
        trader = _trader()
        signal = _make_valid_signal()
        result = trader.execute(_make_approved_risk_result(signal))
        assert result.success
        trade_id = result.trade.trade_id
        # Fechamento manual legado continua funcionando sem snapshot
        close = trader.close_trade(trade_id, close_price=66000.0, reason="manual")
        assert close.success
        assert close.trade.exit_decision_snapshot is None

    def test_close_trade_accepts_snapshot_kwarg(self):
        trader = _trader()
        signal = _make_valid_signal()
        result = trader.execute(_make_approved_risk_result(signal))
        trade_id = result.trade.trade_id
        snap = {"reason": "stop_loss", "auto_execute_blocked": False}
        close = trader.close_trade(
            trade_id, close_price=63700.0, reason="stop_loss",
            exit_decision_snapshot=snap,
        )
        assert close.success
        assert close.trade.exit_decision_snapshot == snap
