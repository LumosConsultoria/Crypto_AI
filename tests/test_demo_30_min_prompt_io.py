"""
Tests - prompt_io (FASE 27)
=================================
100% offline. ZERO network. ZERO secret.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.demo_endurance import (
    envvar_present,
    is_tty,
    prompt_yes_or_abort,
    TTYRequired,
)


class TestPromptYesOrAbort:

    def test_assume_no_returns_false_without_prompt(self):
        called = []
        ok = prompt_yes_or_abort(
            "msg",
            assume_no=True,
            tty_check=lambda: True,
            input_fn=lambda m: called.append(m) or "Y",
        )
        assert ok is False
        assert called == []  # nunca chamou input

    def test_tty_present_with_Y_returns_true(self):
        ok = prompt_yes_or_abort(
            "msg",
            tty_check=lambda: True,
            input_fn=lambda m: "Y",
        )
        assert ok is True

    def test_tty_present_with_y_lowercase_returns_false(self):
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: True, input_fn=lambda m: "y",
        )
        assert ok is False

    def test_tty_present_with_no_returns_false(self):
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: True, input_fn=lambda m: "n",
        )
        assert ok is False

    def test_tty_present_with_empty_returns_false(self):
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: True, input_fn=lambda m: "",
        )
        assert ok is False

    def test_tty_absent_without_assume_no_raises(self):
        with pytest.raises(TTYRequired):
            prompt_yes_or_abort(
                "msg", tty_check=lambda: False, input_fn=lambda m: "Y",
            )

    def test_tty_absent_with_assume_no_returns_false(self):
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: False, assume_no=True,
            input_fn=lambda m: "Y",
        )
        assert ok is False

    def test_eof_returns_false(self):
        def raise_eof(m):
            raise EOFError
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: True, input_fn=raise_eof,
        )
        assert ok is False

    def test_keyboard_interrupt_returns_false(self):
        def raise_kbi(m):
            raise KeyboardInterrupt
        ok = prompt_yes_or_abort(
            "msg", tty_check=lambda: True, input_fn=raise_kbi,
        )
        assert ok is False


class TestEnvvarPresent:

    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("TEST_FASE27_XYZ", raising=False)
        assert envvar_present("TEST_FASE27_XYZ") is False

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setenv("TEST_FASE27_XYZ", "")
        assert envvar_present("TEST_FASE27_XYZ") is False

    def test_whitespace_returns_false(self, monkeypatch):
        monkeypatch.setenv("TEST_FASE27_XYZ", "   ")
        assert envvar_present("TEST_FASE27_XYZ") is False

    def test_value_returns_true_no_value_leak(self, monkeypatch):
        monkeypatch.setenv("TEST_FASE27_XYZ", "very-secret-value")
        # Apenas bool, nunca retorna o valor
        result = envvar_present("TEST_FASE27_XYZ")
        assert result is True
        assert result != "very-secret-value"

    def test_invalid_name_returns_false(self):
        assert envvar_present("") is False
        assert envvar_present(None) is False


class TestIsTtyDefault:

    def test_is_tty_callable(self):
        # Em pytest, stdin geralmente nao eh tty.
        v = is_tty()
        assert isinstance(v, bool)

    def test_is_tty_with_fake_stream(self):
        class FakeTTY:
            def isatty(self):
                return True
        assert is_tty(FakeTTY()) is True

        class FakeNoTTY:
            def isatty(self):
                return False
        assert is_tty(FakeNoTTY()) is False

    def test_is_tty_handles_missing_isatty(self):
        class Bare:
            pass
        assert is_tty(Bare()) is False
