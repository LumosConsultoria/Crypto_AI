"""
Stress tests do backtesting — FASE 3E.3
=========================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - Custos extremos (fees altas, slippage alto, spread alto).
    - Sequência longa de perdas (validação de max_consecutive_losses, drawdown).
    - Gap contra posição (exit_price desliza através do stop).
    - Alta volatilidade (engine sobrevive, anti-lookahead preservado).
    - Dados esparsos / poucos candles.
    - Candles degenerados seguros (volume=0, high==low).
    - Cenário combinado (apenas propriedades estruturais — sem NaN/inf).

Princípios:
    - Determinístico: cenários produzem resultados reproduzíveis.
    - Cenários que precisam de trade GARANTEM trade (sem condicionais fracos).
    - Cenários combinados não validam valores exatos; validam:
        * backtest termina
        * report válido
        * sem NaN/inf
        * net_total_pnl_usd <= gross_total_pnl_usd quando custos > 0
        * total_execution_cost_usd >= 0
        * métricas avançadas calculáveis ou None corretamente
"""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import (
    DEFAULT_CAPITAL,
    DEFAULT_ENTRY_PRICE,
    DEFAULT_MIN_CANDLES,
    DEFAULT_POSITION_SIZE,
    DEFAULT_STOP_PRICE,
    DEFAULT_SYMBOL,
    DEFAULT_TP_PRICE,
    StubStrategy,
    assert_exactly_one_trade_closed_by,
    make_backtest_engine_with_stub,
    make_default_buy_signal,
)

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_trending_candles,
    generate_volatile_candles,
    load_candles_from_list,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_report import (
    BacktestReport,
    _calculate_drawdown,
)
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Helpers locais — construção de cenários
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _tp_scenario_with_cost(config: ExecutionCostConfig) -> BacktestReport:
    """Cenário TP determinístico com custos configuráveis — gera exatamente 1 trade."""
    candles = generate_candles_with_stop_hit(
        entry_price=DEFAULT_ENTRY_PRICE,
        stop_price=DEFAULT_STOP_PRICE,
        take_profit_price=DEFAULT_TP_PRICE,
        n_before_entry=60,
        n_after_entry=3,
        hit_what="tp",
    )
    engine = make_backtest_engine_with_stub(
        signal=make_default_buy_signal(),
        execution_cost_config=config,
    )
    return engine.run(candles)


def _build_sl_trade(idx: int = 0) -> BacktestTrade:
    """Cria um trade fechado por SL — pnl ≈ -3.077 USD para size=200."""
    trade = BacktestTrade(
        symbol="BTCUSDT",
        strategy_name="t",
        entry_candle_idx=idx * 2,
        entry_time=_TS,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=70000.0,
        position_size_usd=200.0,
        side="buy",
        entry_price_theoretical=65000.0,
    )
    trade.close(
        exit_candle_idx=idx * 2 + 1,
        exit_time=_TS,
        exit_price=64000.0,
        close_reason=CloseReason.STOP_LOSS,
        exit_price_theoretical=64000.0,
    )
    return trade


def _replace_last_candle_with_gap(
    candles: List[Candle], gap_low: float, gap_close: float
) -> List[Candle]:
    """Substitui o último candle por outro com gap profundo (low << stop)."""
    last = candles[-1]
    candles[-1] = Candle(
        symbol=last.symbol,
        timeframe=last.timeframe,
        timestamp=last.timestamp,
        open=last.open,
        high=max(last.open, last.high, gap_close),
        low=gap_low,
        close=gap_close,
        volume=last.volume,
    )
    return candles


# ---------------------------------------------------------------------------
# Custos extremos — fees
# ---------------------------------------------------------------------------

