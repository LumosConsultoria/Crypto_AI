"""
Gates de Position Management (FASE 36 Bloco E2)
================================================
Tres gates ENV INDEPENDENTES (nenhum implica outro; nenhum outro gate
os implica). TODOS default OFF.

⚠️  Gate ligado NAO basta: cada capacidade exige tambem permissao de
    perfil + limites do operador (V5-V8) + confirmacao humana +
    revalidacao de risco agregado via RiskEngine.
"""

from __future__ import annotations

import os


ENV_ALLOW_SCALE_IN = "DEMO_ALLOW_SCALE_IN_ENABLED"
ENV_ALLOW_PARTIAL_REDUCE = "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED"
ENV_ALLOW_REVERSAL = "DEMO_ALLOW_REVERSAL_ENABLED"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in (
        "true", "1", "yes",
    )


def scale_in_gate_enabled() -> bool:
    return _env_truthy(ENV_ALLOW_SCALE_IN)


def partial_reduce_gate_enabled() -> bool:
    return _env_truthy(ENV_ALLOW_PARTIAL_REDUCE)


def reversal_gate_enabled() -> bool:
    return _env_truthy(ENV_ALLOW_REVERSAL)


__all__ = [
    "ENV_ALLOW_PARTIAL_REDUCE",
    "ENV_ALLOW_REVERSAL",
    "ENV_ALLOW_SCALE_IN",
    "partial_reduce_gate_enabled",
    "reversal_gate_enabled",
    "scale_in_gate_enabled",
]
