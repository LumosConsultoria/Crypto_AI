"""
OperationalOption (FASE 36 Bloco H)
====================================
Metadado COMPLETO de uma opcao/capacidade operacional do bot.
Regra: capacidade que existe na arquitetura NUNCA fica invisivel —
aparece no registry mesmo bloqueada/nao-implementada.

⚠️  Offline/puro. ZERO secret.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple


class ExecutionImpact(str, Enum):
    NONE = "none"
    SIMULATION_ONLY = "simulation_only"
    DEMO_POSSIBLE = "demo_possible"
    REAL_POSSIBLE = "real_possible"


class OptionRiskImpact(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class OptionStatus(str, Enum):
    AVAILABLE = "available"
    DISABLED_BY_DEFAULT = "disabled_by_default"
    BLOCKED = "blocked"
    MISSING_CONFIG = "missing_config"
    MISSING_LIMITS = "missing_limits"
    NOT_IMPLEMENTED = "not_implemented"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


@dataclass(frozen=True)
class OperationalOption:
    """Uma opcao operacional com metadados UI-ready."""

    option_id: str
    source_location: str
    label: str
    description: str
    category: str
    default_enabled: bool = False
    selectable_by_user: bool = False
    requires_gate: bool = False
    required_gate_name: Optional[str] = None
    requires_profile_permission: bool = False
    required_profile_field: Optional[str] = None
    requires_operator_confirmation: bool = False
    requires_manual_review: bool = False
    risk_impact: OptionRiskImpact = OptionRiskImpact.MEDIUM
    execution_impact: ExecutionImpact = ExecutionImpact.NONE
    supported_modes: Tuple[str, ...] = ("paper",)
    supported_providers: Tuple[str, ...] = ()
    blocked_reason: Optional[str] = None
    missing_information: Tuple[str, ...] = field(default_factory=tuple)
    depends_on: Tuple[str, ...] = field(default_factory=tuple)
    conflicts_with: Tuple[str, ...] = field(default_factory=tuple)
    audit_required: bool = True
    telemetry_required: bool = True
    report_required: bool = True
    ui_group: str = "general"
    ui_order: int = 100
    status: OptionStatus = OptionStatus.DISABLED_BY_DEFAULT

    def __post_init__(self) -> None:
        if not self.option_id.strip():
            raise ValueError("option_id vazio")
        if self.requires_gate and not self.required_gate_name:
            raise ValueError(
                f"{self.option_id}: requires_gate exige "
                "required_gate_name"
            )
        if self.requires_profile_permission and \
                not self.required_profile_field:
            raise ValueError(
                f"{self.option_id}: requires_profile_permission "
                "exige required_profile_field"
            )
        # Capacidade perigosa NUNCA nasce available por default.
        if self.risk_impact in (
            OptionRiskImpact.HIGH, OptionRiskImpact.CRITICAL,
        ) and self.execution_impact is ExecutionImpact.REAL_POSSIBLE:
            if self.default_enabled:
                raise ValueError(
                    f"{self.option_id}: opcao perigosa nao pode ser "
                    "default_enabled"
                )
            if not (self.requires_gate or
                    self.status is OptionStatus.BLOCKED):
                raise ValueError(
                    f"{self.option_id}: opcao perigosa exige gate "
                    "ou status BLOCKED"
                )
        for tf in ("supported_modes", "supported_providers",
                   "missing_information", "depends_on",
                   "conflicts_with"):
            v = getattr(self, tf)
            if not isinstance(v, tuple):
                object.__setattr__(self, tf, tuple(v))

    def current_enabled(self) -> bool:
        """Estado ATUAL: gate ENV ligado (quando ha gate) ou default."""
        if self.status in (
            OptionStatus.BLOCKED, OptionStatus.NOT_IMPLEMENTED,
        ):
            return False
        if self.required_gate_name:
            return os.environ.get(
                self.required_gate_name, "",
            ).strip().lower() in ("true", "1", "yes")
        return self.default_enabled

    def to_dict(self) -> dict:
        return {
            "option_id": self.option_id,
            "source_location": self.source_location,
            "label": self.label,
            "description": self.description,
            "category": self.category,
            "default_enabled": bool(self.default_enabled),
            "current_enabled": bool(self.current_enabled()),
            "selectable_by_user": bool(self.selectable_by_user),
            "requires_gate": bool(self.requires_gate),
            "required_gate_name": self.required_gate_name,
            "requires_profile_permission": bool(
                self.requires_profile_permission
            ),
            "required_profile_field": self.required_profile_field,
            "requires_operator_confirmation": bool(
                self.requires_operator_confirmation
            ),
            "requires_manual_review": bool(
                self.requires_manual_review
            ),
            "risk_impact": self.risk_impact.value,
            "execution_impact": self.execution_impact.value,
            "supported_modes": list(self.supported_modes),
            "supported_providers": list(self.supported_providers),
            "blocked_reason": self.blocked_reason,
            "missing_information": list(self.missing_information),
            "depends_on": list(self.depends_on),
            "conflicts_with": list(self.conflicts_with),
            "audit_required": bool(self.audit_required),
            "telemetry_required": bool(self.telemetry_required),
            "report_required": bool(self.report_required),
            "ui_group": self.ui_group,
            "ui_order": int(self.ui_order),
            "status": self.status.value,
        }


__all__ = [
    "ExecutionImpact",
    "OperationalOption",
    "OptionRiskImpact",
    "OptionStatus",
]
