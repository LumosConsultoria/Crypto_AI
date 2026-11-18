"""
Strategy Research Framework — FASE 3F
=======================================
Módulo de pesquisa e comparação de estratégias usando o BacktestEngine
existente como caixa-preta.

⚠️  ZERO ordens reais. ZERO API. ZERO API key.
⚠️  Backtest e ranking NÃO garantem performance futura.
⚠️  Este framework NÃO faz otimização automática de parâmetros nem
    parameter sweep. Apenas avalia specs/configs explícitos.

Uso típico:
    from crypto_trading_bot.research import (
        StrategySpec,
        StrategyRegistry,
        evaluate_strategy,
        compare_strategies,
        rank_strategies,
        summarize_comparison,
    )

    def my_factory(config):
        s = MyStrategy(**config)
        s.set_running()
        return s

    spec = StrategySpec(
        name="my_strat_default",
        factory=my_factory,
        default_config={"ema_period": 21, "rsi_period": 14},
    )

    result = evaluate_strategy(spec, candles, walk_forward_n_folds=5)
    print(summarize_comparison([result]))
"""

from crypto_trading_bot.research.strategy_research import (
    RankMetric,
    StrategyEvaluationResult,
    StrategyRegistry,
    StrategySpec,
    compare_strategies,
    evaluate_strategy,
    rank_strategies,
    summarize_comparison,
)

__all__ = [
    "StrategySpec",
    "StrategyRegistry",
    "StrategyEvaluationResult",
    "RankMetric",
    "evaluate_strategy",
    "compare_strategies",
    "rank_strategies",
    "summarize_comparison",
]
