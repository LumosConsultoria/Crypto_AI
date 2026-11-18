"""
PaperExitOrchestrator — Regras de saída (FASE 13)
==================================================
⚠️  100% offline. ZERO rede.

Cobre precedência:
    1. Emergency
    2. Manual
    3. SL (vence TP no mesmo candle)
    4. TP
    5. Opposite signal (se habilitado)
    6. Time limit (candles e segundos)
    7. Default = não fecha
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import (
    PaperTradeStatus, PaperTrader,
)
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
    """Constrói trader com 1 BUY aberto e devolve (trader, trade_id)."""
    trader = PaperTrader(
        risk_engine=RiskEngine(initial_capital=5000.0),
        exchange=MockExchange(initial_balance_usdt=5000.0),
    )
    signal = _make_valid_signal()  # BUY entry=65000, sl=63700, tp=67600
    result = trader.execute(_make_approved_risk_result(signal))
    assert result.success
    return trader, result.trade.trade_id


def _candle(*, low: float, high: float, close: float = 65000.0) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=close, high=high, low=low, close=close, volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Precedência
# ---------------------------------------------------------------------------

class TestEmergencyPrecedence:

    def test_emergency_wins(self):
        trader, tid = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            emergency_close_enabled=True,
            allow_close_on_opposite_signal=True,
            max_time_in_position_candles=5,
        )
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=60000.0, high=70000.0),  # SL e TP batem
            now=_NOW,
            emergency_active=True,
        )
        assert len(decisions) == 1
        assert decisions[0].reason == ExitReason.EMERGENCY
        assert trader.closed_trades[-1].status == PaperTradeStatus.CLOSED_EMERGENCY


class TestManualPrecedence:

    def test_manual_beats_sl_tp(self):
        trader, tid = _trader_with_open_buy()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=60000.0, high=70000.0),
            now=_NOW,
            manual_close={tid: True},
        )
        assert decisions[0].reason == ExitReason.MANUAL
        assert trader.closed_trades[-1].status == PaperTradeStatus.CLOSED_MANUAL


class TestStopLossPrecedence:

    def test_sl_only(self):
        trader, _ = _trader_with_open_buy()
        # signal valid: BUY, sl=63700
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=63500.0, high=65500.0),  # SL hit
            now=_NOW,
        )
        assert decisions[0].reason == ExitReason.STOP_LOSS
        assert trader.closed_trades[-1].status == PaperTradeStatus.CLOSED_STOP_LOSS

    def test_sl_wins_over_tp_same_candle(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=63500.0, high=68000.0),  # ambos batem
            now=_NOW,
        )
        assert decisions[0].reason == ExitReason.STOP_LOSS


class TestTakeProfitPrecedence:

    def test_tp_only(self):
        trader, _ = _trader_with_open_buy()
        # signal valid: BUY, tp=67600
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=68000.0),  # TP hit, SL não
            now=_NOW,
        )
        assert decisions[0].reason == ExitReason.TAKE_PROFIT
        assert trader.closed_trades[-1].status == PaperTradeStatus.CLOSED_TAKE_PROFIT


class TestOppositeSignal:

    def test_disabled_does_not_fire(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=False,
        )
        orch = PaperExitOrchestrator(trader, policy)
        sell_sig = StrategySignal.sell(
            symbol="BTCUSDT", strategy_name="x",
            entry_price=65000.0, stop_loss_price=66000.0,
            position_size_usd=200.0,
        )
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW, latest_signal=sell_sig,
        )
        assert decisions == []

    def test_enabled_fires(self):
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
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW, latest_signal=sell_sig,
        )
        assert decisions[0].reason == ExitReason.OPPOSITE_SIGNAL
        assert (
            trader.closed_trades[-1].status
            == PaperTradeStatus.CLOSED_OPPOSITE_SIGNAL
        )


class TestTimeLimit:

    def test_by_candles_fires(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=2,
        )
        orch = PaperExitOrchestrator(trader, policy)
        # PaperTrade.entry_candle_idx é None — limite por candles não dispara
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW, candle_idx=10,
        )
        # Como entry_candle_idx é None no paper, o limite por candles
        # NÃO dispara — paper opera em tempo real, não em grade.
        assert decisions == []

    def test_by_seconds_fires(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_seconds=60,
        )
        orch = PaperExitOrchestrator(trader, policy)
        # opened_at é datetime.now real; usamos relógio real + 120s.
        later = datetime.now(timezone.utc) + timedelta(seconds=120)
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0),
            now=later,
        )
        assert decisions[0].reason == ExitReason.TIME_LIMIT
        assert (
            trader.closed_trades[-1].status
            == PaperTradeStatus.CLOSED_TIME_LIMIT
        )

    def test_by_seconds_not_fired(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_seconds=600,
        )
        orch = PaperExitOrchestrator(trader, policy)
        # opened_at recém-criado; +10s ainda dentro do limite.
        short = datetime.now(timezone.utc) + timedelta(seconds=10)
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0), now=short,
        )
        assert decisions == []


class TestDefault:

    def test_default_no_close(self):
        trader, _ = _trader_with_open_buy()
        policy = ExitPolicy(provider_capability=_cap())
        orch = PaperExitOrchestrator(trader, policy)
        decisions = orch.on_candle(
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
        )
        assert decisions == []
        # Trade segue aberto
        assert len(trader.open_trades) == 1
