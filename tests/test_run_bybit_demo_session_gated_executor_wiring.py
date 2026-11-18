"""
Tests - run_bybit_demo_session_gated.py executor wiring (FASE 21)
======================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Loads the script module via importlib (no subprocess) and unit-tests
the internal wiring functions:
    _compute_real_demo_requested(args)
    _prompt_yes_or_default(timeout, input_fn, isatty_fn)
    _build_real_demo_executor(args, *, factories injected)
    _DryExecutor.execute(...)

All factories are mocked - no BybitClient is ever instantiated for
real. Tests confirm:
    - No real BybitClient or BybitDemoExecutor instantiation without
      complete flags + prompt + valid demo settings.
    - Single instantiation when all gates pass.
    - Sanitized error reasons for every safe-abort path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"


def _load_script_module():
    """Load run_bybit_demo_session_gated.py as a module (no subprocess)."""
    spec = importlib.util.spec_from_file_location(
        "run_bybit_demo_session_gated", str(_SCRIPT_PATH),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Ensure src/ is on path for the module's lazy imports.
    src_path = str(_REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _args_ns(
    *,
    execute_demo: bool = False,
    confirm_demo_session: bool = False,
    operator_token: str = "",
    i_understand_this_is_demo: bool = False,
    capital: float = 5000.0,
    qty_step: str = "0.001",
    prompt_timeout_seconds: float = 60.0,
    non_interactive_assume_no: bool = False,
):
    return SimpleNamespace(
        execute_demo=execute_demo,
        confirm_demo_session=confirm_demo_session,
        operator_token=operator_token,
        i_understand_this_is_demo=i_understand_this_is_demo,
        capital=capital,
        qty_step=qty_step,
        prompt_timeout_seconds=prompt_timeout_seconds,
        non_interactive_assume_no=non_interactive_assume_no,
    )


# ===========================================================================
# _compute_real_demo_requested
# ===========================================================================

class TestComputeRealDemoRequested:

    def test_no_flags_false(self, script_module):
        assert script_module._compute_real_demo_requested(_args_ns()) is False

    def test_only_execute_demo_false(self, script_module):
        args = _args_ns(execute_demo=True)
        assert script_module._compute_real_demo_requested(args) is False

    def test_three_flags_no_token_false(self, script_module):
        args = _args_ns(
            execute_demo=True,
            confirm_demo_session=True,
            i_understand_this_is_demo=True,
            operator_token="",
        )
        assert script_module._compute_real_demo_requested(args) is False

    def test_three_flags_whitespace_token_false(self, script_module):
        args = _args_ns(
            execute_demo=True,
            confirm_demo_session=True,
            i_understand_this_is_demo=True,
            operator_token="   ",
        )
        assert script_module._compute_real_demo_requested(args) is False

    def test_all_four_true(self, script_module):
        args = _args_ns(
            execute_demo=True,
            confirm_demo_session=True,
            i_understand_this_is_demo=True,
            operator_token="operator@example.com",
        )
        assert script_module._compute_real_demo_requested(args) is True


# ===========================================================================
# _prompt_yes_or_default
# ===========================================================================

class TestPromptYesOrDefault:

    def test_non_tty_returns_false(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "Y",
            isatty_fn=lambda: False,
        ) is False

    def test_tty_yes_uppercase_returns_true(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "Y",
            isatty_fn=lambda: True,
        ) is True

    def test_tty_yes_lowercase_returns_true(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "y",
            isatty_fn=lambda: True,
        ) is True

    def test_tty_empty_returns_false(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "",
            isatty_fn=lambda: True,
        ) is False

    def test_tty_no_returns_false(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "n",
            isatty_fn=lambda: True,
        ) is False

    def test_tty_other_returns_false(self, script_module):
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=lambda prompt: "yes please",
            isatty_fn=lambda: True,
        ) is False

    def test_tty_exception_returns_false(self, script_module):
        def _raise(prompt):
            raise RuntimeError("test")
        assert script_module._prompt_yes_or_default(
            timeout_seconds=1.0,
            input_fn=_raise,
            isatty_fn=lambda: True,
        ) is False

    def test_tty_timeout_returns_false(self, script_module):
        import time

        def _slow(prompt):
            time.sleep(2.0)
            return "Y"
        assert script_module._prompt_yes_or_default(
            timeout_seconds=0.2,
            input_fn=_slow,
            isatty_fn=lambda: True,
        ) is False


# ===========================================================================
# _build_real_demo_executor - safe-abort paths
# ===========================================================================

class TestBuildRealDemoExecutorAbortPaths:

    def _common_factories(self):
        """Returns a base dict of factories; tests override specific ones."""
        from crypto_trading_bot.config.settings import TradingMode

        good_settings = SimpleNamespace(
            trading_mode=TradingMode.DEMO,
            enable_demo_execution=True,
        )

        class _Secret:
            def __init__(self, val):
                self._v = val

            def get_secret_value(self):
                return self._v

        good_exchange = SimpleNamespace(
            api_key=_Secret("k_present_NEVER_LEAKED"),
            api_secret=_Secret("s_present_NEVER_LEAKED"),
        )

        fake_client = MagicMock()
        fake_client.environment = "demo"
        fake_client.has_credentials = True

        fake_mode_guard = MagicMock()
        fake_risk_engine = MagicMock()
        fake_executor = MagicMock()
        fake_executor.safe_check_only = MagicMock()

        return dict(
            settings_factory=lambda: good_settings,
            exchange_config_factory=lambda: good_exchange,
            bybit_client_factory=MagicMock(return_value=fake_client),
            mode_guard_factory=MagicMock(return_value=fake_mode_guard),
            risk_engine_factory=MagicMock(return_value=fake_risk_engine),
            bybit_demo_executor_factory=MagicMock(return_value=fake_executor),
            prompt_fn=lambda timeout_seconds: True,
        )

    def test_settings_load_failure(self, script_module):
        factories = self._common_factories()
        def _raise():
            raise RuntimeError("env_broken")
        factories["settings_factory"] = _raise
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason.startswith("settings_load_failed:")

    def test_trading_mode_not_demo(self, script_module):
        from crypto_trading_bot.config.settings import TradingMode
        factories = self._common_factories()
        factories["settings_factory"] = lambda: SimpleNamespace(
            trading_mode=TradingMode.PAPER,
            enable_demo_execution=True,
        )
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "trading_mode_not_demo"
        # bybit_client_factory NEVER called.
        factories["bybit_client_factory"].assert_not_called()

    def test_enable_demo_execution_false(self, script_module):
        from crypto_trading_bot.config.settings import TradingMode
        factories = self._common_factories()
        factories["settings_factory"] = lambda: SimpleNamespace(
            trading_mode=TradingMode.DEMO,
            enable_demo_execution=False,
        )
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "enable_demo_execution_false"
        factories["bybit_client_factory"].assert_not_called()

    def test_credentials_missing(self, script_module):
        factories = self._common_factories()
        factories["exchange_config_factory"] = lambda: SimpleNamespace(
            api_key=None, api_secret=None,
        )
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "demo_credentials_missing"
        factories["bybit_client_factory"].assert_not_called()

    def test_credentials_empty(self, script_module):
        class _Empty:
            def get_secret_value(self):
                return "   "

        factories = self._common_factories()
        factories["exchange_config_factory"] = lambda: SimpleNamespace(
            api_key=_Empty(), api_secret=_Empty(),
        )
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "demo_credentials_empty"
        factories["bybit_client_factory"].assert_not_called()

    def test_prompt_declined_returns_none(self, script_module):
        factories = self._common_factories()
        factories["prompt_fn"] = lambda timeout_seconds: False
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "prompt_declined_or_timeout"
        factories["bybit_client_factory"].assert_not_called()

    def test_prompt_exception_returns_none(self, script_module):
        factories = self._common_factories()
        def _raise(timeout_seconds):
            raise RuntimeError("test")
        factories["prompt_fn"] = _raise
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "prompt_failure"

    def test_bybit_client_init_failure(self, script_module):
        factories = self._common_factories()
        def _raise(**kw):
            raise RuntimeError("net_down")
        factories["bybit_client_factory"] = MagicMock(side_effect=_raise)
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason.startswith("bybit_client_init_failed:")

    def test_bybit_client_wrong_environment(self, script_module):
        factories = self._common_factories()
        fake_client = MagicMock()
        fake_client.environment = "testnet"  # WRONG
        fake_client.has_credentials = True
        factories["bybit_client_factory"] = MagicMock(return_value=fake_client)
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "bybit_client_environment_not_demo"
        # bybit_demo_executor_factory NEVER called.
        factories["bybit_demo_executor_factory"].assert_not_called()

    def test_bybit_client_no_credentials_post_init(self, script_module):
        factories = self._common_factories()
        fake_client = MagicMock()
        fake_client.environment = "demo"
        fake_client.has_credentials = False
        factories["bybit_client_factory"] = MagicMock(return_value=fake_client)
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is None
        assert reason == "bybit_client_missing_credentials"
        factories["bybit_demo_executor_factory"].assert_not_called()


# ===========================================================================
# _build_real_demo_executor - happy path
# ===========================================================================

class TestBuildRealDemoExecutorHappy:

    def _common_factories(self):
        from crypto_trading_bot.config.settings import TradingMode

        class _Secret:
            def __init__(self, val):
                self._v = val

            def get_secret_value(self):
                return self._v

        fake_client = MagicMock()
        fake_client.environment = "demo"
        fake_client.has_credentials = True

        fake_mode_guard = MagicMock()
        fake_risk_engine = MagicMock()
        fake_executor = MagicMock()
        fake_executor.safe_check_only = MagicMock()

        return dict(
            settings_factory=lambda: SimpleNamespace(
                trading_mode=TradingMode.DEMO,
                enable_demo_execution=True,
            ),
            exchange_config_factory=lambda: SimpleNamespace(
                api_key=_Secret("k_NEVER_LEAKED"),
                api_secret=_Secret("s_NEVER_LEAKED"),
            ),
            bybit_client_factory=MagicMock(return_value=fake_client),
            mode_guard_factory=MagicMock(return_value=fake_mode_guard),
            risk_engine_factory=MagicMock(return_value=fake_risk_engine),
            bybit_demo_executor_factory=MagicMock(return_value=fake_executor),
            prompt_fn=lambda timeout_seconds: True,
        )

    def test_happy_path_returns_executor_ok(self, script_module):
        factories = self._common_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        assert executor is not None
        assert reason == "ok"

    def test_bybit_client_instantiated_once_with_environment_demo(
        self, script_module,
    ):
        factories = self._common_factories()
        script_module._build_real_demo_executor(_args_ns(), **factories)
        client_fac = factories["bybit_client_factory"]
        client_fac.assert_called_once()
        _, kwargs = client_fac.call_args
        assert kwargs.get("environment") == "demo"

    def test_bybit_demo_executor_instantiated_once_with_confirm_true(
        self, script_module,
    ):
        factories = self._common_factories()
        script_module._build_real_demo_executor(_args_ns(), **factories)
        exec_fac = factories["bybit_demo_executor_factory"]
        exec_fac.assert_called_once()
        _, kwargs = exec_fac.call_args
        assert kwargs.get("confirm_demo_execution") is True

    def test_risk_engine_instantiated_with_capital(self, script_module):
        factories = self._common_factories()
        script_module._build_real_demo_executor(
            _args_ns(capital=10000.0), **factories,
        )
        risk_fac = factories["risk_engine_factory"]
        risk_fac.assert_called_once()
        _, kwargs = risk_fac.call_args
        assert kwargs.get("initial_capital") == 10000.0

    def test_mode_guard_built_from_demo_settings(self, script_module):
        factories = self._common_factories()
        script_module._build_real_demo_executor(_args_ns(), **factories)
        factories["mode_guard_factory"].assert_called_once()

    def test_executor_supports_safe_check_only_for_post_check(
        self, script_module,
    ):
        factories = self._common_factories()
        executor, _ = script_module._build_real_demo_executor(
            _args_ns(), **factories,
        )
        # The script wires post_session_check_fn to
        # executor.safe_check_only(dry_run=False) when real_attempted.
        assert hasattr(executor, "safe_check_only")


# ===========================================================================
# _DryExecutor invariants
# ===========================================================================

class TestDryExecutor:

    def test_execute_returns_object_with_to_dict(self, script_module):
        executor = script_module._DryExecutor()
        result = executor.execute(risk_result=None, dry_run=True)
        assert hasattr(result, "to_dict")
        d = result.to_dict()
        assert d["dry_run"] is True
        assert d["reconciliation_confidence"] == "canonical"

    def test_dry_executor_does_not_instantiate_bybit_client(self):
        # _DryExecutor body must not call BybitClient(...) or import httpx/requests.
        src = _SCRIPT_PATH.read_text(encoding="utf-8")
        start = src.find("class _DryExecutor")
        assert start >= 0
        next_top = src.find("\n# --", start + 1)
        body = src[start:next_top] if next_top > 0 else src[start:]
        # The docstring may mention "BybitClient" as a note; reject only
        # actual instantiation and network imports.
        assert "BybitClient(" not in body
        assert "import httpx" not in body
        assert "import requests" not in body
        assert "from httpx" not in body
        assert "from requests" not in body
