"""
Testes de SafetyState + SafetyEvent (FASE 16)
================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordens.

Cobertura:
    - SafetyState tem valores estáveis.
    - SafetyEvent é frozen, serializável, timestamp UTC.
    - metadata é MappingProxyType (read-only).
    - to_dict é JSON-serializável.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.operational_safety import (
    InvalidSafetyTransition,
    SafetyEvent,
    SafetyState,
)


class TestSafetyStateEnum:

    def test_values_stable(self):
        assert SafetyState.NORMAL.value == "normal"
        assert SafetyState.MANUAL_REVIEW_REQUIRED.value == "manual_review_required"
        assert SafetyState.SAFETY_HALT_RECOMMENDED.value == "safety_halt_recommended"
        assert SafetyState.SAFETY_HALT_ACTIVE.value == "safety_halt_active"
        assert SafetyState.OPERATOR_ACKNOWLEDGED.value == "operator_acknowledged"
        assert SafetyState.RESOLVED.value == "resolved"

    def test_is_string_enum(self):
        assert isinstance(SafetyState.NORMAL.value, str)
        assert SafetyState.NORMAL == "normal"


class TestSafetyEvent:

    def _make_event(self, **kw):
        defaults = dict(
            event_type="MANUAL_REVIEW_REQUIRED",
            from_state=SafetyState.NORMAL,
            to_state=SafetyState.MANUAL_REVIEW_REQUIRED,
            reason="trianguação detectada",
        )
        defaults.update(kw)
        return SafetyEvent(**defaults)

    def test_frozen(self):
        e = self._make_event()
        with pytest.raises(Exception):
            e.event_type = "X"  # type: ignore[misc]

    def test_naive_timestamp_promoted_to_utc(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        e = self._make_event(triggered_at=naive)
        assert e.triggered_at.tzinfo == timezone.utc

    def test_metadata_becomes_mappingproxy(self):
        e = self._make_event(metadata={"foo": "bar"})
        assert isinstance(e.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            e.metadata["foo"] = "baz"  # type: ignore[index]

    def test_empty_event_type_rejected(self):
        with pytest.raises(ValueError, match="event_type"):
            self._make_event(event_type="")

    def test_to_dict_json_serializable(self):
        e = self._make_event(
            metadata={"order_id": "X1", "details": [1, 2, 3]},
        )
        d = e.to_dict()
        # Estrutura
        assert d["event_type"] == "MANUAL_REVIEW_REQUIRED"
        assert d["from_state"] == "normal"
        assert d["to_state"] == "manual_review_required"
        # Serializável
        json.dumps(d)


class TestInvalidSafetyTransitionException:

    def test_is_value_error_subclass(self):
        assert issubclass(InvalidSafetyTransition, ValueError)

    def test_can_be_raised_and_caught(self):
        with pytest.raises(InvalidSafetyTransition, match="transição"):
            raise InvalidSafetyTransition("transição inválida")
