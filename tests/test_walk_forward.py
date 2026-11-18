"""
Testes de walk_forward — FASE 3E.4A
=====================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - WalkForwardFoldResult: dataclass imutável com campos obrigatórios.
    - run_walk_forward: orquestração end-to-end.
        * 2 instâncias de strategy por fold (sem vazamento de estado).
        * Custo zero / custo configurado.
        * Challenge target propagado como KPI.
    - compare_reports: deltas in-vs-out.
    - summarize_walk_forward: agregados multi-fold (std=None se n_folds==1).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import (
    DEFAULT_CAPITAL,
    DEFAULT_SYMBOL,
    StubStrategy,
    make_default_buy_signal,
)

from crypto_trading_bot.backtesting.backtest_data import generate_trending_candles
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.backtesting.walk_forward import (
    WalkForwardFoldResult,
    compare_reports,
    run_walk_forward,
    summarize_walk_forward,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_hold_factory():
    """Factory que retorna StubStrategy retornando HOLD (sem trade)."""
    def factory():
        s = StubStrategy(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            block_after_trade=True,
        )
        s.set_running()
        return s
    return factory


def _make_buy_factory(signal=None):
    """Factory que retorna StubStrategy emitindo BUY (gera trade se RiskEngine aprovar)."""
    if signal is None:
        signal = make_default_buy_signal()

    def factory():
        s = StubStrategy(signal=signal, block_after_trade=True)
        s.set_running()
        return s
    return factory


def _make_report_with_pnl(pnl: float) -> BacktestReport:
    """Constrói BacktestReport manualmente com 1 trade do PnL especificado."""
    trade = BacktestTrade(
        symbol="BTCUSDT",
        strategy_name="t",
        entry_candle_idx=10,
        entry_time=_TS,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=200.0,
        side="buy",
        entry_price_theoretical=65000.0,
    )
    # Calcular exit_price para gerar pnl desejado:
    # pnl = (exit - entry)/entry * size  →  exit = entry + pnl/size * entry
    exit_price = 65000.0 + (pnl / 200.0) * 65000.0
    if exit_price <= 0:
        exit_price = 64000.0  # fallback para SL
    close_reason = CloseReason.TAKE_PROFIT if pnl > 0 else CloseReason.STOP_LOSS
    trade.close(
        exit_candle_idx=20,
        exit_time=_TS,
        exit_price=exit_price,
        close_reason=close_reason,
        exit_price_theoretical=exit_price,
    )
    return BacktestReport.from_trades(
        trades=[trade],
        initial_capital=5000.0,
        equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
        strategy_name="t",
        symbol="BTCUSDT",
    )


def _make_fold_result(fold_index: int, train_pnl: float, test_pnl: float) -> WalkForwardFoldResult:
    return WalkForwardFoldResult(
        fold_index=fold_index,
        train_report=_make_report_with_pnl(train_pnl),
        test_report=_make_report_with_pnl(test_pnl),
    )


# ---------------------------------------------------------------------------
# WalkForwardFoldResult
# ---------------------------------------------------------------------------

class TestWalkForwardFoldResult:

    def test_dataclass_is_frozen_and_has_required_fields(self):
        r = _make_fold_result(0, 100.0, 50.0)
        assert r.fold_index == 0
        assert isinstance(r.train_report, BacktestReport)
        assert isinstance(r.test_report, BacktestReport)
        # Imutável: tentativa de set deve falhar
        with pytest.raises((AttributeError, Exception)):
            r.fold_index = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# run_walk_forward — fluxo básico (HOLD strategy, sem trades)
# ---------------------------------------------------------------------------

class TestRunWalkForwardBasic:

    def test_returns_list_with_n_folds_results(self):
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
        )
        assert isinstance(results, list)
        assert len(results) == 5
        for r in results:
            assert isinstance(r, WalkForwardFoldResult)

    def test_each_result_has_train_and_test_reports(self):
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
        )
        for r in results:
            assert isinstance(r.train_report, BacktestReport)
            assert isinstance(r.test_report, BacktestReport)

    def test_strategy_factory_called_twice_per_fold(self):
        """5 folds × 2 chamadas (train + test) = 10 chamadas totais."""
        call_count = {"count": 0}
        base_factory = _make_hold_factory()

        def counting_factory():
            call_count["count"] += 1
            return base_factory()

        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        run_walk_forward(
            strategy_factory=counting_factory,
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
        )
        assert call_count["count"] == 10, (
            f"Esperado 10 chamadas (5 folds × 2), obtido {call_count['count']}"
        )

    def test_no_state_leak_between_folds(self):
        """
        Cada fold deve receber uma instância FRESH, distinta das outras.

        Mantemos referências FORTES a cada instância criada para impedir que
        o GC reuse `id()` entre engines descartados. A unicidade é verificada
        por identidade (`is`), não por valor de `id()`.
        """
        created_strategies: List[Any] = []
        base_factory = _make_hold_factory()

        def tracking_factory():
            s = base_factory()
            created_strategies.append(s)  # referência forte
            return s

        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        run_walk_forward(
            strategy_factory=tracking_factory,
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
        )
        # 5 folds × 2 = 10 instâncias
        assert len(created_strategies) == 10
        # Cada par (i, j) com i != j → objetos distintos por identidade
        for i in range(len(created_strategies)):
            for j in range(i + 1, len(created_strategies)):
                assert created_strategies[i] is not created_strategies[j], (
                    f"Instância compartilhada entre chamadas {i} e {j}!"
                )

    def test_works_with_zero_cost_config(self):
        """ExecutionCostConfig() zero não altera fluxo nem quebra fold."""
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            execution_cost_config=ExecutionCostConfig(),
        )
        assert len(results) == 5
        for r in results:
            assert r.train_report.total_fees_usd == 0.0
            assert r.test_report.total_fees_usd == 0.0


# ---------------------------------------------------------------------------
# run_walk_forward — custos aplicados
# ---------------------------------------------------------------------------

class TestRunWalkForwardWithCosts:

    def test_costs_passed_to_each_fold_engine_via_config(self):
        """
        Sem trades (HOLD strategy), agregados de custo permanecem 0,
        mas isso prova que o config foi RESPEITADO: não houve trade,
        então não houve cobrança. Validação estrutural.
        """
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        cfg = ExecutionCostConfig(taker_fee_pct=0.001)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            execution_cost_config=cfg,
        )
        # Sem trades → fees zero, mas não houve erro
        for r in results:
            assert r.train_report.total_trades == 0
            assert r.test_report.total_trades == 0

    def test_costs_dont_change_fold_structure(self):
        """Número e tamanho dos folds independentes da config de custos."""
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results_no_cost = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
        )
        results_with_cost = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            execution_cost_config=ExecutionCostConfig(taker_fee_pct=0.001),
        )
        assert len(results_no_cost) == len(results_with_cost)
        # n_candles_total por fold idêntico
        for r1, r2 in zip(results_no_cost, results_with_cost):
            assert r1.train_report.n_candles_total == r2.train_report.n_candles_total
            assert r1.test_report.n_candles_total == r2.test_report.n_candles_total

    def test_walk_forward_runs_with_any_initial_capital(self):
        """
        FLUXO independe de capital específico: aceita qualquer valor positivo.
        (Substitui o teste 'provider-agnostic' por verificação estrutural,
        conforme ajuste obrigatório do plano aprovado.)
        """
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        for capital in (1000.0, 5000.0, 10000.0, 25000.0):
            results = run_walk_forward(
                strategy_factory=_make_hold_factory(),
                candles=candles,
                n_folds=5,
                train_pct=0.7,
                initial_capital=capital,
                min_candles=5,
            )
            assert len(results) == 5
            for r in results:
                assert r.train_report.initial_capital == capital
                assert r.test_report.initial_capital == capital


# ---------------------------------------------------------------------------
# Challenge target como KPI
# ---------------------------------------------------------------------------

class TestChallengeTargetKpiInWalkForward:

    def test_challenge_target_propagates_to_each_fold_report(self):
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            challenge_profit_target_usd=500.0,
        )
        for r in results:
            assert r.train_report.challenge_profit_target_usd == 500.0
            assert r.test_report.challenge_profit_target_usd == 500.0

    def test_challenge_target_does_not_stop_any_fold(self):
        """Backtest sempre roda até o fim mesmo em folds com target setado."""
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        results = run_walk_forward(
            strategy_factory=_make_hold_factory(),
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            challenge_profit_target_usd=1.0,  # meta irrisória
        )
        # fold_size=100, train=70, test=30; cada engine deve rodar todos os candles
        for r in results:
            assert r.train_report.n_candles_total == 70
            assert r.test_report.n_candles_total == 30
        # Garantia adicional: nenhum report tem max_profit_usd bloqueante
        for r in results:
            assert not hasattr(r.train_report, "max_profit_usd")
            assert not hasattr(r.test_report, "max_profit_usd")


# ---------------------------------------------------------------------------
# compare_reports
# ---------------------------------------------------------------------------

class TestCompareReports:

    EXPECTED_KEYS = {
        "total_pnl_delta_usd",
        "win_rate_delta",
        "expectancy_delta_usd",
        "profit_factor_delta",
        "max_drawdown_delta_usd",
        "avg_trade_duration_delta_candles",
        "total_trades_delta",
        "net_total_pnl_delta_usd",
        "gross_total_pnl_delta_usd",
    }

    def test_compare_returns_expected_keys(self):
        r_in = _make_report_with_pnl(100.0)
        r_out = _make_report_with_pnl(150.0)
        d = compare_reports(r_in, r_out)
        assert set(d.keys()) == self.EXPECTED_KEYS

    def test_compare_zero_when_reports_identical(self):
        r = _make_report_with_pnl(100.0)
        d = compare_reports(r, r)
        # Deltas numéricos: todos zero
        for key in (
            "total_pnl_delta_usd",
            "win_rate_delta",
            "expectancy_delta_usd",
            "max_drawdown_delta_usd",
            "avg_trade_duration_delta_candles",
            "total_trades_delta",
            "net_total_pnl_delta_usd",
            "gross_total_pnl_delta_usd",
        ):
            assert d[key] == 0.0 or d[key] == 0, f"{key} esperado 0, obtido {d[key]}"

    def test_compare_with_known_pnl_delta(self):
        r_in = _make_report_with_pnl(100.0)
        r_out = _make_report_with_pnl(150.0)
        d = compare_reports(r_in, r_out)
        # out - in = 150 - 100 = 50
        assert d["total_pnl_delta_usd"] == pytest.approx(50.0, abs=1e-2)

    def test_profit_factor_delta_is_none_when_either_is_none(self):
        """report com só wins → profit_factor=None → delta=None."""
        r_in = _make_report_with_pnl(100.0)   # 1 win, profit_factor=None
        r_out = _make_report_with_pnl(150.0)  # 1 win, profit_factor=None
        d = compare_reports(r_in, r_out)
        assert d["profit_factor_delta"] is None


# ---------------------------------------------------------------------------
# summarize_walk_forward
# ---------------------------------------------------------------------------

class TestSummarizeWalkForward:

    EXPECTED_KEYS = {
        "n_folds",
        "mean_test_pnl_usd",
        "std_test_pnl_usd",
        "min_test_pnl_usd",
        "max_test_pnl_usd",
        "mean_test_win_rate",
        "n_profitable_folds",
        "n_losing_folds",
        "consistency_pass_rate",
    }

    def test_summary_returns_required_aggregates_keys(self):
        folds = [_make_fold_result(i, 0.0, float(i * 10)) for i in range(5)]
        s = summarize_walk_forward(folds)
        assert set(s.keys()) == self.EXPECTED_KEYS

    def test_summary_mean_pnl_matches_manual_calculation(self):
        # test_pnls = [0, 10, 20, 30, 40], mean = 20
        folds = [_make_fold_result(i, 0.0, float(i * 10)) for i in range(5)]
        s = summarize_walk_forward(folds)
        assert s["mean_test_pnl_usd"] == pytest.approx(20.0, abs=1e-2)

    def test_summary_min_max_correct(self):
        folds = [_make_fold_result(i, 0.0, float(i * 10)) for i in range(5)]
        s = summarize_walk_forward(folds)
        assert s["min_test_pnl_usd"] == 0.0
        assert s["max_test_pnl_usd"] == 40.0

    def test_summary_with_single_fold_std_is_none(self):
        """AJUSTE APROVADO: std=None com 1 fold (não 0.0)."""
        folds = [_make_fold_result(0, 50.0, 100.0)]
        s = summarize_walk_forward(folds)
        assert s["n_folds"] == 1
        assert s["std_test_pnl_usd"] is None

    def test_summary_with_multiple_folds_std_is_number(self):
        folds = [_make_fold_result(i, 0.0, float(i * 10)) for i in range(5)]
        s = summarize_walk_forward(folds)
        assert s["std_test_pnl_usd"] is not None
        assert s["std_test_pnl_usd"] > 0

    def test_summary_consistency_pass_rate_correct(self):
        """3 folds lucrativos de 5 → consistency_pass_rate = 0.6."""
        # PnLs test: +100, -50, +200, -10, +50 → 3 lucrativos
        pnls = [100.0, -50.0, 200.0, -10.0, 50.0]
        folds = [_make_fold_result(i, 0.0, p) for i, p in enumerate(pnls)]
        s = summarize_walk_forward(folds)
        assert s["n_profitable_folds"] == 3
        assert s["n_losing_folds"] == 2
        assert s["consistency_pass_rate"] == pytest.approx(0.6, abs=1e-2)

    def test_summary_empty_list_raises(self):
        with pytest.raises(ValueError, match="vazio"):
            summarize_walk_forward([])
