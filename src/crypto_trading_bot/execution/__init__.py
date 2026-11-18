"""
Módulo de Execução
===================
Responsável pela execução de ordens aprovadas pelo RiskEngine.

Implementações disponíveis:
    PaperTrader: execução simulada sem API real (modo paper/testes)
    BybitExecutor: execução real via Bybit (BLOQUEADO até FASE 3)

Fluxo obrigatório:
    signal → RiskEngine.validate() → [se aprovado] → PaperTrader/Executor

⚠️  Nunca envie ordens sem passar pelo RiskEngine primeiro.
"""

from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
    DemoExecutionError,
    DemoExecutionResult,
    DemoTrade,
    DemoTradeStatus,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    BybitDemoPreflight,
    MarketInfo,
    OrderProposal,
    PreflightAbortReason,
    PreflightReport,
)
from crypto_trading_bot.execution.bybit_testnet_executor import (
    BybitTestnetExecutor,
    TestnetExecutionError,
    TestnetExecutionResult,
    TestnetTrade,
    TestnetTradeStatus,
)
from crypto_trading_bot.execution.executor_protocol import ExecutorProtocol
from crypto_trading_bot.execution.paper_orchestrator import (
    CandlesSource,
    PaperSessionConfig,
    PaperSessionResult,
    PaperTradingOrchestrator,
)
from crypto_trading_bot.execution.paper_trader import PaperTrade, PaperTrader
from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)
from crypto_trading_bot.execution.provider_registry import (
    ProviderBlockedError,
    ProviderEntry,
    ProviderRegistry,
    get_registry,
)
from crypto_trading_bot.execution.providers import (
    BinanceDryRunResult,
    BinanceFuturesTestnetAdapter,
    CleoDryRunResult,
    HyroTraderCleoAdapter,
    TealstreetCliGatewayAdapter,
    TealstreetDryRunResult,
    TealstreetGatewayConfig,
)
from crypto_trading_bot.execution.testnet_executor_adapter import (
    TestnetExecutorBotAdapter,
)

__all__ = [
    # Paper trader e trade individual
    "PaperTrader",
    "PaperTrade",
    # FASE 4 — Orquestrador de sessões de paper trading
    "PaperTradingOrchestrator",
    "PaperSessionConfig",
    "PaperSessionResult",
    "CandlesSource",
    # FASE 5 — Bybit Testnet (manual, dry-run por padrão)
    "BybitTestnetExecutor",
    "TestnetTrade",
    "TestnetTradeStatus",
    "TestnetExecutionResult",
    "TestnetExecutionError",
    # FASE 9 Fatia 4A/4B — Bybit Demo Trading (paralelo a testnet; ordem real gated)
    "BybitDemoExecutor",
    "DemoTrade",
    "DemoTradeStatus",
    "DemoExecutionResult",
    "DemoExecutionError",
    # FASE 9 Fatia 4B+ — Preflight automático read-only para ordem mínima demo
    "BybitDemoPreflight",
    "PreflightReport",
    "PreflightAbortReason",
    "MarketInfo",
    "AccountState",
    "OrderProposal",
    # FASE 6 — Integração BotEngine ↔ executor (contrato + adapter testnet)
    "ExecutorProtocol",
    "TestnetExecutorBotAdapter",
    # FASE 8 — Provider-agnostic: capability + registry + adapters esqueleto
    "ProviderCapability",
    "ProviderStatus",
    "ProviderRegistry",
    "ProviderEntry",
    "ProviderBlockedError",
    "get_registry",
    "BinanceFuturesTestnetAdapter",
    "BinanceDryRunResult",
    "HyroTraderCleoAdapter",
    "CleoDryRunResult",
    # FASE 9B — Tealstreet CLI Gateway (dry-run-only, sem subprocess/HTTP)
    "TealstreetCliGatewayAdapter",
    "TealstreetGatewayConfig",
    "TealstreetDryRunResult",
]
