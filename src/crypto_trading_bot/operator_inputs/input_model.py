"""
Operator Inputs - modelos (FASE 36 Bloco L)
============================================
Tudo que o bot NAO consegue obter sozinho (API/config/calculo seguro)
vira requisito explicito do operador. Valor obrigatorio ausente =>
bloqueia readiness/execucao real. NUNCA inventar valor.

⚠️  Offline/puro. ZERO secret (valores de risco/limites apenas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Tuple


class InputSource(str, Enum):
    API_DERIVED = "api_derived"
    CONFIG_DERIVED = "config_derived"
    CALCULATED = "calculated"
    OPERATOR_REQUIRED = "operator_required"
    OPERATOR_CONFIRMATION_REQUIRED = "operator_confirmation_required"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class InputStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    INVALID = "invalid"
    STALE = "stale"
    NEEDS_CONFIRMATION = "needs_confirmation"


class InputType(str, Enum):
    INT = "int"
    DECIMAL = "decimal"
    PERCENT = "percent"
    BOOL = "bool"
    ENUM = "enum"
    STRING = "string"
    DURATION = "duration"


class RiskImpact(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class OperatorInputRequirement:
    """Especificacao de UM campo operacional."""

    input_id: str
    label: str
    description: str
    input_type: InputType
    category: str                      # account|risk|position_mgmt|strategy|ai_mi|demo_execution
    expected_source: InputSource
    required_for_demo: bool = False
    can_have_default: bool = False
    safe_default: Optional[Any] = None  # APENAS quando can_have_default
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    enum_values: Tuple[str, ...] = field(default_factory=tuple)
    operational_impact: str = ""
    risk_impact: RiskImpact = RiskImpact.MEDIUM
    used_by: Tuple[str, ...] = field(default_factory=tuple)
    ui_visible: bool = True
    blocks_readiness_if_missing: bool = False
    blocks_execution_if_missing: bool = False
    needs_human_confirmation: bool = False
    max_age_days: Optional[int] = None   # None = nao expira

    def __post_init__(self) -> None:
        if not self.input_id.strip():
            raise ValueError("input_id nao pode ser vazio")
        if self.safe_default is not None and not self.can_have_default:
            raise ValueError(
                f"{self.input_id}: safe_default exige "
                "can_have_default=True"
            )
        for tf in ("enum_values", "used_by"):
            v = getattr(self, tf)
            if not isinstance(v, tuple):
                object.__setattr__(self, tf, tuple(v))

    def to_dict(self) -> dict:
        return {
            "input_id": self.input_id,
            "label": self.label,
            "description": self.description,
            "type": self.input_type.value,
            "category": self.category,
            "expected_source": self.expected_source.value,
            "required_for_demo": bool(self.required_for_demo),
            "can_have_default": bool(self.can_have_default),
            "safe_default": self.safe_default,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "enum_values": list(self.enum_values),
            "operational_impact": self.operational_impact,
            "risk_impact": self.risk_impact.value,
            "used_by": list(self.used_by),
            "ui_visible": bool(self.ui_visible),
            "blocks_readiness_if_missing": bool(
                self.blocks_readiness_if_missing
            ),
            "blocks_execution_if_missing": bool(
                self.blocks_execution_if_missing
            ),
            "needs_human_confirmation": bool(
                self.needs_human_confirmation
            ),
            "max_age_days": self.max_age_days,
        }


@dataclass(frozen=True)
class OperatorInputValue:
    """Valor informado pelo operador (com auditoria)."""

    input_id: str
    value: Any
    informed_by: str                  # operator_token
    informed_at: datetime
    confirmed: bool = False
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.informed_at.tzinfo is None:
            object.__setattr__(
                self, "informed_at",
                self.informed_at.replace(tzinfo=timezone.utc),
            )

    def to_dict(self) -> dict:
        return {
            "input_id": self.input_id,
            "value": self.value,
            "informed_by": self.informed_by,
            "informed_at": self.informed_at.isoformat(),
            "confirmed": bool(self.confirmed),
            "confirmed_by": self.confirmed_by,
            "confirmed_at": (
                self.confirmed_at.isoformat()
                if self.confirmed_at else None
            ),
        }


@dataclass(frozen=True)
class MissingOperatorInput:
    """Campo ausente/invalido que bloqueia algo."""
    input_id: str
    label: str
    status: InputStatus
    reason: str
    blocks_readiness: bool
    blocks_execution: bool

    def to_dict(self) -> dict:
        return {
            "input_id": self.input_id,
            "label": self.label,
            "status": self.status.value,
            "reason": self.reason,
            "blocks_readiness": bool(self.blocks_readiness),
            "blocks_execution": bool(self.blocks_execution),
        }


__all__ = [
    "InputSource",
    "InputStatus",
    "InputType",
    "MissingOperatorInput",
    "OperatorInputRequirement",
    "OperatorInputValue",
    "RiskImpact",
]
