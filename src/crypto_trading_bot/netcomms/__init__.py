"""NetComms (infra de comunicacao de rede; FASE 43 — realocado da antiga
UI para um pacote NEUTRO, FastAPI-free, usavel por CLI). Rede SOMENTE via
adapters allowlisted, gated, com timeout/erro sanitizado/status visivel.
Nunca expoe secret/header/signature; nunca shell; nunca bypassa gates.
GUIs futuras consomem esta infra; ela nao depende de nenhuma UI."""

from crypto_trading_bot.netcomms.operation import run_network_op
from crypto_trading_bot.netcomms.registry import NetCommsRegistry
from crypto_trading_bot.netcomms.status import STATES, ConnectionStatus

# Operacoes de rede conhecidas (read-only).
KNOWN_OPERATIONS = (
    "bybit_test_connection", "bybit_provider_health",
    "bybit_instrument_info", "bybit_account_readonly",
    "candles_public_fetch", "demo_preview_blueprint",
    "position_monitor", "reconciliation", "close_reduce_only",
    "market_intelligence", "ai_provider",
)

__all__ = [
    "ConnectionStatus",
    "KNOWN_OPERATIONS",
    "NetCommsRegistry",
    "STATES",
    "run_network_op",
]
