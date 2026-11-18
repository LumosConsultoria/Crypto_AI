"""
FASE 37.3 - Semantica de limites diarios no backtest
=====================================================
Bug: DailyRiskState.reset_if_new_day() usava date.today() (relogio REAL).
No backtest tudo acontece "hoje" -> trades_today nunca reseta -> o
max_trades_per_day virava um limite GLOBAL do backtest inteiro (ex.: 10
trades em 6 meses) em vez de diario.

Correcao (sem enfraquecer risco): RiskEngine.set_simulation_date(d) deixa
o BacktestEngine informar a DATA SIMULADA do candle; o limite diario e o
PnL diario resetam por dia simulado. Em prod/paper/live nada muda
(sim_date None => date.today()). O report agrega blocked_reasons_summary.

Testes 100% OFFLINE. ZERO rede / ordem / secret.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    TradingSignal,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal
from tests.helpers import StubStrategy


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT", side=OrderSide.BUY, entry_price=65000.0,
        stop_loss_price=64000.0, position_size_usd=200.0,
        strategy_name="t", take_profit_price=67000.0,
    )


# ---------------------------------------------------------------------------
# RiskEngine: reset diario por data SIMULADA (sem enfraquecer risco)
# ---------------------------------------------------------------------------

class TestRiskEngineSimDate:

    def test_daily_limit_resets_by_sim_date(self):
        eng = RiskEngine(initial_capital=100000.0)
        cap = eng._config.max_trades_per_day
        eng.set_simulation_date(date(2026, 1, 1))
        # Abre ate o limite diario no dia 1.
        for _ in range(cap):
            r = eng.validate_signal(_signal())
            assert r.approved
            eng.record_trade_opened(_signal())
            eng.record_trade_closed("BTCUSDT", pnl=1.0, size_usd=200.0)
        # Proximo no MESMO dia: bloqueado por max_trades_today.
        blocked = eng.validate_signal(_signal())
        assert not blocked.approved
        assert blocked.block_reason.value == "max_trades_today"
        # Vira o dia simulado -> contador reseta -> aprova de novo.
        reset = eng.set_simulation_date(date(2026, 1, 2))
        assert reset is True
        assert eng.validate_signal(_signal()).approved

    def test_no_sim_date_uses_real_today(self):
        # Sem set_simulation_date, comportamento de producao inalterado:
        # o estado usa date.today() (nenhuma data simulada injetada).
        eng = RiskEngine(initial_capital=100000.0)
        assert eng._sim_date is None
        assert eng.daily_state.date == date.today()


# ---------------------------------------------------------------------------
# BacktestEngine: limite diario reseta por dia simulado
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _c(i: int, low: float, close: float = 65000.0) -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15",
        timestamp=_BASE + timedelta(minutes=15 * i),
        open=65000.0, high=65010.0, low=low, close=close, volume=100.0,
    )


def _multi_day_series(pairs: int = 60):
    """warmup + 'pairs' ciclos entrada/stop (96 candles/dia => abrange
    >1 dia simulado)."""
    out = [_c(i, 64990.0) for i in range(60)]
    idx = 60
    for _ in range(pairs):
        out.append(_c(idx, 64990.0, 65000.0)); idx += 1
        out.append(_c(idx, 63900.0, 64500.0)); idx += 1
    return out


def _engine(strategy, capital=1_000_000.0):
    return BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=capital),
        feature_engine=FeatureEngine(),
        initial_capital=capital, min_candles=50, symbol="BTCUSDT",
    )


def _buy_stub():
    sig = StrategySignal.buy(
        symbol="BTCUSDT", strategy_name="stub", entry_price=65000.0,
        stop_loss_price=64000.0, take_profit_price=67000.0,
        position_size_usd=200.0)
    s = StubStrategy(signal=sig, block_after_trade=True, one_shot=False)
    s.set_running()
    return s


class TestBacktestDailyReset:

    def test_trades_occur_on_multiple_days(self):
        candles = _multi_day_series(pairs=60)
        report = _engine(_buy_stub()).run(candles)
        cap = RiskEngine(initial_capital=1.0)._config.max_trades_per_day
        # Limite e DIARIO: total deve superar o cap (varios dias),
        # provando que nao virou limite global do backtest.
        assert report.total_trades > cap, (
            f"esperado > {cap} trades em multiplos dias, "
            f"obtido {report.total_trades}")
        trade_dates = sorted({t.entry_time.date() for t in report.trades})
        assert len(trade_dates) >= 2, (
            f"trades em apenas {trade_dates} (reset diario falhou)")

    def test_day1_cap_does_not_block_day2(self):
        candles = _multi_day_series(pairs=60)
        report = _engine(_buy_stub()).run(candles)
        cap = RiskEngine(initial_capital=1.0)._config.max_trades_per_day
        by_day = {}
        for t in report.trades:
            by_day.setdefault(t.entry_time.date(), 0)
            by_day[t.entry_time.date()] += 1
        days = sorted(by_day)
        # Cada dia respeita o cap diario (<=) e o dia 2 abriu trades.
        assert all(v <= cap for v in by_day.values())
        assert by_day[days[1]] >= 1

    def test_blocked_reasons_summary_populated(self):
        candles = _multi_day_series(pairs=60)
        report = _engine(_buy_stub()).run(candles)
        d = report.to_dict()
        assert "risk_blocked_reasons" in d
        # O cap diario gera bloqueios categorizados como max_trades_today.
        assert d["risk_blocked_reasons"].get("max_trades_today", 0) > 0
        assert report.risk_blocked_count == sum(
            report.risk_blocked_reasons.values())


# ---------------------------------------------------------------------------
# Report operacional expoe blocked_reasons_summary
# ---------------------------------------------------------------------------

class TestOperationalBlockedSummary:

    def test_operational_report_has_blocked_reasons_summary(self):
        from crypto_trading_bot.backtest_operational import (
            BacktestExecutionContext, run_operational_backtest,
        )
        candles = _multi_day_series(pairs=60)
        ctx = BacktestExecutionContext(
            strategy="trend_pullback_bidirectional", capital_usd=1_000_000.0)
        rep = run_operational_backtest(
            ctx, candles, symbol="BTCUSDT", timeframe="15m",
            source_type="synthetic_fake")
        d = rep.to_dict()
        assert "blocked_reasons_summary" in d["results"]
        # estrutura presente (pode ou nao ter blocks dependendo do setup).
        assert isinstance(d["results"]["blocked_reasons_summary"], dict)
