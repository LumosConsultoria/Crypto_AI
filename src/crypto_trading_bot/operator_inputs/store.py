"""
Operator Inputs - store + validacao + report (FASE 36 Bloco L)
===============================================================
Persistencia JSON AUDITAVEL (antes/depois, operador, timestamp),
validacao de status por campo e RequiredInputsForDemoReport.

⚠️  Offline. Valor obrigatorio ausente/invalid/stale => bloqueia
    readiness/execucao real (blocked_missing_operator_input).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.operator_inputs.input_model import (
    InputStatus,
    InputType,
    MissingOperatorInput,
    OperatorInputRequirement,
    OperatorInputValue,
)


class OperatorInputStore:
    """Store JSON com audit trail. Arquivo local; nunca secrets."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        if any(p == ".." for p in self._path.parts):
            raise ValueError("store path contem '..' (rejeitado)")
        self._data: Dict[str, Any] = {"values": {}, "audit": []}
        if self._path.is_file():
            try:
                loaded = json.loads(
                    self._path.read_text(encoding="utf-8"),
                )
                if isinstance(loaded, dict):
                    self._data = {
                        "values": dict(loaded.get("values") or {}),
                        "audit": list(loaded.get("audit") or []),
                    }
            except Exception:  # noqa: BLE001
                pass  # arquivo corrompido: comeca limpo (audit preservado em backup manual)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    def set_value(
        self, input_id: str, value: Any, *, operator_token: str,
        now: Optional[datetime] = None,
    ) -> None:
        """Define valor + registra antes/depois no audit trail."""
        if not operator_token.strip():
            raise ValueError("operator_token obrigatorio")
        now = now or datetime.now(timezone.utc)
        old = self._data["values"].get(input_id)
        self._data["values"][input_id] = {
            "value": value,
            "informed_by": operator_token,
            "informed_at": now.isoformat(),
            "confirmed": False,
            "confirmed_by": None,
            "confirmed_at": None,
        }
        self._data["audit"].append({
            "input_id": input_id,
            "old_value": (old or {}).get("value"),
            "new_value": value,
            "operator_token": operator_token,
            "timestamp": now.isoformat(),
            "action": "set",
        })
        self._persist()

    def confirm(
        self, input_id: str, *, operator_token: str,
        now: Optional[datetime] = None,
    ) -> bool:
        """Confirmacao humana explicita de um valor presente."""
        now = now or datetime.now(timezone.utc)
        entry = self._data["values"].get(input_id)
        if entry is None:
            return False
        entry["confirmed"] = True
        entry["confirmed_by"] = operator_token
        entry["confirmed_at"] = now.isoformat()
        self._data["audit"].append({
            "input_id": input_id,
            "operator_token": operator_token,
            "timestamp": now.isoformat(),
            "action": "confirm",
        })
        self._persist()
        return True

    def get(self, input_id: str) -> Optional[OperatorInputValue]:
        entry = self._data["values"].get(input_id)
        if entry is None:
            return None
        try:
            return OperatorInputValue(
                input_id=input_id,
                value=entry.get("value"),
                informed_by=str(entry.get("informed_by", "")),
                informed_at=datetime.fromisoformat(
                    str(entry.get("informed_at")),
                ),
                confirmed=bool(entry.get("confirmed", False)),
                confirmed_by=entry.get("confirmed_by"),
                confirmed_at=(
                    datetime.fromisoformat(
                        str(entry["confirmed_at"]),
                    )
                    if entry.get("confirmed_at") else None
                ),
            )
        except (ValueError, TypeError):
            return None

    @property
    def audit_trail(self) -> List[dict]:
        return list(self._data["audit"])


# ---------------------------------------------------------------------------
# Validacao
# ---------------------------------------------------------------------------

def _validate_value(
    req: OperatorInputRequirement, value: Any,
) -> Tuple[bool, str]:
    """(valido, motivo)."""
    t = req.input_type
    if t in (InputType.INT, InputType.DURATION):
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"esperado int; recebido {type(value).__name__}"
        num = float(value)
    elif t in (InputType.DECIMAL, InputType.PERCENT):
        if not isinstance(value, (int, float)) or \
                isinstance(value, bool):
            return False, "esperado numerico"
        num = float(value)
    elif t is InputType.BOOL:
        if not isinstance(value, bool):
            return False, "esperado bool"
        return True, ""
    elif t is InputType.ENUM:
        if value not in req.enum_values:
            return False, f"valor fora de {list(req.enum_values)}"
        return True, ""
    else:  # STRING
        if not isinstance(value, str) or not value.strip():
            return False, "esperado string nao-vazia"
        return True, ""
    if req.min_value is not None and num < req.min_value:
        return False, f"{num} < min {req.min_value}"
    if req.max_value is not None and num > req.max_value:
        return False, f"{num} > max {req.max_value}"
    return True, ""