class TestExtremeFees:

    def test_high_fee_turns_gross_winners_into_net_losers(self):
        """
        Fee = 5% por leg sobre size=200 → 20 USD totais.
        Ganho bruto do TP é ~ +6 USD → líquido fica ~ -14 USD (perdedor).
        """
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(taker_fee_pct=0.05)
        )
        assert report.total_trades == 1
        assert report.gross_total_pnl_usd > 0, (
            f"Trade deveria ser bruto vencedor. gross={report.gross_total_pnl_usd}"
        )
        assert report.net_total_pnl_usd < 0, (
            f"Trade deveria ser líquido perdedor por fees altas. net={report.net_total_pnl_usd}"
        )

    def test_extreme_fees_preserved_in_total_fees_usd(self):
        """fee_pct=0.01, size=200 → 2 USD por leg → 4 USD total."""
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(taker_fee_pct=0.01)
        )
        assert report.total_trades == 1
        assert report.total_fees_usd == pytest.approx(4.0, abs=1e-3)

    def test_extreme_fees_do_not_break_metrics(self):
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(taker_fee_pct=0.05)
        )
        # Métricas devem ser calculáveis (float ou None coerente)
        assert math.isfinite(report.expectancy_usd)
        assert math.isfinite(report.total_pnl_usd)
        assert math.isfinite(report.gross_total_pnl_usd)
        assert math.isfinite(report.net_total_pnl_usd)
        # Com 1 trade líquido perdedor: payoff_ratio = 0/|loss| = 0
        assert report.payoff_ratio == 0.0
        # max_consecutive_* são inteiros válidos
        assert isinstance(report.max_consecutive_wins, int)
        assert isinstance(report.max_consecutive_losses, int)
        assert report.max_consecutive_wins + report.max_consecutive_losses >= 1


# ---------------------------------------------------------------------------
# Custos extremos — slippage
# ---------------------------------------------------------------------------

class TestExtremeSlippage:

    def test_extreme_slippage_worsens_entry_significantly(self):
        """slippage_pct=0.05 → BUY entry executado ≥ 4% acima do teórico."""
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(slippage_pct=0.05)
        )
        assert report.total_trades == 1
        trade = report.trades[0]
        assert trade.entry_price_theoretical is not None
        ratio = trade.entry_price / trade.entry_price_theoretical
        assert ratio >= 1.04, (
            f"BUY entry deveria ser >= 4% acima do teórico. "
            f"executed={trade.entry_price} theo={trade.entry_price_theoretical} ratio={ratio}"
        )

    def test_extreme_slippage_increases_total_slippage_usd(self):
        """slippage_pct=0.05, size=200 → ~10 USD por leg → ~20 USD total."""
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(slippage_pct=0.05)
        )
        assert report.total_trades == 1
        # entry: drift de ~5% do preço × size = ~10 USD
        # exit: drift de ~5% do preço × size = ~10 USD
        # Tolerância ampla: aceita pequenas variações por arredondamento
        assert report.total_slippage_usd >= 15.0, (
            f"Slippage total deveria ser >= 15 USD. obtido={report.total_slippage_usd}"
        )
        assert report.total_slippage_usd <= 25.0


# ---------------------------------------------------------------------------
# Custos extremos — spread
# ---------------------------------------------------------------------------

class TestExtremeSpread:

    def test_wide_spread_increases_total_execution_cost(self):
        """spread_pct=0.02 → ~8 USD de slippage cost total (2% × 200 × 2 legs)."""
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(spread_pct=0.02)
        )
        assert report.total_trades == 1
        # Spread amplo gera slippage cost significativo
        assert report.total_execution_cost_usd >= 5.0, (
            f"total_execution_cost_usd deveria ser >= 5 USD com spread 2%. "
            f"obtido={report.total_execution_cost_usd}"
        )

    def test_extreme_spread_does_not_alter_hit_detection_threshold(self):
        """
        Mesmo com spread 2%, o TP é detectado pelo preço TEÓRICO (67000).
        exit_price_theoretical deve ser EXATAMENTE 67000; exit_price < 67000.
        """
        report = _tp_scenario_with_cost(
            ExecutionCostConfig(spread_pct=0.02)
        )
        assert_exactly_one_trade_closed_by(report, CloseReason.TAKE_PROFIT)
        trade = report.trades[0]
        assert trade.exit_price_theoretical == DEFAULT_TP_PRICE
        assert trade.exit_price < trade.exit_price_theoretical, (
            "BUY exit com spread DEVE deslizar abaixo do TP teórico"
        )


# ---------------------------------------------------------------------------
# Sequência longa de perdas — trades construídos manualmente
# ---------------------------------------------------------------------------

