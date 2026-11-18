"""
Provider Adapters — FASE 8
============================
Pacote de adapters de provider para o BotEngine.

Adapters atuais (todos esqueleto/dry-run nesta fase):
    BinanceFuturesTestnetAdapter — dry-run only; live levanta NotImplementedError.
    HyroTraderCleoAdapter        — UNCONFIRMED; execute sempre falha explicando
                                   que o mecanismo de integração CLEO não foi
                                   confirmado (ver docs/hyrotrader_cleo.md).

⚠️  Nenhum adapter aqui chama internet, importa httpx, ou usa API key real.
⚠️  PaperTrader continua o caminho default do BotEngine — não é re-instanciado
    aqui (mora em execution/paper_trader.py).
⚠️  BybitTestnetExecutor (FASE 5) NÃO é movido para cá — código intacto.
    Bybit é apenas reclassificada como RESTRICTED no ProviderRegistry.
"""

from crypto_trading_bot.execution.providers.binance_futures_testnet_adapter import (
    BinanceDryRunResult,
    BinanceFuturesTestnetAdapter,
)
from crypto_trading_bot.execution.providers.hyrotrader_cleo_adapter import (
    CleoDryRunResult,
    HyroTraderCleoAdapter,
)
from crypto_trading_bot.execution.providers.tealstreet_cli_gateway_adapter import (
    TealstreetCliGatewayAdapter,
    TealstreetDryRunResult,
    TealstreetGatewayConfig,
)

__all__ = [
    "BinanceFuturesTestnetAdapter",
    "BinanceDryRunResult",
    "HyroTraderCleoAdapter",
    "CleoDryRunResult",
    "TealstreetCliGatewayAdapter",
    "TealstreetGatewayConfig",
    "TealstreetDryRunResult",
]
