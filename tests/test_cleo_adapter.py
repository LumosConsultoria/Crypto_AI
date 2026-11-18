"""
Testes do HyroTraderCleoAdapter — FASE 8 (UNCONFIRMED)
========================================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - dry_run obrigatório no construtor (sem default).
    - dry_run=False levanta NotImplementedError com "cleo-mechanism-undefined".
    - dry_run=True + execute() retorna CleoDryRunResult(success=False, ...)
      explicando que o mecanismo de integração CLEO não foi confirmado.
    - execute() rejeita risk_result.approved=False (INVARIANTE).
    - Capability tem TODOS os flags False, confirmed=False.
    - Satisfaz ExecutorProtocol estruturalmente.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.execution import ExecutorProtocol
from crypto_trading_bot.execution.providers import (
    CleoDryRunResult,
    HyroTraderCleoAdapter,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskResult,
    TradingSignal,
)


def _signal() -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=100.0,
        leverage=1.0,
        strategy_name="test",
    )


def _approved() -> RiskResult:
    return RiskResult(approved=True, reason="ok", signal=_signal())


def _blocked() -> RiskResult:
    return RiskResult(approved=False, reason="blocked", signal=_signal())


class TestConstructor:

    def test_dry_run_required_no_default(self):
        with pytest.raises(TypeError):
            HyroTraderCleoAdapter()  # type: ignore[call-arg]

    def test_dry_run_must_be_bool(self):
        with pytest.raises(ValueError):
            HyroTraderCleoAdapter(dry_run=None)  # type: ignore[arg-type]

    def test_dry_run_false_raises_with_safe_message(self):
        with pytest.raises(NotImplementedError, match="cleo-mechanism-undefined"):
            HyroTraderCleoAdapter(dry_run=False)


class TestCapabilityAllFalse:

    def test_all_capabilities_false(self):
        a = HyroTraderCleoAdapter(dry_run=True)
        cap = a.capability
        for attr in [
            "supports_market_order", "supports_limit_order",
            "supports_stop_loss", "supports_take_profit",
            "supports_reduce_only", "supports_leverage_api",
            "supports_positions_query", "supports_balance_query",
            "supports_cancel_order",
            "is_demo_environment", "is_live_environment",
            "confirmed",
        ]:
            assert getattr(cap, attr) is False, f"{attr} must be False (UNCONFIRMED)"


class TestExecuteAlwaysFailsExplicitly:

    def test_satisfies_executor_protocol(self):
        a = HyroTraderCleoAdapter(dry_run=True)
        assert isinstance(a, ExecutorProtocol)

    def test_execute_rejects_unapproved(self):
        a = HyroTraderCleoAdapter(dry_run=True)
        with pytest.raises(ValueError, match="REJEITA risk_result não aprovado"):
            a.execute(_blocked())

    def test_execute_returns_success_false_with_cleo_mechanism_undefined(self):
        a = HyroTraderCleoAdapter(dry_run=True)
        r = a.execute(_approved())
        assert isinstance(r, CleoDryRunResult)
        assert r.success is False
        assert "cleo-mechanism-undefined" in r.reason

    def test_summary_marks_mechanism_unconfirmed(self):
        a = HyroTraderCleoAdapter(dry_run=True)
        s = a.get_summary()
        assert s["mechanism_confirmed"] is False
        assert s["provider_id"] == "hyrotrader_cleo_demo"
