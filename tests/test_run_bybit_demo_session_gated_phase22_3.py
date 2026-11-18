"""
Tests - FASE 22.3: _build_real_demo_executor accepts explicit capital
==========================================================================
100% offline. ZERO network. ZERO API. ZERO secrets. ZERO order.

Reproduces the operational bug observed in Comando B with
--from-blueprint (without --capital): args.capital is None and
float(None) raised TypeError, surfacing as
"risk_engine_init_failed:TypeError".

Covers the FASE 22.3 hotfix:
    - _build_real_demo_executor accepts capital=<float> explicitly.
    - When --from-blueprint is used (args.capital=None), the explicit
      capital kwarg drives RiskEngine init successfully.
    - Missing capital (None+None) returns capital_missing_or_invalid
      reason WITHOUT calling RiskEngine.
    - Risk engine init failures now expose type+sanitized message.
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
    spec = importlib.util.spec_from_file_location(
        "run_bybit_demo_session_gated_p223", str(_SCRIPT_PATH),
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    src_path = str(_REPO_ROOT / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script_module():
    return _load_script_module()


def _args_ns(
    *,
    capital=None,  # FASE 22 made it optional; --from-blueprint omits it.
    qty_step: str = "0.001",
    prompt_timeout_seconds: float = 60.0,
):
    return SimpleNamespace(
        capital=capital,
        qty_step=qty_step,
        prompt_timeout_seconds=prompt_timeout_seconds,
    )


def _ok_factories():
    """Returns factories that all succeed (mocked)."""
    from crypto_trading_bot.config.settings import TradingMode

    class _Secret:
        def __init__(self, val):
            self._v = val
        def get_secret_value(self):
            return self._v

    good_settings = SimpleNamespace(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
    )
    good_exchange = SimpleNamespace(
        api_key=_Secret("k_NEVER_LEAKED"),
        api_secret=_Secret("s_NEVER_LEAKED"),
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


# ===========================================================================
# Reproduce the bug: args.capital=None without explicit kwarg
# ===========================================================================

class TestCapitalMissingReproducesBug(object):

    def test_capital_none_in_args_no_kwarg_returns_safe_error(
        self, script_module,
    ):
        """FASE 22.3: when args.capital=None and capital kwarg omitted,
        function returns capital_missing_or_invalid WITHOUT calling
        risk_engine_factory. Previously this raised TypeError inside
        float(None) and surfaced as risk_engine_init_failed:TypeError.
        """
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=None),
            **factories,
        )
        assert executor is None
        assert reason == "capital_missing_or_invalid"
        # RiskEngine factory NEVER called.
        factories["risk_engine_factory"].assert_not_called()

    def test_capital_zero_in_args_no_kwarg_returns_safe_error(
        self, script_module,
    ):
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=0.0),
            **factories,
        )
        assert executor is None
        assert reason == "capital_missing_or_invalid"

    def test_capital_negative_returns_safe_error(self, script_module):
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=-10.0),
            **factories,
        )
        assert executor is None
        assert reason == "capital_missing_or_invalid"


# ===========================================================================
# Explicit capital kwarg unblocks the path
# ===========================================================================

class TestExplicitCapitalUnblocks:

    def test_explicit_capital_with_args_none_succeeds(self, script_module):
        """Operator runs --from-blueprint without --capital; main() passes
        derived_capital from blueprint.proposal.capital explicitly. The
        function must accept that kwarg and pass to RiskEngine."""
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=None),
            capital=4999.86,
            **factories,
        )
        assert executor is not None
        assert reason == "ok"
        # RiskEngine factory called once with initial_capital from kwarg.
        factories["risk_engine_factory"].assert_called_once()
        _, kwargs = factories["risk_engine_factory"].call_args
        assert kwargs.get("initial_capital") == 4999.86

    def test_explicit_capital_overrides_args_capital(self, script_module):
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=5000.0),
            capital=4321.10,
            **factories,
        )
        assert executor is not None
        assert reason == "ok"
        _, kwargs = factories["risk_engine_factory"].call_args
        # Explicit kwarg wins over args.capital.
        assert kwargs.get("initial_capital") == 4321.10


# ===========================================================================
# Backward-compat: args.capital still works when kwarg omitted
# ===========================================================================

class TestArgsCapitalFallback:

    def test_args_capital_used_when_kwarg_omitted(self, script_module):
        factories = _ok_factories()
        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=5000.0),
            **factories,
        )
        assert executor is not None
        assert reason == "ok"
        _, kwargs = factories["risk_engine_factory"].call_args
        assert kwargs.get("initial_capital") == 5000.0


# ===========================================================================
# Risk engine init failure surfaces type + sanitized message
# ===========================================================================

class TestRiskEngineInitFailureMessage:

    def test_risk_engine_typeerror_message_sanitized(self, script_module):
        factories = _ok_factories()

        def _raise(*a, **kw):
            raise TypeError("synthetic msg with no secrets")
        factories["risk_engine_factory"] = MagicMock(side_effect=_raise)

        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=None),
            capital=5000.0,
            **factories,
        )
        assert executor is None
        # FASE 22.3: now includes type AND sanitized message portion.
        assert reason.startswith("risk_engine_init_failed:TypeError")
        assert "synthetic msg" in reason

    def test_risk_engine_long_message_truncated(self, script_module):
        factories = _ok_factories()

        def _raise(*a, **kw):
            raise ValueError("x" * 500)
        factories["risk_engine_factory"] = MagicMock(side_effect=_raise)

        executor, reason = script_module._build_real_demo_executor(
            _args_ns(capital=None),
            capital=5000.0,
            **factories,
        )
        assert executor is None
        # Reason format: "risk_engine_init_failed:ValueError:<msg truncated>".
        # We truncated msg at 200 chars; prefix is ~32 chars.
        # Should NOT contain 201+ x's.
        assert "x" * 250 not in reason


# ===========================================================================
# Sanitization: no secrets leak through error path
# ===========================================================================

class TestNoSecretsInErrorPath:

    def test_no_secret_substring_in_capital_error(self, script_module):
        factories = _ok_factories()
        _, reason = script_module._build_real_demo_executor(
            _args_ns(capital=None), **factories,
        )
        lower = reason.lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:"):
            assert tok not in lower
