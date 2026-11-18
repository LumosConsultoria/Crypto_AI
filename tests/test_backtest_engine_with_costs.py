"""
Testes de integração: BacktestEngine + ExecutionCostConfig
============================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

FASE 3E.1 — Cobertura:
    - Regressão FASE 3D.5: custo zero não altera comportamento
    - Fees reduzem PnL líquido
    - Slippage piora preço executado de entrada e saída
    - Spread impacta entrada e saída
    - Stop loss continua tendo prioridade na ambiguidade
    - Stop/TP detectados pelo preço TEÓRICO (não pelo executado)
    - BacktestReport soma fees e slippage corretamente
    - Summary exibe seção de custos apenas quando > 0
    - Challenge target continua apenas KPI (com custos > 0)
    - Não existe max_profit_usd bloqueante
    - Provider-agnostic com custos
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import (
    DEFAULT_CAPITAL,
    DEFAULT_ENTRY_PRICE,
    DEFAULT_MIN_CANDLES,
    DEFAULT_POSITION_SIZE,
    DEFAULT_STOP_PRICE,
    DEFAULT_TP_PRICE,
    assert_exactly_one_trade_closed_by,
    make_backtest_engine_with_stub,
    make_default_buy_signal,
    make_realistic_cost_config,
    make_zero_cost_config,
)

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_trending_candles,
)
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import CloseReason
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.config.risk_config import ACCOUNT_PROFILES


# ---------------------------------------------------------------------------
# Regressão FASE 3D.5 — custo zero preserva comportamento
# ---------------------------------------------------------------------------

class TestZeroCostRegression:
    """
    Garante regressão zero: ExecutionCostConfig() sem argumentos produz
    backtest idêntico ao da FASE 3D.5 (sem config).
    """

    def _run_pair(self, candles, *, signal=None, min_candles=DEFAULT_MIN_CANDLES):
        engine_no_cfg = make_backtest_engine_with_stub(
            signal=signal, min_candles=min_candles, execution_cost_config=None
        )
        engine_zero = make_backtest_engine_with_stub(
            signal=signal, min_candles=min_candles,
            execution_cost_config=make_zero_cost_config(),
        )
        return engine_no_cfg.run(candles), engine_zero.run(candles)

    def test_total_trades_identical(self):
        candles = generate_trending_candles(100)
        r1, r2 = self._run_pair(candles)
        assert r1.total_trades == r2.total_trades

    def test_total_pnl_identical(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        r1, r2 = self._run_pair(candles, signal=make_default_buy_signal())
        assert r1.total_pnl_usd == r2.total_pnl_usd

    def test_final_capital_identical(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        r1, r2 = self._run_pair(candles, signal=make_default_buy_signal())
        assert r1.final_capital == r2.final_capital

    def test_equity_curve_identical(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        r1, r2 = self._run_pair(candles, signal=make_default_buy_signal())
        assert r1.equity_curve == r2.equity_curve

    def test_close_reasons_identical(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )
        r1, r2 = self._run_pair(candles, signal=make_default_buy_signal())
        reasons_1 = [t.close_reason for t in r1.trades]
        reasons_2 = [t.close_reason for t in r2.trades]
        assert reasons_1 == reasons_2

    def test_entry_and_exit_prices_identical(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="tp",
        )
        r1, r2 = self._run_pair(candles, signal=make_default_buy_signal())
        assert [t.entry_price for t in r1.trades] == [t.entry_price for t in r2.trades]
        assert [t.exit_price for t in r1.trades] == [t.exit_price for t in r2.trades]

    def test_gross_equals_net_when_zero_cost(self):
        """Com custo zero, PnL bruto e líquido devem ser iguais."""
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
            execution_cost_config=make_zero_cost_config(),
        )
        report = engine.run(candles)
        assert report.total_trades == 1
        trade = report.trades[0]
        assert trade.gross_pnl_usd == trade.pnl_usd
        assert report.gross_total_pnl_usd == report.net_total_pnl_usd
        assert report.total_fees_usd == 0.0
        assert report.total_slippage_usd == 0.0
        assert report.total_execution_cost_usd == 0.0


# ---------------------------------------------------------------------------
# Fees reduzem PnL líquido
# ---------------------------------------------------------------------------

class TestFeesReducePnl:

    def _tp_scenario(self, *, config):
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

    def test_fee_reduces_net_pnl_compared_to_gross(self):
        report = self._tp_scenario(
            config=ExecutionCostConfig(taker_fee_pct=0.0006),
        )
        assert report.total_trades == 1
        trade = report.trades[0]
        # gross é o PnL teórico (sem custos); net inclui fees → menor
        assert trade.gross_pnl_usd > trade.pnl_usd
        # Fees totais = 2 × notional × pct = 2 × 200 × 0.0006 = 0.24
        assert report.total_fees_usd == pytest.approx(0.24, abs=1e-6)
        # net = gross - fees (sem slippage neste cenário)
        assert trade.pnl_usd == pytest.approx(
            trade.gross_pnl_usd - report.total_fees_usd, abs=1e-3
        )

    def test_zero_fee_keeps_gross_equal_to_net(self):
        report = self._tp_scenario(config=ExecutionCostConfig(taker_fee_pct=0.0))
        trade = report.trades[0]
        assert trade.gross_pnl_usd == trade.pnl_usd

    def test_total_fees_sum_across_trades(self):
        """Fees somam corretamente em entry + exit."""
        cfg = ExecutionCostConfig(taker_fee_pct=0.001)
        report = self._tp_scenario(config=cfg)
        # Fee = position_size × 0.001 = 0.20 por leg → 0.40 no total
        assert report.total_fees_usd == pytest.approx(0.40, abs=1e-6)


# ---------------------------------------------------------------------------
# Slippage piora entrada e saída
# ---------------------------------------------------------------------------

class TestSlippageWorsenedExecution:

    def _tp_scenario(self, *, config):
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

    def test_buy_entry_executed_above_theoretical(self):
        report = self._tp_scenario(config=ExecutionCostConfig(slippage_pct=0.001))
        trade = report.trades[0]
        assert trade.entry_price_theoretical is not None
        assert trade.entry_price > trade.entry_price_theoretical, (
            "BUY entry deveria executar pior (preço acima do teórico)"
        )

    def test_buy_exit_executed_below_theoretical(self):
        report = self._tp_scenario(config=ExecutionCostConfig(slippage_pct=0.001))
        trade = report.trades[0]
        assert trade.exit_price_theoretical is not None
        # exit teórico = take_profit_price (67000.0). Exit executado deve ser menor.
        assert trade.exit_price < trade.exit_price_theoretical, (
            "BUY exit deveria executar pior (preço abaixo do teórico)"
        )

    def test_slippage_cost_in_report(self):
        report = self._tp_scenario(config=ExecutionCostConfig(slippage_pct=0.001))
        assert report.total_slippage_usd > 0
        # 2 × (1 × 200 / 1000) usando aproximação: drift_pct × notional = 0.001 × 200 = 0.20 por leg
        # entry: 65000 → 65065, drift=65 → 65/65000 × 200 = 0.20
        # exit: 67000 → 66933, drift=67 → 67/67000 × 200 = 0.20
        assert report.total_slippage_usd == pytest.approx(0.40, abs=1e-2)


# ---------------------------------------------------------------------------
# Sell entry/exit slippage
# ---------------------------------------------------------------------------

class TestSellSlippageDirection:
    """
    Para SELL: entry deveria executar abaixo do teórico (vende mais barato),
    exit deveria executar acima (cobre mais caro).
    Testes diretos das funções, pois o BacktestEngine padrão usa BUY no Stub.
    """

    def test_sell_entry_executes_lower(self):
        from crypto_trading_bot.backtesting.execution_costs import apply_entry_costs
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_entry_costs("sell", 65000.0, 200.0, cfg)
        assert result.price_executed < 65000.0

    def test_sell_exit_executes_higher(self):
        from crypto_trading_bot.backtesting.execution_costs import apply_exit_costs
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_exit_costs("sell", 65000.0, 200.0, cfg)
        assert result.price_executed > 65000.0


# ---------------------------------------------------------------------------
# Spread impacta entrada e saída
# ---------------------------------------------------------------------------

class TestSpreadImpactsBothLegs:

    def test_spread_pct_increases_buy_entry_and_decreases_buy_exit(self):
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
            execution_cost_config=ExecutionCostConfig(spread_pct=0.0005),
        )
        report = engine.run(candles)
        trade = report.trades[0]
        assert trade.entry_price > trade.entry_price_theoretical
        assert trade.exit_price < trade.exit_price_theoretical


# ---------------------------------------------------------------------------
# Stop/TP continuam detectados pelo preço TEÓRICO (não pelo executado)
# ---------------------------------------------------------------------------

class TestHitDetectionUsesTheoreticalPrice:

    def test_stop_hit_detected_even_with_slippage(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            execution_cost_config=ExecutionCostConfig(slippage_pct=0.0005),
        )
        report = engine.run(candles)
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        trade = report.trades[0]
        # Preço teórico de saída == stop_loss_price (regra de hit)
        assert trade.exit_price_theoretical == DEFAULT_STOP_PRICE
        # Preço executado é PIOR que o teórico (BUY exit)
        assert trade.exit_price < trade.exit_price_theoretical

    def test_tp_hit_detected_even_with_slippage(self):
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
            execution_cost_config=ExecutionCostConfig(slippage_pct=0.0005),
        )
        report = engine.run(candles)
        assert_exactly_one_trade_closed_by(report, CloseReason.TAKE_PROFIT)
        trade = report.trades[0]
        assert trade.exit_price_theoretical == DEFAULT_TP_PRICE
        assert trade.exit_price < trade.exit_price_theoretical


# ---------------------------------------------------------------------------
# Regra de ambiguidade SL+TP continua: stop tem prioridade COM custos
# ---------------------------------------------------------------------------

class TestAmbiguityStopPriorityWithCosts:

    def test_stop_wins_when_both_hit_same_candle_with_costs(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="both",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            execution_cost_config=make_realistic_cost_config(),
        )
        report = engine.run(candles)
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)

    def test_ambiguity_exit_price_theoretical_is_stop_with_costs(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="both",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            execution_cost_config=make_realistic_cost_config(),
        )
        report = engine.run(candles)
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        # Preço teórico continua sendo o stop; preço executado pior (mais baixo).
        assert report.trades[0].exit_price_theoretical == DEFAULT_STOP_PRICE


# ---------------------------------------------------------------------------
# Challenge target continua apenas KPI mesmo com custos
# ---------------------------------------------------------------------------

class TestChallengeTargetIsKpiWithCosts:

    def test_backtest_runs_to_end_with_costs_and_challenge_target(self):
        candles = generate_trending_candles(150)
        engine = make_backtest_engine_with_stub(
            min_candles=5,
            challenge_target=1.0,
            execution_cost_config=make_realistic_cost_config(),
        )
        report = engine.run(candles)
        # Backtest sempre roda até o fim, mesmo com challenge atingido
        assert report.n_candles_total == 150

    def test_challenge_target_reached_uses_net_pnl(self):
        """
        challenge_target_reached olha total_pnl_usd (líquido).
        Cenário positivo: cria report manualmente com PnL líquido conhecido.
        """
        from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade
        from datetime import datetime, timezone

        trade = BacktestTrade(
            symbol="BTCUSDT",
            strategy_name="t",
            entry_candle_idx=10,
            entry_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            entry_price=65000.0,
            stop_loss_price=64000.0,
            take_profit_price=70000.0,
            position_size_usd=10000.0,
            side="buy",
        )
        trade.close(
            exit_candle_idx=20,
            exit_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
            exit_price=70000.0,
            close_reason=CloseReason.TAKE_PROFIT,
            exit_price_theoretical=70000.0,
            entry_fee_usd=5.0,
            exit_fee_usd=5.0,
        )
        report = BacktestReport.from_trades(
            trades=[trade],
            initial_capital=5000.0,
            equity_curve=[5000.0, 5760.0],
            strategy_name="t",
            symbol="BTCUSDT",
            challenge_profit_target_usd=500.0,
        )
        assert report.total_pnl_usd > 500.0
        assert report.challenge_target_reached is True

    def test_no_max_profit_field_after_costs_added(self):
        candles = generate_trending_candles(50)
        engine = make_backtest_engine_with_stub(
            execution_cost_config=make_realistic_cost_config(),
        )
        report = engine.run(candles)
        assert not hasattr(report, "max_profit_usd"), (
            "BacktestReport NÃO deve ter max_profit_usd bloqueante!"
        )


# ---------------------------------------------------------------------------
# Summary só mostra seção de custos quando > 0
# ---------------------------------------------------------------------------

class TestSummaryCostsConditional:

    def test_summary_omits_costs_when_zero(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            execution_cost_config=make_zero_cost_config(),
        )
        report = engine.run(candles)
        summary = report.summary()
        assert "CUSTOS DE EXECUÇÃO" not in summary

    def test_summary_includes_costs_when_present(self):
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
            execution_cost_config=make_realistic_cost_config(),
        )
        report = engine.run(candles)
        summary = report.summary()
        assert "CUSTOS DE EXECUÇÃO" in summary
        assert "Fees totais" in summary
        assert "Slippage" in summary


# ---------------------------------------------------------------------------
# Provider-agnostic com custos
# ---------------------------------------------------------------------------

class TestProviderAgnosticWithCosts:

    def test_same_costs_yield_identical_results_across_providers(self):
        candles = generate_trending_candles(60)
        signal = make_default_buy_signal()
        cost_cfg = make_realistic_cost_config()

        def run_for(profile_name: str):
            profile = ACCOUNT_PROFILES[profile_name]
            capital = float(profile["account_size_usd"] or DEFAULT_CAPITAL)
            engine = make_backtest_engine_with_stub(
                signal=signal,
                capital=capital,
                min_candles=5,
                execution_cost_config=cost_cfg,
            )
            return engine.run(candles)

        r_personal = run_for("personal")
        r_hyro = run_for("hyrotrader_5k")
        r_prop = run_for("prop_challenge_5k")

        assert r_personal.total_trades == r_hyro.total_trades == r_prop.total_trades
        assert r_personal.total_pnl_usd == r_hyro.total_pnl_usd == r_prop.total_pnl_usd
        assert r_personal.total_fees_usd == r_hyro.total_fees_usd == r_prop.total_fees_usd
        assert r_personal.total_slippage_usd == r_hyro.total_slippage_usd == r_prop.total_slippage_usd