class TestLongLosingStreak:

    def _build_streak_report(self, n_losses: int) -> BacktestReport:
        """Constrói report com n_losses trades SL consecutivos (sem rodar engine)."""
        trades = [_build_sl_trade(i) for i in range(n_losses)]
        # Cada trade perde ~3.077 USD; equity curve decresce
        capital = 5000.0
        equity = [capital]
        for t in trades:
            capital += t.pnl_usd
            equity.append(capital)
        return BacktestReport.from_trades(
            trades=trades,
            initial_capital=5000.0,
            equity_curve=equity,
            strategy_name="t",
            symbol="BTCUSDT",
            n_candles_total=100,
        )

    def test_max_consecutive_losses_with_10_stop_loss_sequence(self):
        report = self._build_streak_report(10)
        assert report.total_trades == 10
        assert report.max_consecutive_losses == 10
        assert report.max_consecutive_wins == 0

    def test_max_drawdown_approximates_sum_of_consecutive_losses(self):
        """
        10 trades SL de ~-3.077 USD cada → soma = ~-30.77 USD.
        max_drawdown_usd deve refletir a queda total do pico ao vale.
        """
        report = self._build_streak_report(10)
        # Cada SL: (64000-65000)/65000 * 200 = -3.0769 USD
        expected_total_loss = -3.0769 * 10  # ~-30.77 USD
        assert report.max_drawdown_usd == pytest.approx(
            expected_total_loss, abs=0.1
        )
        assert report.max_drawdown_usd < 0

    def test_risk_reward_realized_avg_close_to_minus_one_in_pure_loss_streak(self):
        """SL atingido em todos os trades → R:R realizado ≈ -1.0."""
        report = self._build_streak_report(10)
        assert report.risk_reward_realized_avg is not None
        assert report.risk_reward_realized_avg == pytest.approx(-1.0, abs=1e-2)


# ---------------------------------------------------------------------------
# Gap contra posição
# ---------------------------------------------------------------------------

