"""
PaperExitOrchestrator — PnL coerente (FASE 13)
=================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - close_price escolhido pelo orquestrador bate com a regra documentada:
        STOP_LOSS   → signal.stop_loss_price
        TAKE_PROFIT → signal.take_profit_price
        TIME_LIMIT  → candle.close
        OPPOSITE    → candle.close
    - PnL calculado pelo PaperTrader.close_trade é coerente com close_price
      escolhido (orquestrador apenas decide preço; PaperTrader faz a conta).
    - SELL side coerente (PnL negativo para SL em SELL).
    - Snapshot anexado à trade fechada via orquestrador.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy, PaperExitOrchestrator,
)
from crypto_trading_bot.risk.risk_engine import OrderSide, RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.test_paper_trader import (
    _make_approved_risk_result,
    _make_valid_signal,
)


def _cap() -> ProviderCapability:
    return ProviderCapability(
        provider_id="paper", supports_market_order=True,
        supports_reduce_only=True,
    )


def _trader_with_open(side: OrderSide = OrderSide.BUY):
    trader = PaperTrader(
        risk_engine=RiskEngine(initial_capital=5000.0),
        exchange=MockExchange(initial_balance_usdt=5000.0),
    )
    signal = _make_valid_signal(side=side)
    result = trader.execute(_make_approved_risk_result(signal))
    assert result.success
    return trader, result.trade.trade_id, signal, result.trade


# ---------------------------------------------------------------------------
# close_price escolhido pelo orquestrador
# ---------------------------------------------------------------------------

class TestClosePriceRules:

    def test_sl_uses_signal_stop_loss_price(self):
        trader, _, sig, _ = _trader_with_open()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        sl_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=64000.0, high=64500.0, low=63500.0, close=63700.0,
            volume=1000.0,
        )
        orch.on_candle(candle=sl_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        # close_price deve ser exatamente o stop_loss do signal (preço teórico)
        assert closed.close_price == sig.stop_loss_price

    def test_tp_uses_signal_take_profit_price(self):
        trader, _, sig, _ = _trader_with_open()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        tp_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=66500.0, high=68000.0, low=64500.0, close=67800.0,
            volume=1000.0,
        )
        orch.on_candle(candle=tp_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        assert closed.close_price == sig.take_profit_price

    def test_time_limit_uses_candle_close(self):
        trader, _, sig, _ = _trader_with_open()
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_seconds=10,
        )
        orch = PaperExitOrchestrator(trader, policy)
        c = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=65500.0, high=65800.0, low=65200.0, close=65700.0,
            volume=1000.0,
        )
        later = datetime.now(timezone.utc) + timedelta(seconds=60)
        orch.on_candle(candle=c, now=later)
        closed = trader.closed_trades[-1]
        assert closed.close_price == c.close

    def test_opposite_signal_uses_candle_close(self):
        trader, _, sig, _ = _trader_with_open()
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        orch = PaperExitOrchestrator(trader, policy)
        c = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=65100.0, high=65500.0, low=64800.0, close=65300.0,
            volume=1000.0,
        )
        sell = StrategySignal.sell(
            symbol="BTCUSDT", strategy_name="x",
            entry_price=65000.0, stop_loss_price=66000.0,
            position_size_usd=200.0,
        )
        orch.on_candle(
            candle=c, now=datetime.now(timezone.utc), latest_signal=sell,
        )
        closed = trader.closed_trades[-1]
        assert closed.close_price == c.close


# ---------------------------------------------------------------------------
# PnL coerente com o close_price escolhido
# ---------------------------------------------------------------------------

class TestPnLCoherence:

    def test_buy_sl_pnl_negative_and_consistent(self):
        trader, _, sig, opened = _trader_with_open()
        entry_executed = opened.order_result.avg_fill_price or sig.entry_price
        qty = opened.order_result.filled_qty
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        sl_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=64000.0, high=64500.0, low=63500.0, close=63700.0,
            volume=1000.0,
        )
        orch.on_candle(candle=sl_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        # PnL_USD esperado: (close - entry) * qty
        expected_pnl = round((sig.stop_loss_price - entry_executed) * qty, 4)
        assert closed.pnl == expected_pnl
        assert closed.pnl < 0  # SL em BUY → perda

    def test_buy_tp_pnl_positive(self):
        trader, _, sig, opened = _trader_with_open()
        entry_executed = opened.order_result.avg_fill_price or sig.entry_price
        qty = opened.order_result.filled_qty
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        tp_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=66500.0, high=68000.0, low=64500.0, close=67800.0,
            volume=1000.0,
        )
        orch.on_candle(candle=tp_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        expected_pnl = round((sig.take_profit_price - entry_executed) * qty, 4)
        assert closed.pnl == expected_pnl
        assert closed.pnl > 0  # TP em BUY → lucro

    def test_sell_sl_pnl_negative(self):
        trader, _, sig, opened = _trader_with_open(side=OrderSide.SELL)
        entry_executed = opened.order_result.avg_fill_price or sig.entry_price
        qty = opened.order_result.filled_qty
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        # SELL SL: candle.high >= sl
        sl_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=65800.0, high=66500.0, low=65200.0, close=66400.0,
            volume=1000.0,
        )
        orch.on_candle(candle=sl_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        # SELL PnL: (entry - close) * qty
        expected_pnl = round((entry_executed - sig.stop_loss_price) * qty, 4)
        assert closed.pnl == expected_pnl
        assert closed.pnl < 0


class TestSnapshotAttached:

    def test_snapshot_attached_with_capability_field(self):
        trader, _, _, _ = _trader_with_open()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        sl_candle = Candle(
            symbol="BTCUSDT", timeframe="15",
            timestamp=datetime.now(timezone.utc),
            open=64000.0, high=64500.0, low=63500.0, close=63700.0,
            volume=1000.0,
        )
        orch.on_candle(candle=sl_candle, now=datetime.now(timezone.utc))
        closed = trader.closed_trades[-1]
        assert closed.exit_decision_snapshot is not None
        assert closed.exit_decision_snapshot["reason"] == "stop_loss"
        assert "capability_allows_auto_close" in closed.exit_decision_snapshot
        # capability ≠ autorização — não expor execution_allowed
        assert "execution_allowed" not in closed.exit_decision_snapshot
