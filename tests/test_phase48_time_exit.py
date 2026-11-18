"""
FASE 48 — saida por TEMPO (max_holding_candles) no BacktestEngine.
100% OFFLINE. Aditivo: default None preserva o legado; quando setado, fecha
por TIME_LIMIT no close se nem SL nem TP dispararem. Compativel com 1 posicao.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_trade import CloseReason
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


class _OneShotStrategy:
    """Emite 1 BUY no 1o candle elegivel com SL/TP MUITO largos (nunca batem)
    => so a saida por tempo pode fechar."""
    name = "oneshot"

    def __init__(self):
        self._done = False
        self._open = False

    def on_signal_approved(self, signal):
        self._open = True

    def on_signal_rejected(self, signal, reason):
        pass

    def on_trade_closed(self, symbol, pnl):
        self._open = False

    def reset(self):
        self._open = False

    def generate_signal(self, md):
        return None

    def evaluate(self, features):
        if self._open or self._done:
            return StrategySignal.hold(symbol="BTCUSDT", strategy_name=self.name,
                                       reason="hold")
        ts = features.get("timestamps")
        last = features.get("last_close", 100.0)
        if ts is None or len(ts) < 1:
            return StrategySignal.hold(symbol="BTCUSDT",
                                       strategy_name=self.name, reason="warmup")
        self._done = True
        # SL 4% (<=5% do RiskEngine) / TP 50% — nenhum bate no fixture flat
        # (low=99.5, high=100.5) => so a saida por TEMPO pode fechar.
        return StrategySignal.buy(
            symbol="BTCUSDT", strategy_name=self.name, entry_price=last,
            stop_loss_price=round(last * 0.96, 2),
            take_profit_price=round(last * 1.50, 2),
            position_size_usd=500.0, leverage=1.0)


def _flat_candles(n=80):
    return [Candle(symbol="BTCUSDT", timeframe="4h",
                   timestamp=_D0 + timedelta(hours=4 * i),
                   open=100.0, high=100.5, low=99.5, close=100.0,
                   volume=10.0) for i in range(n)]


def _run(max_holding):
    eng = BacktestEngine(
        strategy=_OneShotStrategy(),
        risk_engine=RiskEngine(initial_capital=5000.0),
        initial_capital=5000.0, min_candles=5, symbol="BTCUSDT",
        max_holding_candles=max_holding)
    return eng.run(_flat_candles())


def test_time_exit_closes_after_max_holding():
    rep = _run(max_holding=10)
    assert rep.total_trades == 1
    t = rep.trades[0]
    assert t.close_reason == CloseReason.TIME_LIMIT
    # fechou ~10 barras apos a entrada
    assert (t.exit_candle_idx - t.entry_candle_idx) == 10


def test_no_time_exit_when_none_legacy():
    # default None => sem time-exit; posicao so e fechada no FIM dos dados
    # (NUNCA por TIME_LIMIT), segurando muito alem de 10 barras (legado).
    rep = _run(max_holding=None)
    assert rep.total_trades == 1
    t = rep.trades[0]
    assert t.close_reason != CloseReason.TIME_LIMIT
    assert (t.exit_candle_idx - t.entry_candle_idx) > 10


def test_invalid_max_holding_raises():
    import pytest
    with pytest.raises(ValueError):
        BacktestEngine(strategy=_OneShotStrategy(),
                       risk_engine=RiskEngine(initial_capital=5000.0),
                       max_holding_candles=0)