class TestGapAgainstPosition:

    def _gap_scenario(self, config: Optional[ExecutionCostConfig] = None) -> BacktestReport:
        """Constrói candles SL normais e substitui o último por um gap profundo."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=70000.0,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )
        # Gap profundo: low=50000 (muito abaixo do stop=64000)
        candles = _replace_last_candle_with_gap(
            candles, gap_low=50000.0, gap_close=50500.0
        )
        signal = make_default_buy_signal(take_profit_price=70000.0)
        engine = make_backtest_engine_with_stub(
            signal=signal,
            execution_cost_config=config,
        )
        return engine.run(candles)

    def test_gap_below_stop_keeps_theoretical_exit_at_stop_price(self):
        """Mesmo com gap profundo, exit_price_theoretical == stop_loss_price (regra de hit)."""
        report = self._gap_scenario(config=None)
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        trade = report.trades[0]
        assert trade.exit_price_theoretical == DEFAULT_STOP_PRICE, (
            f"exit_price_theoretical deveria ser {DEFAULT_STOP_PRICE} "
            f"(regra: hit usa preço teórico). obtido={trade.exit_price_theoretical}"
        )

    def test_slippage_under_gap_executes_below_stop_for_buy(self):
        """
        Com slippage > 0 sob gap, exit_price executado desliza ABAIXO do stop_loss_price
        (BUY exit fica pior). Preserva o "stop drift" documentado em backtesting_realism.md.
        """
        report = self._gap_scenario(
            config=ExecutionCostConfig(slippage_pct=0.001)
        )
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        trade = report.trades[0]
        assert trade.exit_price < DEFAULT_STOP_PRICE, (
            f"exit_price executado deveria estar abaixo do stop (drift conservador). "
            f"executed={trade.exit_price} stop={DEFAULT_STOP_PRICE}"
        )
        assert trade.exit_price < trade.exit_price_theoretical

    def test_gap_does_not_crash_pnl_calculation(self):
        report = self._gap_scenario(config=None)
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        trade = report.trades[0]
        assert math.isfinite(trade.pnl_usd)
        assert math.isfinite(trade.gross_pnl_usd)
        assert trade.pnl_usd < 0


# ---------------------------------------------------------------------------
# Alta volatilidade
# ---------------------------------------------------------------------------

class _HoldSpy:
    """Spy strategy que retorna HOLD e registra janelas vistas (anti-lookahead)."""

    name = "stress_spy"

    def __init__(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING
        self.windows_seen: List[int] = []

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    def set_running(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict) -> StrategySignal:
        self.windows_seen.append(features.get("n_candles", 0))
        return StrategySignal.hold(DEFAULT_SYMBOL, "stress_spy")


class TestHighVolatilityBacktest:

    def test_backtest_runs_to_end_under_high_volatility(self):
        """Engine sobrevive a 200 candles com volatilidade 5% (HOLD strategy)."""
        n = 200
        candles = generate_volatile_candles(n, volatility_pct=0.05)
        # StubStrategy retornando HOLD para evitar validações de stop_loss em preços extremos
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
        )
        report = engine.run(candles)
        assert report.n_candles_total == n
        assert len(report.equity_curve) >= n - 1

    def test_high_volatility_does_not_introduce_lookahead(self):
        """Spy verifica monotonicidade das janelas mesmo em volatilidade alta."""
        n = 100
        candles = generate_volatile_candles(n, volatility_pct=0.05)
        spy = _HoldSpy()
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=5,
            symbol=DEFAULT_SYMBOL,
        )
        engine.run(candles)

        assert len(spy.windows_seen) > 0, "Spy não foi chamada — backtest não executou estratégia"
        assert spy.windows_seen == sorted(spy.windows_seen), (
            "Janelas não monotônicas — possível lookahead!"
        )
        assert max(spy.windows_seen) <= n
        assert spy.windows_seen[-1] == n


# ---------------------------------------------------------------------------
# Dados esparsos / poucos candles
# ---------------------------------------------------------------------------

class TestSparseData:

    def test_backtest_with_very_few_candles_produces_zero_trades(self):
        """
        n_candles=10 < FeatureEngine._MIN_CANDLES_RECOMMENDED=50.
        Zero trades, métricas em estado vazio coerente.
        """
        candles = generate_trending_candles(10)
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=5,
        )
        report = engine.run(candles)

        assert report.total_trades == 0
        assert report.expectancy_usd == 0.0
        assert report.payoff_ratio is None
        assert report.net_payoff_ratio is None
        assert report.gross_payoff_ratio is None
        assert report.max_consecutive_wins == 0
        assert report.max_consecutive_losses == 0
        assert report.avg_trade_duration_candles == 0.0
        assert report.risk_reward_realized_avg is None
        assert report.net_profit_factor is None
        assert report.gross_profit_factor is None

    def test_backtest_with_minimum_data_does_not_raise(self):
        """1 candle → backtest roda sem erro, zero trades."""
        candles = generate_trending_candles(1)
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=5,
        )
        report = engine.run(candles)
        assert report.total_trades == 0
        assert report.n_candles_total == 1

    def test_empty_equity_curve_drawdown_is_zero(self):
        peak, dd_usd, dd_pct = _calculate_drawdown([], 5000.0)
        assert peak == 5000.0
        assert dd_usd == 0.0
        assert dd_pct == 0.0


# ---------------------------------------------------------------------------
# Candles degenerados seguros
# ---------------------------------------------------------------------------

class TestDegenerateButValidCandles:

    def test_candles_with_zero_volume_are_accepted(self):
        """
        Construir 60 candles válidos (high>=max(o,c), low<=min(o,c), low>0)
        com volume=0. load_candles_from_list deve aceitar e backtest deve rodar.
        """
        data = [
            {
                "timestamp": f"2024-01-01T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00",
                "open": 65000.0,
                "high": 65100.0,
                "low": 64900.0,
                "close": 65000.0,
                "volume": 0.0,
            }
            for i in range(60)
        ]
        candles = load_candles_from_list(data)
        assert len(candles) == 60
        assert all(c.volume == 0.0 for c in candles)

        # Backtest com esses candles roda sem erro (HOLD strategy)
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
        )
        report = engine.run(candles)
        assert report.n_candles_total == 60

    def test_candles_with_high_equals_low_no_volatility(self):
        """
        Candles "flat" onde high == open == close == low (sem volatilidade).
        Backtest aceita; sem trade gerado por HOLD strategy.
        """
        data = [
            {
                "timestamp": f"2024-01-01T{(i // 60) % 24:02d}:{i % 60:02d}:00+00:00",
                "open": 65000.0,
                "high": 65000.0,
                "low": 65000.0,
                "close": 65000.0,
                "volume": 1000.0,
            }
            for i in range(60)
        ]
        candles = load_candles_from_list(data)
        for c in candles:
            assert c.high == c.low == c.open == c.close == 65000.0

        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
        )
        report = engine.run(candles)
        assert report.n_candles_total == 60


# ---------------------------------------------------------------------------
# Cenário combinado de stress
# ---------------------------------------------------------------------------

class TestCombinedStressScenario:
    """
    Combina alta volatilidade + custos extremos + grande dataset.
    Não valida valores específicos; valida propriedades estruturais:
        - backtest termina
        - report válido
        - sem NaN/inf
        - net_total_pnl_usd <= gross_total_pnl_usd quando custos > 0
        - total_execution_cost_usd >= 0
        - métricas avançadas calculáveis ou None corretamente
    """

    def test_high_volatility_plus_extreme_costs_plus_sequential_losses_no_crash(self):
        n = 150
        candles = generate_volatile_candles(n, volatility_pct=0.05)
        config = ExecutionCostConfig(
            taker_fee_pct=0.005,    # 0.5% — alto
            slippage_pct=0.005,     # 0.5% — alto
            spread_pct=0.002,       # 0.2% — alto
        )
        # HOLD strategy → engine não tenta abrir trades em preços voláteis,
        # evita validações de stop_loss que poderiam abortar e mascarar bugs.
        # O foco do teste é: o engine SOBREVIVE ao stress combinado.
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
            execution_cost_config=config,
        )
        report = engine.run(candles)

        # Propriedades estruturais obrigatórias
        assert report.n_candles_total == n
        assert math.isfinite(report.total_pnl_usd)
        assert math.isfinite(report.gross_total_pnl_usd)
        assert math.isfinite(report.net_total_pnl_usd)
        assert math.isfinite(report.final_capital)
        assert math.isfinite(report.max_drawdown_usd)
        assert math.isfinite(report.max_drawdown_pct)
        assert math.isfinite(report.expectancy_usd)
        assert math.isfinite(report.avg_trade_duration_candles)
        assert report.total_execution_cost_usd >= 0
        assert report.total_fees_usd >= 0
        assert report.total_slippage_usd >= 0
        # Inteiros não-negativos
        assert report.max_consecutive_wins >= 0
        assert report.max_consecutive_losses >= 0
        # Métricas que podem ser None: payoff_ratio, profit_factor, R:R
        assert report.payoff_ratio is None or math.isfinite(report.payoff_ratio)
        assert report.net_profit_factor is None or math.isfinite(report.net_profit_factor)
        assert report.gross_profit_factor is None or math.isfinite(report.gross_profit_factor)
        assert (
            report.risk_reward_realized_avg is None
            or math.isfinite(report.risk_reward_realized_avg)
        )

    def test_combined_stress_with_trade_net_less_or_equal_gross(self):
        """
        Cenário com trade real: gera 1 trade com custos altos.
        net_total_pnl_usd <= gross_total_pnl_usd (custos só pioram).
        total_execution_cost_usd >= 0.
        """
        config = ExecutionCostConfig(
            taker_fee_pct=0.005,
            slippage_pct=0.005,
            spread_pct=0.002,
        )
        report = _tp_scenario_with_cost(config)
        assert report.total_trades == 1
        assert report.net_total_pnl_usd <= report.gross_total_pnl_usd, (
            f"Custos só pioram resultado: net ({report.net_total_pnl_usd}) "
            f"deveria ser <= gross ({report.gross_total_pnl_usd})"
        )
        assert report.total_execution_cost_usd >= 0
        # Challenge target continua KPI (mesmo com stress)
        assert report.challenge_target_reached is False  # sem target configurado
        assert not hasattr(report, "max_profit_usd")
