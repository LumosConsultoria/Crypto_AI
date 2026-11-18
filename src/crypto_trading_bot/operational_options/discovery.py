"""
OptionDiscoveryAudit (FASE 36 Bloco H)
=======================================
Audita o BOT INTEIRO: compara o registry com o que existe no codigo
(gates ENV declarados, flags de CLI, campos de permissao de perfil)
e aponta lacunas/inconsistencias.

⚠️  Offline: le apenas fontes locais. Detecta opcoes "esquecidas".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple

from crypto_trading_bot.operational_options.registry import (
    OperationalOptionsRegistry,
)


# Inconsistencias historicas conhecidas (documentadas no plano §2).
KNOWN_INCONSISTENCIES = (
    "gate short com nome duplicado em spec: DEMO_ALLOW_SHORT_ENABLED "
    "(spec) vs DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED (implementado)",
    "--apply-demo-real-final e STUB da FASE 28 (sem efeito)",
    "campos FASE 16 sem enforcement no runner FASE 30: "
    "kill_switch_enabled, allowed_hours_utc, "
    "pause_after_consecutive_losses",
    "sobreposicao max_session_minutes/max_trades_per_session "
    "(FASE 16) vs max_orders_per_session (FASE 31)",
)

# Modulos onde gates ENV sao declarados como constantes ENV_*.
_GATE_MODULES = (
    "crypto_trading_bot.demo_endurance.gates_phase29",
    "crypto_trading_bot.demo_endurance.gates_phase30",
    "crypto_trading_bot.demo_endurance.endurance_runner",
    "crypto_trading_bot.ai_assistant.decision_support",
    "crypto_trading_bot.position_management.gates_position_mgmt",
    "crypto_trading_bot.ai_assistant.provider_adapter",
    "crypto_trading_bot.market_intelligence.aggregator",
)

# ENVs que nao sao gates de opcao (infra/config) — ignoradas.
_NON_OPTION_ENVS = frozenset({
    "BYBIT_DEMO_API_KEY", "BYBIT_DEMO_API_SECRET",
    "TRADING_MODE", "ENABLE_LIVE_TRADING",
    "AI_PROVIDER", "AI_API_KEY",   # config de IA (presence-only)
})

_CLI_SCRIPTS = (
    "scripts/run_demo_endurance.py",
    "scripts/run_demo_30_min_endurance.py",
    "scripts/run_strategy_parameter_advisor.py",
    "scripts/run_supervised_readiness.py",
    "scripts/run_operator_inputs.py",
)

_FLAG_RE = re.compile(r'add_argument\(\s*"(--[a-z0-9-]+)"')


@dataclass(frozen=True)
class OptionDiscoveryAuditReport:
    """Resultado da auditoria global."""
    declared_env_gates_in_code: Tuple[str, ...]
    env_gates_missing_in_registry: Tuple[str, ...]
    registry_gates_not_found_in_code: Tuple[str, ...]
    cli_flags_found: Tuple[str, ...]
    profile_permission_fields: Tuple[str, ...]
    profile_fields_missing_in_registry: Tuple[str, ...]
    known_inconsistencies: Tuple[str, ...] = field(
        default_factory=lambda: KNOWN_INCONSISTENCIES,
    )

    @property
    def has_gaps(self) -> bool:
        return bool(
            self.env_gates_missing_in_registry
            or self.profile_fields_missing_in_registry
        )

    def to_dict(self) -> dict:
        return {
            "schema": "option_discovery_audit_v1",
            "declared_env_gates_in_code": list(
                self.declared_env_gates_in_code
            ),
            "env_gates_missing_in_registry": list(
                self.env_gates_missing_in_registry
            ),
            "registry_gates_not_found_in_code": list(
                self.registry_gates_not_found_in_code
            ),
            "cli_flags_found": list(self.cli_flags_found),
            "profile_permission_fields": list(
                self.profile_permission_fields
            ),
            "profile_fields_missing_in_registry": list(
                self.profile_fields_missing_in_registry
            ),
            "known_inconsistencies": list(
                self.known_inconsistencies
            ),
            "has_gaps": self.has_gaps,
        }


def _discover_env_gates() -> List[str]:
    """ENVs de gate declaradas como constantes ENV_* nos modulos."""
    import importlib
    found: set = set()
    for module_name in _GATE_MODULES:
        try:
            mod = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            continue
        for attr in dir(mod):
            if attr.startswith("ENV_"):
                value = getattr(mod, attr)
                if isinstance(value, str) and value.isupper():
                    found.add(value)
    # Gates de settings (sem constante ENV_*): conhecidos.
    found.add("ENABLE_DEMO_EXECUTION")
    found.add("ENABLE_TESTNET_EXECUTION")
    return sorted(found - _NON_OPTION_ENVS)


def _discover_cli_flags(repo_root: Path) -> List[str]:
    flags: set = set()
    for rel in _CLI_SCRIPTS:
        path = repo_root / rel
        if not path.is_file():
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        flags.update(_FLAG_RE.findall(src))
    return sorted(flags)


def _discover_profile_permission_fields() -> List[str]:
    """Campos allow_*/require_* do OperationalProfile."""
    from dataclasses import fields as dc_fields
    from crypto_trading_bot.operational_profile.profile import (
        OperationalProfile,
    )
    return sorted(
        f.name for f in dc_fields(OperationalProfile)
        if f.name.startswith(("allow_", "require_"))
    )


def run_option_discovery_audit(
    *,
    registry: OperationalOptionsRegistry,
    repo_root: str = "",
) -> OptionDiscoveryAuditReport:
    """Roda a auditoria global e compara com o registry."""
    root = Path(repo_root) if repo_root else (
        Path(__file__).resolve().parents[3]
    )
    env_gates_in_code = _discover_env_gates()
    registry_gates = set(registry.declared_gate_names())

    missing_in_registry = sorted(
        set(env_gates_in_code) - registry_gates,
    )
    not_in_code = sorted(
        registry_gates - set(env_gates_in_code),
    )

    profile_fields = _discover_profile_permission_fields()
    registry_profile_fields = {
        o.required_profile_field
        for o in registry.all_options
        if o.required_profile_field
    }
    # Campos de permissao com impacto operacional que precisam estar
    # representados (subset allow_*; require_* sao politicas).
    operationally_relevant = [
        f for f in profile_fields
        if f.startswith("allow_") and f not in (
            # cobertos por opcoes com outro id de campo
            "allow_demo_real",            # representado via gates demo
            "allowed_hours_utc",
        )
    ]
    profile_missing = sorted(
        set(operationally_relevant) - registry_profile_fields,
    )

    return OptionDiscoveryAuditReport(
        declared_env_gates_in_code=tuple(env_gates_in_code),
        env_gates_missing_in_registry=tuple(missing_in_registry),
        registry_gates_not_found_in_code=tuple(not_in_code),
        cli_flags_found=tuple(_discover_cli_flags(root)),
        profile_permission_fields=tuple(profile_fields),
        profile_fields_missing_in_registry=tuple(profile_missing),
    )


__all__ = [
    "KNOWN_INCONSISTENCIES",
    "OptionDiscoveryAuditReport",
    "run_option_discovery_audit",
]
