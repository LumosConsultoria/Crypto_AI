"""
Gates FASE 30.2 - Multi-Ordem Real Demo Sequencial
====================================================
Gate de validacao PURA para a execucao real demo multi-ordem.

⚠️  NAO altera gates_phase29.py (FASE 29 preservada). Este gate eh
    ADICIONAL e independente: nenhum gate implica outro.

⚠️  Validacao pura: NAO chama rede, NAO envia ordem. Retorna
    Phase30GateResult; caller decide.

ENVs exigidos SIMULTANEAMENTE (todos independentes):
    ENABLE_DEMO_EXECUTION=true
    BYBIT_USE_DEMO=true
    DEMO_30_MIN_REAL_RUNNER_DEPLOYED=true
    DEMO_ALLOW_MULTI_ORDER_PER_SESSION=true
    DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED=true   (gate proprio 30.2)

Short real demo continua atras do gate proprio FASE 29.x
(DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED) - validado no pipeline,
nao aqui.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple


ENV_REAL_MULTI_ORDER = "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED"
ENV_DEMO_EXECUTION = "ENABLE_DEMO_EXECUTION"
ENV_USE_DEMO_30_2 = "BYBIT_USE_DEMO"
ENV_RUNNER_DEPLOYED = "DEMO_30_MIN_REAL_RUNNER_DEPLOYED"
ENV_ALLOW_MULTI_ORDER_30_2 = "DEMO_ALLOW_MULTI_ORDER_PER_SESSION"

MAX_REAL_ORDERS_SAFE_CAP = 3


def expected_phrase_30_2(max_real_orders: int) -> str:
    """Frase exata de autorizacao da FASE 30.2 (N substituido)."""
    return (
        f"I authorize up to {int(max_real_orders)} real demo orders "
        "on api-demo.bybit.com for FASE 30.2"
    )


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class Phase30GateResult:
    """Resultado de validacao do gate FASE 30.2."""
    approved: bool
    gate_name: str  # "real_multi_order"
    blockers: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "approved": bool(self.approved),
            "gate_name": self.gate_name,
            "blockers": list(self.blockers),
        }


def validate_phase30_2_real_multi_gate(
    *,
    profile,
    max_real_orders: int,
    phrase_confirmation: str,
    flag_execute_demo_real_multi: bool,
    flag_confirm_demo_real_multi: bool,
    flag_first_real_demo_multi_order_fase30: bool,
    prompt_y_confirmed: bool,
    operator_token: str,
    tty_present: bool,
    real_time: bool,
    demo_only: bool,
    observation_mode: bool,
    synthetic_feed: bool,
) -> Phase30GateResult:
    """Valida TODOS os pre-requisitos da execucao real multi-ordem.

    Pura (sem rede). approved=False com blockers se QUALQUER trava
    falhar. Nenhum item implica outro.
    """
    blockers = []

    # --- ENVs independentes ---
    for env in (
        ENV_DEMO_EXECUTION, ENV_USE_DEMO_30_2, ENV_RUNNER_DEPLOYED,
        ENV_ALLOW_MULTI_ORDER_30_2, ENV_REAL_MULTI_ORDER,
    ):
        if not _env_truthy(env):
            blockers.append(f"{env}=true required")

    # --- perfil ---
    if not getattr(profile, "allow_multi_order_demo", False):
        blockers.append(
            "profile.allow_multi_order_demo=False "
            f"(profile={getattr(profile, 'name', '?')!r})"
        )
    if not getattr(profile, "allow_demo_real", False):
        blockers.append("profile.allow_demo_real=False")

    # --- limites do teto seguro ---
    if not isinstance(max_real_orders, int) or not (
        1 <= max_real_orders <= MAX_REAL_ORDERS_SAFE_CAP
    ):
        blockers.append(
            f"max_real_orders={max_real_orders!r} fora de "
            f"[1, {MAX_REAL_ORDERS_SAFE_CAP}] (cap seguro inicial; "
            "valores maiores exigem gate futuro especifico)"
        )

    # --- frase exata com N ---
    expected = expected_phrase_30_2(
        max_real_orders if isinstance(max_real_orders, int) else 0,
    )
    if not isinstance(phrase_confirmation, str) or \
            phrase_confirmation != expected:
        blockers.append(
            "phrase confirmation mismatch (exact match required)"
        )

    # --- flags redundantes (todas juntas; padrao FASE 27/29) ---
    if not flag_execute_demo_real_multi:
        blockers.append("--execute-demo-real-multi missing")
    if not flag_confirm_demo_real_multi:
        blockers.append("--confirm-demo-real-multi missing")
    if not flag_first_real_demo_multi_order_fase30:
        blockers.append(
            "--first-real-demo-multi-order-fase30 missing"
        )

    # --- confirmacoes humanas ---
    if not prompt_y_confirmed:
        blockers.append("Y prompt not confirmed")
    if not tty_present:
        blockers.append("TTY required for real execution")
    if not isinstance(operator_token, str) or not operator_token.strip():
        blockers.append("operator_token must be non-empty")

    # --- coerencias de modo (regras 11-12 + rejeicoes da spec) ---
    if not real_time:
        blockers.append("--real-time required for real execution")
    if not demo_only:
        blockers.append("--demo-only required")
    if observation_mode:
        blockers.append(
            "observation_mode (--continue-after-would-order) is "
            "forbidden with real execution"
        )
    if synthetic_feed:
        blockers.append(
            "--synthetic-feed is forbidden with real execution"
        )

    return Phase30GateResult(
        approved=not blockers,
        gate_name="real_multi_order",
        blockers=tuple(blockers),
    )


__all__ = [
    "ENV_ALLOW_MULTI_ORDER_30_2",
    "ENV_DEMO_EXECUTION",
    "ENV_REAL_MULTI_ORDER",
    "ENV_RUNNER_DEPLOYED",
    "ENV_USE_DEMO_30_2",
    "MAX_REAL_ORDERS_SAFE_CAP",
    "Phase30GateResult",
    "expected_phrase_30_2",
    "validate_phase30_2_real_multi_gate",
]
