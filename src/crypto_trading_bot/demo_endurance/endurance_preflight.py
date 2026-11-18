"""
EndurancePreflight (FASE 30)
=============================
Validacao OBRIGATORIA antes de iniciar uma demo endurance — em
especial demo LONGA (nova sessao de 7 dias so comeca apos validacao
limpa da anterior).

⚠️  Checks com probes INJETAVEIS/mockaveis (zero rede em teste).
⚠️  Credenciais: presence-only — valores NUNCA sao lidos/impressos.
⚠️  Falha em QUALQUER item -> bloqueia nova demo + manual review.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Tuple


_ALLOWED_PROVIDERS = ("paper", "bybit_demo_linear")
_FORBIDDEN_ENV_TOKENS = ("live", "mainnet", "production", "prod")


@dataclass(frozen=True)
class EndurancePreflightResult:
    """Resultado do preflight. approved=False -> manual review."""
    approved: bool
    blockers: Tuple[str, ...] = field(default_factory=tuple)
    manual_review_required: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.blockers, tuple):
            object.__setattr__(self, "blockers", tuple(self.blockers))

    def to_dict(self) -> dict:
        return {
            "approved": bool(self.approved),
            "blockers": list(self.blockers),
            "manual_review_required": bool(self.manual_review_required),
        }


def validate_endurance_preflight(
    *,
    open_positions_count: int,
    open_orders_count: int,
    conditional_orders_count: int,
    safety_state: str,
    provider_id: str,
    environment: str,
    demo_credentials_present: bool,
    api_probe: Optional[Callable[[], bool]] = None,
    mode_guard: Optional[Any] = None,
    endpoint_url: str = "",
    require_previous_report: bool = False,
    previous_report_path: str = "",
    require_previous_telemetry: bool = False,
    previous_telemetry_path: str = "",
) -> EndurancePreflightResult:
    """Valida pre-condicoes de inicio de demo endurance.

    Args:
        open_positions_count/open_orders_count/conditional_orders_count:
            estado atual da conta demo (obtido por caller read-only).
        safety_state: estado da SafetyStateMachine ("normal" exigido).
        provider_id: provider planejado (paper | bybit_demo_linear).
        environment: ambiente planejado ("paper"|"demo"; nunca live).
        demo_credentials_present: presence-only (valores nunca lidos).
        api_probe: callable read-only que retorna True se API demo
            acessivel. None = check pulado (paper/offline).
        mode_guard: ModeGuard opcional. Leitura das properties REAIS
            (is_live / is_safe) — nunca heuristica textual. Demo safe
            (mode=demo, live_enabled=False, demo_exec_enabled=True)
            APROVA; live/mainnet (is_live=True) BLOQUEIA.
        endpoint_url: URL REST planejada (opcional). Em environment
            demo, exige api-demo.bybit.com; endpoint mainnet bloqueia.
        require_previous_report/telemetry + paths: para demo LONGA,
            exigem que report/telemetry da sessao anterior existam.
    """
    blockers = []

    if int(open_positions_count) > 0:
        blockers.append(
            f"open_positions_count={open_positions_count} > 0 "
            "(posicao anterior nao resolvida)"
        )
    if int(open_orders_count) > 0:
        blockers.append(f"open_orders_count={open_orders_count} > 0")
    if int(conditional_orders_count) > 0:
        blockers.append(
            f"conditional_orders_count={conditional_orders_count} > 0"
        )

    if str(safety_state).strip().lower() != "normal":
        blockers.append(f"safety_state={safety_state!r} != 'normal'")

    norm_provider = str(provider_id).strip().lower()
    if norm_provider not in _ALLOWED_PROVIDERS:
        blockers.append(
            f"provider_id={provider_id!r} nao permitido; "
            f"aceitos: {list(_ALLOWED_PROVIDERS)}"
        )

    norm_env = str(environment).strip().lower()
    if any(tok in norm_env for tok in _FORBIDDEN_ENV_TOKENS):
        blockers.append(
            f"environment={environment!r} proibido (mainnet/live "
            "bloqueados)"
        )
    elif norm_env not in ("paper", "demo"):
        blockers.append(
            f"environment={environment!r} desconhecido; "
            "aceitos: paper | demo"
        )

    if mode_guard is not None:
        # HOTFIX FASE 30: ler as properties REAIS do ModeGuard
        # (is_live / is_safe = not is_live). O nome anterior
        # (is_safe_mode) NAO existe no ModeGuard e fazia o getattr
        # default (False) bloquear demo safe — contradizendo o log
        # safe=True do proprio guard. demo_exec_enabled=True NUNCA
        # torna o estado unsafe: unsafe == is_live True.
        try:
            is_live = getattr(mode_guard, "is_live", None)
            is_safe = getattr(mode_guard, "is_safe", None)
            if is_safe is None and is_live is not None:
                is_safe = not bool(is_live)
            if is_live is True:
                blockers.append(
                    "ModeGuard.is_live=True — live/mainnet proibido"
                )
            elif is_safe is not True:
                blockers.append(
                    "ModeGuard sem confirmacao de modo seguro "
                    "(is_safe/is_live indisponiveis) — proibido"
                )
        except Exception:  # noqa: BLE001
            blockers.append("ModeGuard inacessivel")

    # Endpoint: em demo, somente api-demo.bybit.com; mainnet bloqueia.
    if endpoint_url:
        low = str(endpoint_url).strip().lower()
        if "api-demo.bybit.com" not in low:
            blockers.append(
                f"endpoint nao-demo: {endpoint_url!r} "
                "(exigido api-demo.bybit.com; mainnet/live proibidos)"
            )

    if norm_env == "demo" and not demo_credentials_present:
        blockers.append(
            "credenciais demo ausentes (presence-only; valores nunca "
            "impressos)"
        )

    if api_probe is not None:
        try:
            if not bool(api_probe()):
                blockers.append("API demo inacessivel (probe=False)")
        except Exception as e:  # noqa: BLE001
            blockers.append(
                f"API demo probe falhou: {type(e).__name__}"
            )

    if require_previous_report:
        if not previous_report_path or \
                not Path(previous_report_path).is_file():
            blockers.append(
                "report anterior nao encontrado: "
                f"{previous_report_path!r}"
            )
    if require_previous_telemetry:
        if not previous_telemetry_path or \
                not Path(previous_telemetry_path).is_file():
            blockers.append(
                "telemetry anterior nao encontrada: "
                f"{previous_telemetry_path!r}"
            )

    approved = not blockers
    return EndurancePreflightResult(
        approved=approved,
        blockers=tuple(blockers),
        manual_review_required=not approved,
    )


def demo_credentials_present_from_env() -> bool:
    """Presence-only das credenciais demo (valores nunca lidos)."""
    return bool(
        os.environ.get("BYBIT_DEMO_API_KEY", "").strip()
        and os.environ.get("BYBIT_DEMO_API_SECRET", "").strip()
    )


__all__ = [
    "EndurancePreflightResult",
    "demo_credentials_present_from_env",
    "validate_endurance_preflight",
]
