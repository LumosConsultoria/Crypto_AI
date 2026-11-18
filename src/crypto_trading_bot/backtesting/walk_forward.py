"""
walk_forward.py — Orquestrador de Walk-Forward Validation
===========================================================
Executa walk-forward validation usando o BacktestEngine como CAIXA-PRETA.

⚠️  Backtesting NÃO treina modelo.
⚠️  Walk-forward aqui serve para auditar consistência temporal e detectar
    overfitting QUALITATIVO (variabilidade de PnL entre folds, in-vs-out).
⚠️  Zero API real. Zero ordens reais.

Princípios:
    - Por fold: 2 instâncias de estratégia (uma para train, outra para test).
      Garantia zero de vazamento de estado entre train e test.
    - Cada fold é independente: nova RiskEngine, nova FeatureEngine, nova strategy.
    - BacktestEngine é usado sem modificação (mesma interface da FASE 3D/3E.1).
    - ExecutionCostConfig propagado a cada fold uniformemente.
    - challenge_profit_target_usd propagado como KPI (não bloqueia).

Uso típico:
    from crypto_trading_bot.backtesting import (
        run_walk_forward, summarize_walk_forward, compare_reports
    )

    def factory():
        s = MyStrategy(...)
        s.set_running()
        return s

    results = run_walk_forward(
        strategy_factory=factory,
        candles=candles,
        n_folds=5,
        train_pct=0.7,
        execution_cost_config=ExecutionCostConfig(taker_fee_pct=0.0006),
    )
    summary = summarize_walk_forward(results)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.data_splits import walk_forward_split
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine

_logger = get_logger(__name__)


# Type alias: factory que produz uma nova instância de estratégia pronta para uso.
# Convenção: a factory já chama .set_running() (ou equivalente) na strategy.
StrategyFactory = Callable[[], Any]


@dataclass(frozen=True)
class WalkForwardFoldResult:
    """
    Resultado de um único fold do walk-forward.

    Atributos:
        fold_index:    índice 0-based do fold (0, 1, 2, ...).
        train_report:  BacktestReport da execução em train_window.
        test_report:   BacktestReport da execução em test_window.

    Imutável (frozen=True) para auditabilidade.
    """
    fold_index: int
    train_report: BacktestReport
    test_report: BacktestReport


def run_walk_forward(
    strategy_factory: StrategyFactory,
    candles: List[Candle],
    n_folds: int = 5,
    train_pct: float = 0.7,
    initial_capital: float = 5000.0,
    min_candles: int = 50,
    symbol: str = "BTCUSDT",
    execution_cost_config: Optional[ExecutionCostConfig] = None,
    challenge_profit_target_usd: Optional[float] = None,
    precompute_features: bool = False,
    risk_config: Optional["RiskConfig"] = None,
    max_holding_candles: Optional[int] = None,
) -> List[WalkForwardFoldResult]:
    """
    Executa walk-forward validation sobre `candles` em `n_folds` janelas adjacentes.

    Para cada fold k em 0..n_folds-1:
        1. (train_window, test_window) = folds[k]
        2. strategy_train = strategy_factory()          ← nova instância
        3. engine_train = BacktestEngine(strategy_train, ...)
        4. train_report = engine_train.run(train_window)
        5. strategy_test = strategy_factory()           ← OUTRA nova instância
        6. engine_test = BacktestEngine(strategy_test, ...)
        7. test_report = engine_test.run(test_window)

    Args:
        strategy_factory:              Callable[[], Any] que retorna uma nova
                                       instância de estratégia (já set_running).
                                       Chamada EXATAMENTE 2× por fold.
        candles:                       Lista de Candle em ordem cronológica.
        n_folds:                       Número de folds (>= 2).
        train_pct:                     Fração de cada fold para train (em (0,1)).
        initial_capital:               Capital inicial por engine.
        min_candles:                   Min candles antes da estratégia operar.
        symbol:                        Símbolo para os engines.
        execution_cost_config:         FASE 3E.1 — custos opcionais.
        challenge_profit_target_usd:   KPI propagado (NÃO bloqueia).

    Returns:
        Lista de n_folds WalkForwardFoldResult.

    Raises:
        BacktestDataError / ValueError: propagado de walk_forward_split.

    Garantias:
        - Sem vazamento de estado: cada fold cria 2 strategies novas.
        - Cada fold tem 2 RiskEngine independentes (capital inicial fresco).
        - Custos aplicados uniformemente em todos os folds.
        - challenge target propagado mas NÃO bloqueia trades.
    """
    folds = walk_forward_split(candles, n_folds=n_folds, train_pct=train_pct)

    _logger.info(
        f"run_walk_forward iniciado | "
        f"n_folds={n_folds} | train_pct={train_pct} | "
        f"total_candles={len(candles)} | costs="
        f"{'ON' if execution_cost_config and not execution_cost_config.is_zero else 'OFF'}"
    )

    results: List[WalkForwardFoldResult] = []
    for fold_idx, (train_window, test_window) in enumerate(folds):
        # --- TRAIN ---
        strategy_train = strategy_factory()
        engine_train = BacktestEngine(
            strategy=strategy_train,
            risk_engine=RiskEngine(initial_capital=initial_capital,
                                   config=risk_config),
            feature_engine=FeatureEngine(),
            initial_capital=initial_capital,
            min_candles=min_candles,
            symbol=symbol,
            execution_cost_config=execution_cost_config,
            challenge_profit_target_usd=challenge_profit_target_usd,
            max_holding_candles=max_holding_candles,
        )
        train_report = engine_train.run(
            train_window, precompute_features=precompute_features)

        # --- TEST --- (estratégia, engine e risco FRESCOS)
        strategy_test = strategy_factory()
        engine_test = BacktestEngine(
            strategy=strategy_test,
            risk_engine=RiskEngine(initial_capital=initial_capital,
                                   config=risk_config),
            feature_engine=FeatureEngine(),
            initial_capital=initial_capital,
            min_candles=min_candles,
            symbol=symbol,
            execution_cost_config=execution_cost_config,
            challenge_profit_target_usd=challenge_profit_target_usd,
            max_holding_candles=max_holding_candles,
        )
        test_report = engine_test.run(
            test_window, precompute_features=precompute_features)

        results.append(WalkForwardFoldResult(
            fold_index=fold_idx,
            train_report=train_report,
            test_report=test_report,
        ))

    _logger.info(f"run_walk_forward concluído | {len(results)} fold(s) executado(s)")
    return results


def compare_reports(
    report_in: BacktestReport,
    report_out: BacktestReport,
) -> dict:
    """
    Calcula deltas (out - in) de métricas chave entre dois BacktestReports.

    Útil para:
        - Auditar consistência in-sample vs. out-of-sample.
        - Comparar train_report vs. test_report de cada fold do walk-forward.

    Args:
        report_in:  Relatório de referência (in-sample / train).
        report_out: Relatório a comparar (out-of-sample / test).

    Returns:
        dict com as chaves:
            total_pnl_delta_usd
            win_rate_delta
            expectancy_delta_usd
            profit_factor_delta             (None se algum dos PFs for None)
            max_drawdown_delta_usd
            avg_trade_duration_delta_candles
            total_trades_delta
            net_total_pnl_delta_usd
            gross_total_pnl_delta_usd

        Para qualquer métrica que seja None em um dos reports, o delta é None.
    """
    def _delta(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 4)

    return {
        "total_pnl_delta_usd":             _delta(report_in.total_pnl_usd, report_out.total_pnl_usd),
        "win_rate_delta":                  _delta(report_in.win_rate, report_out.win_rate),
        "expectancy_delta_usd":            _delta(report_in.expectancy_usd, report_out.expectancy_usd),
        "profit_factor_delta":             _delta(report_in.profit_factor, report_out.profit_factor),
        "max_drawdown_delta_usd":          _delta(report_in.max_drawdown_usd, report_out.max_drawdown_usd),
        "avg_trade_duration_delta_candles": _delta(
            report_in.avg_trade_duration_candles, report_out.avg_trade_duration_candles
        ),
        "total_trades_delta":              _delta(report_in.total_trades, report_out.total_trades),
        "net_total_pnl_delta_usd":         _delta(report_in.net_total_pnl_usd, report_out.net_total_pnl_usd),
        "gross_total_pnl_delta_usd":       _delta(report_in.gross_total_pnl_usd, report_out.gross_total_pnl_usd),
    }


def summarize_walk_forward(
    fold_results: List[WalkForwardFoldResult],
) -> dict:
    """
    Agrega estatísticas sobre os test_reports de múltiplos folds.

    Args:
        fold_results: Lista de WalkForwardFoldResult (>=1 elemento).

    Returns:
        dict com as chaves:
            n_folds                  : número de folds.
            mean_test_pnl_usd        : média de total_pnl_usd dos test_reports.
            std_test_pnl_usd         : desvio padrão (None se n_folds == 1).
            min_test_pnl_usd         : menor PnL líquido entre os folds.
            max_test_pnl_usd         : maior PnL líquido entre os folds.
            mean_test_win_rate       : média de win_rate dos test_reports.
            n_profitable_folds       : folds com test_pnl > 0.
            n_losing_folds           : folds com test_pnl <= 0.
            consistency_pass_rate    : fração de folds lucrativos (0..1).

    Raises:
        ValueError: se fold_results estiver vazio.

    Política de std=None:
        Quando n_folds == 1, std_test_pnl_usd é None (não 0.0).
        Isto evita que o consumidor interprete 0.0 como "estável" quando
        na verdade simplesmente não há variabilidade observável com 1 fold.
    """
    if not fold_results:
        raise ValueError("fold_results vazio — não há nada a agregar.")

    test_pnls = [f.test_report.total_pnl_usd for f in fold_results]
    test_win_rates = [f.test_report.win_rate for f in fold_results]
    n = len(fold_results)

    mean_pnl = sum(test_pnls) / n
    mean_win_rate = sum(test_win_rates) / n

    if n > 1:
        variance = sum((p - mean_pnl) ** 2 for p in test_pnls) / n
        std_pnl: Optional[float] = round(variance ** 0.5, 4)
    else:
        std_pnl = None

    n_profitable = sum(1 for p in test_pnls if p > 0)
    n_losing = sum(1 for p in test_pnls if p <= 0)

    return {
        "n_folds":                n,
        "mean_test_pnl_usd":      round(mean_pnl, 4),
        "std_test_pnl_usd":       std_pnl,
        "min_test_pnl_usd":       round(min(test_pnls), 4),
        "max_test_pnl_usd":       round(max(test_pnls), 4),
        "mean_test_win_rate":     round(mean_win_rate, 4),
        "n_profitable_folds":     n_profitable,
        "n_losing_folds":         n_losing,
        "consistency_pass_rate":  round(n_profitable / n, 4),
    }
