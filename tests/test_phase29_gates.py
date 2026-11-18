"""
Tests - FASE 29 gates (entry + close)
=========================================
100% offline. ZERO network.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.demo_endurance import (
    ENV_REAL_ORDER_ENABLED,
    ENV_REDUCE_ONLY_CLOSE_ENABLED,
    ENV_USE_DEMO,
    EXPECTED_PHRASE,
    Phase29GateResult,
    validate_phase29_close_gate,
    validate_phase29_entry_gate,
)


def _entry_default(monkeypatch, **overrides):
    monkeypatch.setenv(ENV_REAL_ORDER_ENABLED, "true")
    monkeypatch.setenv(ENV_USE_DEMO, "true")
    base = dict(
        phrase_confirmation=EXPECTED_PHRASE,
        flag_apply_demo_real=True,
        flag_confirm_demo_endurance=True,
        flag_i_understand=True,
        flag_execute_real=True,
        flag_first_real_demo_order=True,
        prompt_y_confirmed=True,
        operator_token="OPTOK",
        tty_present=True,
        non_interactive_assume_no=False,
    )
    base.update(overrides)
    return base


class TestEntryGateApproved:

    def test_happy_path_approves(self, monkeypatch):
        r = validate_phase29_entry_gate(**_entry_default(monkeypatch))
        assert r.approved
        assert r.gate_name == "entry"


class TestEntryGateBlockers:

    def test_env_real_order_enabled_missing(self, monkeypatch):
        monkeypatch.delenv(ENV_REAL_ORDER_ENABLED, raising=False)
        monkeypatch.setenv(ENV_USE_DEMO, "true")
        r = validate_phase29_entry_gate(**_entry_default(monkeypatch))
        # Even though _entry_default sets the env, delenv removed first;
        # but _entry_default re-sets. We force delete after:
        monkeypatch.delenv(ENV_REAL_ORDER_ENABLED, raising=False)
        r = validate_phase29_entry_gate(**_entry_default(monkeypatch))
        # _entry_default re-sets again. Use direct call:
        kw = _entry_default(monkeypatch)
        monkeypatch.delenv(ENV_REAL_ORDER_ENABLED, raising=False)
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved
        assert any(ENV_REAL_ORDER_ENABLED in b for b in r.blockers)

    def test_env_use_demo_missing(self, monkeypatch):
        kw = _entry_default(monkeypatch)
        monkeypatch.delenv(ENV_USE_DEMO, raising=False)
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved
        assert any(ENV_USE_DEMO in b for b in r.blockers)

    def test_phrase_wrong(self, monkeypatch):
        kw = _entry_default(monkeypatch,
                            phrase_confirmation="I authorize wrong")
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved
        assert any("phrase" in b for b in r.blockers)

    def test_phrase_empty(self, monkeypatch):
        kw = _entry_default(monkeypatch, phrase_confirmation="")
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved

    def test_each_flag_missing(self, monkeypatch):
        for flag in (
            "flag_apply_demo_real", "flag_confirm_demo_endurance",
            "flag_i_understand", "flag_execute_real",
            "flag_first_real_demo_order",
        ):
            kw = _entry_default(monkeypatch, **{flag: False})
            r = validate_phase29_entry_gate(**kw)
            assert not r.approved, f"missing {flag} should reject"

    def test_no_prompt_y(self, monkeypatch):
        kw = _entry_default(monkeypatch, prompt_y_confirmed=False)
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved

    def test_no_tty(self, monkeypatch):
        kw = _entry_default(monkeypatch, tty_present=False)
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved

    def test_non_interactive_assume_no(self, monkeypatch):
        kw = _entry_default(monkeypatch,
                            non_interactive_assume_no=True)
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved

    def test_empty_operator_token(self, monkeypatch):
        kw = _entry_default(monkeypatch, operator_token="")
        r = validate_phase29_entry_gate(**kw)
        assert not r.approved


def _close_default(monkeypatch, **overrides):
    monkeypatch.setenv(ENV_REDUCE_ONLY_CLOSE_ENABLED, "true")
    base = dict(
        has_open_position=True,
        position_qty=0.003,
        requested_close_qty=0.003,
        exit_decision_requires_reduce_only=True,
        exit_decision_should_close=True,
        safety_state="normal",
        safety_halt_recommended=False,
        close_orders_submitted_so_far=0,
        max_close_orders=1,
        operator_token="OPTOK",
    )
    base.update(overrides)
    return base


class TestCloseGateApproved:

    def test_happy_path(self, monkeypatch):
        r = validate_phase29_close_gate(**_close_default(monkeypatch))
        assert r.approved
        assert r.gate_name == "close"


class TestCloseGateBlockers:

    def test_separate_env_required(self, monkeypatch):
        kw = _close_default(monkeypatch)
        monkeypatch.delenv(ENV_REDUCE_ONLY_CLOSE_ENABLED, raising=False)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved
        assert any(ENV_REDUCE_ONLY_CLOSE_ENABLED in b
                   for b in r.blockers)

    def test_no_open_position(self, monkeypatch):
        kw = _close_default(monkeypatch, has_open_position=False)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved
        assert any("no open position" in b for b in r.blockers)

    def test_position_qty_zero(self, monkeypatch):
        kw = _close_default(monkeypatch, position_qty=0)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved

    def test_partial_close_rejected(self, monkeypatch):
        kw = _close_default(
            monkeypatch, position_qty=0.003, requested_close_qty=0.001,
        )
        r = validate_phase29_close_gate(**kw)
        assert not r.approved
        assert any("partial close" in b for b in r.blockers)

    def test_should_close_false(self, monkeypatch):
        kw = _close_default(monkeypatch,
                            exit_decision_should_close=False)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved

    def test_requires_reduce_only_false(self, monkeypatch):
        kw = _close_default(monkeypatch,
                            exit_decision_requires_reduce_only=False)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved

    def test_safety_state_blocked(self, monkeypatch):
        kw = _close_default(monkeypatch, safety_state="halt")
        r = validate_phase29_close_gate(**kw)
        assert not r.approved

    def test_max_close_orders_exceeded(self, monkeypatch):
        kw = _close_default(
            monkeypatch, close_orders_submitted_so_far=1,
            max_close_orders=1,
        )
        r = validate_phase29_close_gate(**kw)
        assert not r.approved

    def test_empty_operator_token(self, monkeypatch):
        kw = _close_default(monkeypatch, operator_token="")
        r = validate_phase29_close_gate(**kw)
        assert not r.approved


class TestGateEnvsSeparated:
    """Garantia explicita: entry gate NAO desbloqueia close gate."""

    def test_entry_env_does_not_unlock_close(self, monkeypatch):
        # Entry env presente, close env ausente
        monkeypatch.setenv(ENV_REAL_ORDER_ENABLED, "true")
        monkeypatch.delenv(ENV_REDUCE_ONLY_CLOSE_ENABLED, raising=False)
        kw = _close_default(monkeypatch)
        monkeypatch.delenv(ENV_REDUCE_ONLY_CLOSE_ENABLED, raising=False)
        r = validate_phase29_close_gate(**kw)
        assert not r.approved
