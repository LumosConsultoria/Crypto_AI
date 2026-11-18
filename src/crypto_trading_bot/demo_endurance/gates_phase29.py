"""
Gates FASE 29
======================
Dois gates separados:
    1. execute_demo_real_order_gated (entry): primeira ordem real demo.
    2. execute_demo_close_gated (close): reduceOnly close gated.

⚠️  Os dois sao habilitados por ENVs DIFERENTES (ajuste obrigatorio
    do plano):
        - entry: DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED=true
        - close: DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED=true

⚠️  Estes gates sao WRAPPERS de validacao. NAO enviam ordem por si:
    delegam ao caller (entry: execute_demo_session_gated FASE 22;
    close: CloseExecutorWrapper FASE 29).

⚠️  Cada gate retorna um Phase29GateResult; nao levanta excecao por
    falha de validacao (mantem caller em controle).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Tuple


ENV_REAL_ORDER_ENABLED = "DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED"
ENV_REDUCE_ONLY_CLOSE_ENABLED = (
    "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED"
)
# FASE 29.x - gate ADICIONAL para ordens SELL/SHORT reais em demo.
# Sem ele, a FASE 29 real permanece long-only mesmo que o advisor
# de pesquisa ja consiga avaliar grids SHORT.
ENV_ALLOW_SHORT = "DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED"
ENV_USE_DEMO = "BYBIT_USE_DEMO"
EXPECTED_PHRASE = (
    "I authorize a real demo order on api-demo.bybit.com"
)


@dataclass(frozen=True)
class Phase29GateResult:
    """Resultado de validacao de um gate FASE 29."""
    approved: bool
    gate_name: str  # "entry" | "close"
    blockers: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "approved": bool(self.approved),
            "gate_name": self.gate_name,
            "blockers": list(self.blockers),
        }


def _env_truthy(name: str) -> bool:
    val = os.environ.get(name, "")
    return val.strip().lower() in ("true", "1", "yes")


def validate_phase29_entry_gate(
    *,
    phrase_confirmation: str,
    flag_apply_demo_real: bool,
    flag_confirm_demo_endurance: bool,
    flag_i_understand: bool,
    flag_execute_real: bool,
    flag_first_real_demo_order: bool,
    prompt_y_confirmed: bool,
    operator_token: str,
    tty_present: bool,
    non_interactive_assume_no: bool,
) -> Phase29GateResult:
    """Valida pre-requisitos para chamar execute_demo_session_gated
    com dry_run=False na FASE 29 (entry).

    Esta validacao eh PURA (nao chama rede). Retorna approved=False
    com lista de blockers se algum gate falhar.

    Nota: validacoes de ENV/provider/endpoint sao responsabilidade
    do caller via outras camadas (readiness + production_wiring +
    preflight).
    """
    blockers = []

    if non_interactive_assume_no:
        blockers.append("non_interactive_assume_no rejects real path")

    if not tty_present:
        blockers.append("TTY required for real order")

    if not _env_truthy(ENV_REAL_ORDER_ENABLED):
        blockers.append(
            f"{ENV_REAL_ORDER_ENABLED}=true required"
        )

    if not _env_truthy(ENV_USE_DEMO):
        blockers.append(f"{ENV_USE_DEMO}=true required")

    # Frase exata
    if not isinstance(phrase_confirmation, str) or \
            phrase_confirmation != EXPECTED_PHRASE:
        blockers.append("phrase confirmation mismatch (exact match required)")

    # 5 flags redundantes
    if not flag_apply_demo_real:
        blockers.append("--apply-demo-real missing")
    if not flag_confirm_demo_endurance:
        blockers.append("--confirm-demo-endurance missing")
    if not flag_i_understand:
        blockers.append("--i-understand-this-is-demo-endurance missing")
    if not flag_execute_real:
        blockers.append("--execute-real missing")
    if not flag_first_real_demo_order:
        blockers.append("--first-real-demo-order missing")

    if not prompt_y_confirmed:
        blockers.append("Y prompt not confirmed")

    if not isinstance(operator_token, str) or \
            not operator_token.strip():
        blockers.append("operator_token must be non-empty")

    return Phase29GateResult(
        approved=not blockers,
        gate_name="entry",
        blockers=tuple(blockers),
    )


def validate_phase29_close_gate(
    *,
    has_open_position: bool,
    position_qty: float,
    requested_close_qty: float,
    exit_decision_requires_reduce_only: bool,
    exit_decision_should_close: bool,
    safety_state: str,
    safety_halt_recommended: bool,
    close_orders_submitted_so_far: int,
    max_close_orders: int,
    operator_token: str,
) -> Phase29GateResult:
    """Valida pre-requisitos para reduceOnly close FASE 29.

    Esta validacao depende de uma ENV SEPARADA da entry; recusa se
    DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED nao for true.
    """
    blockers = []

    if not _env_truthy(ENV_REDUCE_ONLY_CLOSE_ENABLED):
        blockers.append(
            f"{ENV_REDUCE_ONLY_CLOSE_ENABLED}=true required"
        )

    if not has_open_position:
        blockers.append("no open position to close")
    if position_qty <= 0:
        blockers.append(f"position_qty <= 0: {position_qty}")
    if requested_close_qty <= 0:
        blockers.append(
            f"requested_close_qty <= 0: {requested_close_qty}"
        )
    # close integral - sem partial
    if abs(requested_close_qty - position_qty) > 1e-9:
        blockers.append(
            "partial close not allowed in FASE 29; "
            f"requested={requested_close_qty} position={position_qty}"
        )

    if not exit_decision_should_close:
        blockers.append("ExitDecision.should_close=False")
    if not exit_decision_requires_reduce_only:
        blockers.append("ExitDecision.requires_reduce_only=False")

    if safety_state not in ("normal", "emergency"):
        blockers.append(f"safety_state={safety_state!r} blocks close")

    if safety_halt_recommended:
        # halt + emergency permitido apenas com ExitReason=EMERGENCY
        # (ja modelado em ExitDecision.requires_reduce_only); caller
        # garante esse caminho. Aqui apenas registra.
        pass

    if max_close_orders < 1:
        blockers.append(f"max_close_orders={max_close_orders} invalid")
    if close_orders_submitted_so_far >= max_close_orders:
        blockers.append(
            "close_orders_submitted_so_far"
            f"={close_orders_submitted_so_far} >= "
            f"max_close_orders={max_close_orders}"
        )

    if not isinstance(operator_token, str) or \
            not operator_token.strip():
        blockers.append("operator_token must be non-empty")

    return Phase29GateResult(
        approved=not blockers,
        gate_name="close",
        blockers=tuple(blockers),
    )


def validate_phase29_short_gate(
    *,
    signal_side: str,
    operator_confirmed_short: bool,
    operator_token: str,
) -> Phase29GateResult:
    """Gate ADICIONAL para ordens SELL/SHORT reais em demo (FASE 29.x).

    Comportamento long-only por default:
        - BUY/long: aprovado trivialmente (este gate nao restringe long).
        - SELL/short: REQUER ENV_ALLOW_SHORT=true + aprovacao explicita
          do operador + operator_token nao-vazio.

    Sem ENV_ALLOW_SHORT=true a FASE 29 real continua long-only: qualquer
    sinal SELL eh bloqueado por este gate. NAO altera os gates de entry
    nem de close; eh uma camada adicional, sempre mais restritiva.

    Validacao PURA (sem rede). Retorna Phase29GateResult.
    """
    side = (signal_side or "").strip().lower()
    is_short = side in ("sell", "short")

    if not is_short:
        # Long-only default: BUY/long nunca depende deste gate.
        return Phase29GateResult(
            approved=True, gate_name="short", blockers=(),
        )

    blockers = []
    if not _env_truthy(ENV_ALLOW_SHORT):
        blockers.append(
            f"{ENV_ALLOW_SHORT}=true required for SELL/SHORT real demo "
            "(FASE 29 stays long-only without it)"
        )
    if not operator_confirmed_short:
        blockers.append("operator did not confirm SHORT explicitly")
    if not isinstance(operator_token, str) or not operator_token.strip():
        blockers.append("operator_token must be non-empty")

    return Phase29GateResult(
        approved=not blockers,
        gate_name="short",
        blockers=tuple(blockers),
    )


__all__ = [
    "ENV_REAL_ORDER_ENABLED",
    "ENV_REDUCE_ONLY_CLOSE_ENABLED",
    "ENV_ALLOW_SHORT",
    "ENV_USE_DEMO",
    "EXPECTED_PHRASE",
    "Phase29GateResult",
    "validate_phase29_entry_gate",
    "validate_phase29_close_gate",
    "validate_phase29_short_gate",
]
