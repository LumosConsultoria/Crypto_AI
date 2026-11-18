"""
Módulo de Backtesting
======================
Motor de simulação de estratégias sobre dados históricos.

⚠️  AVISOS OBRIGATÓRIOS:
    1. Resultados de backtest NÃO garantem performance futura.
    2. Dados sintéticos NÃO representam condições reais de mercado.
    3. Valide com dados out-of-sample antes de operar em conta real.
    4. Cuidado com overfitting — menos parâmetros é geralmente melhor.
    5. Meta de challenge é APENAS KPI informativo — nunca bloqueia trades.
    6. O bot é agnóstico de provider — HyroTrader é apenas template/exemplo.

Módulos disponíveis:
    backtest_engine.py  → BacktestEngine: motor principal, anti-lookahead
    backtest_data.py    → carregadores e geradores de candles históricos
    backtest_report.py  → BacktestReport: métricas e equity curve
    backtest_trade.py   → BacktestTrade: registro de trade simulado

Uso rápido:
    from crypto_trading_bot.backtesting import BacktestEngine, generate_trending_candles
    from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    candles = generate_trending_candles(200)

    strategy = EmaRsiStrategy()
    strategy.set_running()

    engine = BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=5000.0),
        initial_capital=5000.0,
    )
    report = engine.run(candles)
    print(report.summary())
"""

from crypto_trading_bot.backtesting.backtest_data import (
    BacktestDataError,
    candles_to_csv_string,
    generate_candles_with_stop_hit,
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
    load_candles_from_csv,
    load_candles_from_csv_string,
    load_candles_from_list,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.backtesting.data_splits import (
    split_in_sample_out_of_sample,
    walk_forward_split,
)
from crypto_trading_bot.backtesting.execution_costs import (
    ExecutionCostConfig,
    ExecutionResult,
    apply_entry_costs,
    apply_exit_costs,
)
from crypto_trading_bot.backtesting.walk_forward import (
    StrategyFactory,
    WalkForwardFoldResult,
    compare_reports,
    run_walk_forward,
    summarize_walk_forward,
)

__all__ = [
    # Motor principal
    "BacktestEngine",
    # Relatório
    "BacktestReport",
    # Trades
    "BacktestTrade",
    "CloseReason",
    # Dados
    "BacktestDataError",
    "generate_trending_candles",
    "generate_ranging_candles",
    "generate_volatile_candles",
    "generate_candles_with_stop_hit",
    "load_candles_from_list",
    "load_candles_from_csv",
    "load_candles_from_csv_string",
    "candles_to_csv_string",
    # FASE 3E.1 — Custos de execução
    "ExecutionCostConfig",
    "ExecutionResult",
    "apply_entry_costs",
    "apply_exit_costs",
    # FASE 3E.4A — Splits temporais + walk-forward
    "split_in_sample_out_of_sample",
    "walk_forward_split",
    "StrategyFactory",
    "WalkForwardFoldResult",
    "run_walk_forward",
    "compare_reports",
    "summarize_walk_forward",
]
