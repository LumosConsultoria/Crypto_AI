"""NetComms registry (infra; FASE 43 realocado da antiga UI): guarda o
status de cada operacao de rede para leitura (read-only). Thread-safe."""

from __future__ import annotations

import threading
from typing import Dict, List

from crypto_trading_bot.netcomms.status import ConnectionStatus


class NetCommsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._status: Dict[str, ConnectionStatus] = {}

    def update(self, status: ConnectionStatus) -> None:
        with self._lock:
            self._status[status.operation] = status

    def get(self, operation: str):
        with self._lock:
            return self._status.get(operation)

    def all(self) -> List[dict]:
        with self._lock:
            return [s.to_dict() for s in self._status.values()]

    def seed(self, operations: List[str]) -> None:
        """Inicializa operacoes conhecidas como not_configured (visivel)."""
        for op in operations:
            if self.get(op) is None:
                self.update(ConnectionStatus(operation=op,
                                             state="not_configured",
                                             detail="ainda nao verificado"))


__all__ = ["NetCommsRegistry"]
