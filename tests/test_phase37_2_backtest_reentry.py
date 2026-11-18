"""
FASE 37.2 - Backtest Lifecycle / Reentrada apos fechamento
==========================================================
Bug: o BacktestEngine nunca chamava strategy.on_trade_closed() ao fechar
um trade. Estrategias que rastreiam posicao internamente
(_has_open_position) ficavam presas em "posicao aberta" e nunca mais
geravam sinal -> apenas 1 trade por backtest inteiro.

Correcao (lifecycle): o engine agora notifica a estrategia no fechamento
(mesma notificacao que paper/live ja fazem), liberando a reentrada.
NAO altera RiskEngine, ModeGuard, piso 0.005 nem a logica das estrategias.

Testes 100% OFFLINE. ZERO rede / ordem / secret.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal
from crypto_trading_bot.strategies.trend_pullback_bidirectional_strategy \
    import build_trend_pullback_bidirectional_spec
from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
)
from tests.helpers import StubStrategy


_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _c(i: int, *, low: float, close: float = 65000.0) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15",
        timestamp=_BASE + timedelta(minutes=15 * i),
        open=65000.0, high=65010.0, low=low, close=close, volume=100.0,
    )


def _two_opportunity_series(n_pairs: int = 4):
    """Candles sinteticos com N oportunidades validas separadas por
    fechamento (cada par: candle de entrada + candle que estoura o stop
    de 64000, fechando o trade -> flat -> nova entrada)."""
    out = []
    # warmup flat suficiente p/ features.
    for i in range(60):
        out.append(_c(i, low=64990.0))
    idx = 60
    for _ in range(n_pairs):
        out.append(_c(idx, low=64990.0, close=65000.0))   # entrada
        idx += 1
        # estoura stop (low<=64000) mas FECHA acima do stop (64500) p/ que
        # uma eventual reentrada no mesmo candle seja valida (stop<entry).
        out.append(_c(idx, low=63900.0, close=64500.0))
        idx += 1
    return out


def _buy_signal():
    return StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="stub",
        entry_price=65000.0, stop_loss_price=64000.0,
        take_profit_price=67000.0, position_size_usd=200.0,
    )


def _engine(strategy, capital=100000.0, min_candles=50):
    return BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=capital),
        feature_engine=FeatureEngine(),
        initial_capital=capital, min_candles=min_candles, symbol="BTCUSDT",
    )


class TestReentryAfterClose:

    def test_two_opportunities_yield_at_least_two_trades(self):
        # Stub que LIBERA reentrada apos fechamento (block_after_trade=True
        # resetado por on_trade_closed; one_shot=False).
        strat = StubStrategy(
            signal=_buy_signal(), block_after_trade=True, one_shot=False)
        strat.set_running()
        candles = _two_opportunity_series(n_pairs=4)
        report = _engine(strat).run(candles)
        # Antes do fix: 1 trade (estrategia presa). Depois: reentra.
        assert report.total_trades >= 2, (
            f"reentrada falhou: {report.total_trades} trade(s)")
        # Todos fechados por stop_loss (cenario controlado).
        assert all(not t.is_open for t in report.trades)

    def test_engine_notifies_strategy_on_trade_closed(self):
        # Espia as chamadas de on_trade_closed feitas pelo engine.
        class _Spy(StubStrategy):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.closed_calls = []

            def on_trade_closed(self, symbol, pnl):
                self.closed_calls.append((symbol, pnl))
                super().on_trade_closed(symbol, pnl)

        spy = _Spy(signal=_buy_signal(), block_after_trade=True,
                   one_shot=False)
        spy.set_running()
        report = _engine(spy).run(_two_opportunity_series(n_pairs=3))
        # Engine notificou o fechamento ao menos uma vez por trade fechado.
        assert len(spy.closed_calls) >= 1
        assert len(spy.closed_calls) >= report.total_trades
        assert spy.closed_calls[0][0] == "BTCUSDT"

    def test_one_shot_stub_still_single_trade(self):
        # Regressao: stub one_shot continua com 1 trade (intencao dos
        # testes de parity/custos), mesmo com o engine notificando close.
        strat = StubStrategy(
            signal=_buy_signal(), block_after_trade=True, one_shot=True)
        strat.set_running()
        report = _engine(strat).run(_two_opportunity_series(n_pairs=4))
        assert report.total_trades == 1

    def test_real_strategy_reenters_on_multi_setup_data(self):
        # Cenario do operador: estrategia real (gating _has_open_position)
        # em dados com varios setups deve gerar >1 trade.
        spec = build_trend_pullback_bidirectional_spec()
        candles = generate_ranging_candles(
            1500, symbol="BTCUSDT", timeframe="15")
        report = _engine(
            spec.factory(dict(spec.default_config)), capital=5000.0,
            min_candles=60).run(candles)
        assert report.total_trades >= 2
