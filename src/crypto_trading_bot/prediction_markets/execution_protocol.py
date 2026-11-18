"""
PredictionMarketExecutionProtocol - SEAM FUTURO BLOQUEADO (FASE 34)
====================================================================
Este modulo existe APENAS como seam arquitetural para uma fase futura
de execucao em prediction markets — que exigiria:
    - confirmacao regulatoria;
    - confirmacao dos termos da plataforma (bots permitidos?);
    - gate ENV especifico;
    - sandbox/testnet se existir;
    - limites e logs proprios;
    - autorizacao explicita do operador.

⚠️  NESTA MACROFASE (30-35): TODA execucao e BLOQUEADA. Qualquer
    chamada levanta PredictionExecutionBlocked. Nenhuma flag, perfil,
    IA ou advisor pode desbloquear este seam.
"""

from __future__ import annotations

from typing import Any


class PredictionExecutionBlocked(PermissionError):
    """Execucao em prediction markets e proibida nesta macrofase."""


_BLOCK_MESSAGE = (
    "Prediction market execution is BLOCKED in this macrophase "
    "(FASE 34 is read-only/advisory). A future dedicated phase with "
    "regulatory/platform confirmation, its own gate and explicit "
    "operator authorization is required."
)


class PredictionMarketExecutionProtocol:
    """Seam futuro. TODA operacao levanta PredictionExecutionBlocked."""

    enabled: bool = False

    def place_bet(self, *args: Any, **kwargs: Any) -> None:
        raise PredictionExecutionBlocked(_BLOCK_MESSAGE)

    def place_order(self, *args: Any, **kwargs: Any) -> None:
        raise PredictionExecutionBlocked(_BLOCK_MESSAGE)

    def cancel(self, *args: Any, **kwargs: Any) -> None:
        raise PredictionExecutionBlocked(_BLOCK_MESSAGE)

    def withdraw(self, *args: Any, **kwargs: Any) -> None:
        raise PredictionExecutionBlocked(_BLOCK_MESSAGE)


__all__ = [
    "PredictionExecutionBlocked",
    "PredictionMarketExecutionProtocol",
]
