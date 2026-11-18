"""
Módulo de Estratégias
======================
Contém as estratégias de trading — regras determinísticas e auditáveis.

⚠️  REGRAS FUNDAMENTAIS:
    1. Estratégias geram SINAIS, não ordens. O RiskEngine decide se executa.
    2. Toda lógica de decisão deve ser determinística e testável.
    3. IA/LLM NUNCA deve gerar sinais de trading diretamente.
    4. Qualquer estratégia deve herdar de BaseStrategy.
    5. Sinais sem stop loss são bloqueados automaticamente pelo RiskEngine.
    6. HOLD/NO_TRADE NUNCA é enviado para execução.

Fluxo padronizado via BotEngine:
    strategy.evaluate(features) → StrategySignal (BUY/SELL/HOLD)
        → se HOLD → ciclo encerra com segurança
        → se BUY/SELL → to_trading_signal() → RiskEngine → PaperTrader

Uso:
    from crypto_trading_bot.strategies import (
        BaseStrategy,
        StrategyState,
        ExampleStrategy,
        EmaRsiStrategy,
        StrategyAction,
        StrategySignal,
    )
"""

from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.example_strategy import ExampleStrategy
from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    TrendPullbackStrategy,
    build_trend_pullback_spec,
)
from crypto_trading_bot.strategies.volatility_breakout_strategy import (
    VolatilityBreakoutStrategy,
    build_volatility_breakout_spec,
)

__all__ = [
    # Interface base
    "BaseStrategy",
    "StrategyState",
    # Estratégias
    "ExampleStrategy",
    "EmaRsiStrategy",                # Placeholder para validação do fluxo
    "TrendPullbackStrategy",         # FASE 10 — tendência + pullback
    "VolatilityBreakoutStrategy",    # FASE 10 — rompimento + volatilidade
    # Factories (StrategySpec)
    "build_trend_pullback_spec",
    "build_volatility_breakout_spec",
    # Modelo de sinal padronizado
    "StrategyAction",
    "StrategySignal",
]
