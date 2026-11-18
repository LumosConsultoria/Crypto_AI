"""
Microstructure (FASE 63 — btc_ofi_absorption_scalper_v1). BTCUSDT-only.
=======================================================================
Order flow / book / tape / spread / liquidez / execucao. SOMENTE leitura
publica (REST gated; sem WebSocket dep nesta v1); SEM ordem/demo/live;
orders_emitted=0; RiskEngine/ModeGuard/piso 0.005 intactos; OOS intocado.

5 concerns SEPARADOS: (1) coleta [collector], (2) sinal [features+signal_engine],
(3) simulacao/shadow [shadow], (4) risco [shadow usa RiskParams/piso], (5)
relatorio [report]. Microestrutura e a fonte de dado ESTRUTURALMENTE NOVA que a
politica de reabertura (rejected_hypotheses_registry.check_reopen) autoriza.
"""

from crypto_trading_bot.microstructure.models import (
    BookSnapshot, RiskParams, ShadowTrade, Signal, Tick, Trade)

__all__ = ["BookSnapshot", "Tick", "Trade", "Signal", "ShadowTrade",
           "RiskParams"]
