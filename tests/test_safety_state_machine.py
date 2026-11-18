"""
Testes de SafetyStateMachine (FASE 16)
=======================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordens.

Cobertura:
    - Estado inicial NORMAL.
    - Transições válidas e inválidas.
    - can_open_new_position / can_modify_positions / can_read_state /
      requires_operator_ack em cada estado.
    - acknowledge não volta para NORMAL.
    - resolve só após OPERATOR_ACKNOWLEDGED.
    - reset só após RESOLVED.
    - InvalidSafetyTransition em transições inválidas.
    - history é tuple imutável.
    - Token e notes sanitizados em logs/metadata.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from crypto_trading_bot.operational_safety import (
    InvalidSafetyTransition,
    SafetyState,
    SafetyStateMachine,
)


# ---------------------------------------------------------------------------
# Estado inicial e flags
# ---------------------------------------------------------------------------

class TestInitialState:

    def test_default_initial_is_normal(self):
        m = SafetyStateMachine()
        assert m.state is SafetyState.NORMAL

    def test_custom_initial_state(self):
        m = SafetyStateMachine(initial_state=SafetyState.MANUAL_REVIEW_REQUIRED)
        assert m.state is SafetyState.MANUAL_REVIEW_REQUIRED

    def test_rejects_non_safety_state(self):
        with pytest.raises(TypeError):
            SafetyStateMachine(initial_state="normal")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Properties read-only por estado
# ---------------------------------------------------------------------------

class TestReadOnlyProperties:

    def test_normal_allows_everything(self):
        m = SafetyStateMachine()
        assert m.can_open_new_position is True
        assert m.can_modify_positions is True
        assert m.can_read_state is True
        assert m.requires_operator_ack is False

    def test_manual_review_blocks_open_allows_modify(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="test")
        assert m.can_open_new_position is False
        assert m.can_modify_positions is True  # halt ativo é mais grave
        assert m.can_read_state is True
        assert m.requires_operator_ack is True

    def test_safety_halt_recommended_blocks_open(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="test")
        assert m.can_open_new_position is False
        assert m.can_modify_positions is True
        assert m.can_read_state is True
        assert m.requires_operator_ack is False  # ainda sem ack obrigatório

    def test_safety_halt_active_blocks_open_and_modify(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="t")
        m.activate_safety_halt(reason="t")
        assert m.can_open_new_position is False
        assert m.can_modify_positions is False
        assert m.can_read_state is True
        assert m.requires_operator_ack is True

    def test_operator_acknowledged_still_blocks_open(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com", notes="ok")
        assert m.state is SafetyState.OPERATOR_ACKNOWLEDGED
        # ack NÃO basta — precisa resolve+reset para liberar
        assert m.can_open_new_position is False
        assert m.requires_operator_ack is False


# ---------------------------------------------------------------------------
# Transições válidas
# ---------------------------------------------------------------------------

class TestValidTransitions:

    def test_normal_to_manual_review(self):
        m = SafetyStateMachine()
        evt = m.mark_manual_review_required(reason="triangulation")
        assert m.state is SafetyState.MANUAL_REVIEW_REQUIRED
        assert evt.from_state is SafetyState.NORMAL
        assert evt.to_state is SafetyState.MANUAL_REVIEW_REQUIRED
        assert evt.event_type == "MANUAL_REVIEW_REQUIRED"

    def test_normal_to_safety_halt_recommended(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="rec")
        assert m.state is SafetyState.SAFETY_HALT_RECOMMENDED

    def test_recommended_to_active(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="r")
        evt = m.activate_safety_halt(reason="op decision")
        assert m.state is SafetyState.SAFETY_HALT_ACTIVE
        assert evt.event_type == "SAFETY_HALT_TRIGGERED"

    def test_manual_review_to_acknowledged(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        assert m.state is SafetyState.OPERATOR_ACKNOWLEDGED

    def test_halt_active_to_acknowledged(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="t")
        m.activate_safety_halt(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        assert m.state is SafetyState.OPERATOR_ACKNOWLEDGED

    def test_acknowledged_to_resolved(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        evt = m.resolve(resolution_notes="checked manually")
        assert m.state is SafetyState.RESOLVED
        assert evt.event_type == "SAFETY_STATE_RESOLVED"

    def test_resolved_to_normal_via_reset(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        m.resolve()
        m.reset()
        assert m.state is SafetyState.NORMAL


# ---------------------------------------------------------------------------
# Transições inválidas
# ---------------------------------------------------------------------------

class TestInvalidTransitions:

    def test_normal_cannot_directly_activate_halt(self):
        m = SafetyStateMachine()
        with pytest.raises(InvalidSafetyTransition):
            m.activate_safety_halt(reason="x")

    def test_manual_review_cannot_directly_resolve(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        with pytest.raises(InvalidSafetyTransition):
            m.resolve()

    def test_normal_cannot_acknowledge(self):
        m = SafetyStateMachine()
        with pytest.raises(InvalidSafetyTransition):
            m.acknowledge(operator_ack_token="op@example.com")

    def test_normal_cannot_reset(self):
        m = SafetyStateMachine()
        with pytest.raises(InvalidSafetyTransition):
            m.reset()

    def test_acknowledged_cannot_reset_directly(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        with pytest.raises(InvalidSafetyTransition):
            m.reset()


# ---------------------------------------------------------------------------
# Ack validation + sanitização
# ---------------------------------------------------------------------------

class TestAckValidation:

    def test_acknowledge_requires_non_empty_token(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        with pytest.raises(ValueError, match="operator_ack_token"):
            m.acknowledge(operator_ack_token="")
        with pytest.raises(ValueError, match="operator_ack_token"):
            m.acknowledge(operator_ack_token="   ")

    def test_acknowledge_does_not_return_to_normal(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        m.acknowledge(operator_ack_token="op@example.com")
        assert m.state is SafetyState.OPERATOR_ACKNOWLEDGED
        assert m.state is not SafetyState.NORMAL

    def test_token_sanitized_in_metadata(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        evt = m.acknowledge(
            operator_ack_token="consultorialumos@gmail.com",
            notes="checked",
        )
        # Token sanitizado: truncado em 8 + "..."
        assert evt.metadata["ack_token_sanitized"] == "consulto..."

    def test_token_with_suspicious_content_redacted(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        evt = m.acknowledge(operator_ack_token="api_key=ABC")
        assert evt.metadata["ack_token_sanitized"] == "<redacted_suspicious_token>"

    def test_notes_with_suspicious_content_redacted(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        evt = m.acknowledge(
            operator_ack_token="op@example.com",
            notes="api_secret=XYZ accidentally",
        )
        assert evt.metadata["ack_notes_sanitized"] == "<redacted_suspicious_notes>"


# ---------------------------------------------------------------------------
# History é tuple imutável
# ---------------------------------------------------------------------------

class TestHistory:

    def test_history_starts_empty(self):
        m = SafetyStateMachine()
        assert m.history == ()
        assert isinstance(m.history, tuple)

    def test_history_accumulates_events(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t1")
        m.acknowledge(operator_ack_token="op@example.com")
        m.resolve()
        m.reset()
        history = m.history
        assert len(history) == 4
        assert history[0].event_type == "MANUAL_REVIEW_REQUIRED"
        assert history[1].event_type == "OPERATOR_ACKNOWLEDGED"
        assert history[2].event_type == "SAFETY_STATE_RESOLVED"
        assert history[3].event_type == "SAFETY_STATE_RESET"

    def test_history_is_tuple_immutable(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="t")
        history = m.history
        # tuple não tem append
        assert not hasattr(history, "append")


# ---------------------------------------------------------------------------
# Helper from_safety_flags (duck-typed)
# ---------------------------------------------------------------------------

class _FakeFlags:
    """Fake duck-typed sem importar BybitDemoExecutor/DemoExecutionResult."""

    def __init__(self, *, manual_review_required=False,
                 safety_halt_recommended=False,
                 reconciliation_confidence="canonical",
                 reason="", metadata=None):
        self.manual_review_required = manual_review_required
        self.safety_halt_recommended = safety_halt_recommended
        self.reconciliation_confidence = reconciliation_confidence
        self.reason = reason
        self.metadata = metadata or {}


class TestFromSafetyFlags:

    def test_no_flags_keeps_normal(self):
        m = SafetyStateMachine()
        flags = _FakeFlags()
        evt = m.from_safety_flags(flags)
        assert evt is None
        assert m.state is SafetyState.NORMAL

    def test_manual_review_only_moves_to_manual_review(self):
        m = SafetyStateMachine()
        flags = _FakeFlags(manual_review_required=True, reason="triangulation")
        evt = m.from_safety_flags(flags)
        assert evt is not None
        assert m.state is SafetyState.MANUAL_REVIEW_REQUIRED
        assert evt.metadata["manual_review_required"] is True
        assert evt.metadata["safety_halt_recommended"] is False

    def test_safety_halt_only_moves_to_recommended(self):
        m = SafetyStateMachine()
        flags = _FakeFlags(safety_halt_recommended=True, reason="halt")
        evt = m.from_safety_flags(flags)
        assert m.state is SafetyState.SAFETY_HALT_RECOMMENDED

    def test_both_flags_take_severer_path(self):
        m = SafetyStateMachine()
        flags = _FakeFlags(
            manual_review_required=True,
            safety_halt_recommended=True,
            reason="triangulation+halt",
        )
        evt = m.from_safety_flags(flags)
        assert m.state is SafetyState.SAFETY_HALT_RECOMMENDED
        # Metadata registra que manual_review também estava pendente
        assert evt.metadata["manual_review_required"] is True
        assert evt.metadata["safety_halt_recommended"] is True

    def test_does_not_transition_if_not_in_normal(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="x")
        # Já em estado ambíguo — não pode transitar automaticamente
        flags = _FakeFlags(safety_halt_recommended=True)
        evt = m.from_safety_flags(flags)
        assert evt is None
        assert m.state is SafetyState.MANUAL_REVIEW_REQUIRED


# ---------------------------------------------------------------------------
# Audit log sanitização
# ---------------------------------------------------------------------------

class TestAuditSanitization:

    def test_audit_line_contains_no_secrets(self, monkeypatch):
        import crypto_trading_bot.operational_safety.safety_state_machine as mod
        captured: list[str] = []

        class FakeAudit:
            def info(self, msg):
                captured.append(msg)

        monkeypatch.setattr(mod, "_audit", FakeAudit())
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="api_key=XYZ test")
        m.acknowledge(
            operator_ack_token="consultorialumos@gmail.com",
            notes="some notes",
        )
        assert len(captured) == 2
        combined = " ".join(captured).lower()
        # Token original NÃO deve aparecer no log; apenas sanitizado
        assert "consultorialumos@gmail.com" not in combined
        # Tokens proibidos
        for tok in ("api_secret", "x-bapi-sign", "bearer ", "authorization:"):
            assert tok not in combined


# ---------------------------------------------------------------------------
# Isolamento estrutural
# ---------------------------------------------------------------------------

class TestStructuralIsolation:

    def _src(self, mod) -> str:
        return open(mod.__file__, "r", encoding="utf-8").read()

    def test_safety_state_does_not_import_executors(self):
        import crypto_trading_bot.operational_safety.safety_state as mod
        src = self._src(mod)
        forbidden = [
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.risk.risk_engine",
            "import httpx",
            "from httpx",
        ]
        for line in forbidden:
            assert line not in src

    def test_state_machine_does_not_import_executors(self):
        import crypto_trading_bot.operational_safety.safety_state_machine as mod
        src = self._src(mod)
        forbidden = [
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.risk.risk_engine",
            "from crypto_trading_bot.core.bot_engine",
            "import httpx",
            "from httpx",
        ]
        for line in forbidden:
            assert line not in src