@dataclass(frozen=True)
class OperatorInputValidationResult:
    """Resultado consolidado da validacao do schema."""
    statuses: Mapping[str, str]
    missing: Tuple[MissingOperatorInput, ...]
    blocks_readiness: bool
    blocks_execution: bool

    def to_dict(self) -> dict:
        return {
            "statuses": dict(self.statuses),
            "missing": [m.to_dict() for m in self.missing],
            "blocks_readiness": bool(self.blocks_readiness),
            "blocks_execution": bool(self.blocks_execution),
        }


def validate_operator_inputs(
    *,
    schema: Sequence[OperatorInputRequirement],
    store: OperatorInputStore,
    now: Optional[datetime] = None,
) -> OperatorInputValidationResult:
    """Valida cada requisito contra o store.

    Status por campo: present | missing | invalid | stale |
    needs_confirmation. Campo obrigatorio nao-present => entra em
    missing[] com flags de bloqueio do requisito.
    """
    now = now or datetime.now(timezone.utc)
    statuses: Dict[str, str] = {}
    missing: List[MissingOperatorInput] = []

    for req in schema:
        val = store.get(req.input_id)
        if val is None:
            if req.can_have_default and req.safe_default is not None:
                statuses[req.input_id] = InputStatus.PRESENT.value
                continue
            status = InputStatus.MISSING
            reason = "valor nao informado pelo operador"
        else:
            ok, why = _validate_value(req, val.value)
            if not ok:
                status = InputStatus.INVALID
                reason = why
            elif req.max_age_days is not None and (
                now - val.informed_at
                > timedelta(days=req.max_age_days)
            ):
                status = InputStatus.STALE
                reason = (
                    f"valor expirou (> {req.max_age_days} dias)"
                )
            elif req.needs_human_confirmation and not val.confirmed:
                status = InputStatus.NEEDS_CONFIRMATION
                reason = "valor presente mas nao confirmado"
            else:
                statuses[req.input_id] = InputStatus.PRESENT.value
                continue
        statuses[req.input_id] = status.value
        if req.required_for_demo:
            missing.append(MissingOperatorInput(
                input_id=req.input_id,
                label=req.label,
                status=status,
                reason=reason,
                blocks_readiness=req.blocks_readiness_if_missing,
                blocks_execution=req.blocks_execution_if_missing,
            ))

    return OperatorInputValidationResult(
        statuses=statuses,
        missing=tuple(missing),
        blocks_readiness=any(m.blocks_readiness for m in missing),
        blocks_execution=any(m.blocks_execution for m in missing),
    )


def get_effective_value(
    *,
    schema: Sequence[OperatorInputRequirement],
    store: OperatorInputStore,
    input_id: str,
) -> Any:
    """Valor efetivo: store > safe_default > None (NUNCA inventa)."""
    req = next(
        (r for r in schema if r.input_id == input_id), None,
    )
    val = store.get(input_id)
    if val is not None:
        return val.value
    if req is not None and req.can_have_default:
        return req.safe_default
    return None


# ---------------------------------------------------------------------------
# RequiredInputsForDemoReport
# ---------------------------------------------------------------------------

def build_required_inputs_for_demo_report(
    *,
    schema: Sequence[OperatorInputRequirement],
    store: OperatorInputStore,
    now: Optional[datetime] = None,
) -> dict:
    """Relatorio exigido pelo plano antes de QUALQUER demo real:
    o que veio de API/config/calculo, o que o operador informou,
    o que falta, o que bloqueia readiness e o que bloqueia execucao."""
    now = now or datetime.now(timezone.utc)
    result = validate_operator_inputs(
        schema=schema, store=store, now=now,
    )
    by_source: Dict[str, List[dict]] = {}
    for req in schema:
        row = {
            "input_id": req.input_id,
            "label": req.label,
            "status": result.statuses.get(req.input_id),
            "required_for_demo": req.required_for_demo,
        }
        val = store.get(req.input_id)
        if val is not None:
            row["last_value"] = val.value
            row["informed_by"] = val.informed_by
            row["informed_at"] = val.informed_at.isoformat()
            row["confirmed"] = val.confirmed
        elif req.can_have_default and req.safe_default is not None:
            row["last_value"] = req.safe_default
            row["from_safe_default"] = True
        by_source.setdefault(
            req.expected_source.value, [],
        ).append(row)

    return {
        "schema": "required_inputs_for_demo_report_v1",
        "generated_at": now.isoformat(),
        "by_source": by_source,
        "statuses": dict(result.statuses),
        "missing": [m.to_dict() for m in result.missing],
        "blocks_readiness": result.blocks_readiness,
        "blocks_execution": result.blocks_execution,
        "note": (
            "Valores obrigatorios ausentes BLOQUEIAM execucao real. "
            "NENHUM valor e inventado pelo sistema."
        ),
    }


__all__ = [
    "OperatorInputStore",
    "OperatorInputValidationResult",
    "build_required_inputs_for_demo_report",
    "get_effective_value",
    "validate_operator_inputs",
]
