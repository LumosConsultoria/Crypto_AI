"""
Testes — SignalBlueprint + DemoSessionPlan tipos (FASE 20)
==============================================================
⚠️  100% offline. ZERO rede. ZERO API. ZERO secrets. ZERO ordem.

Garante:
    - SignalBlueprint frozen, SL e TP obrigatórios > 0.
    - BUY: stop_loss < entry < take_profit.
    - SELL: take_profit < entry < stop_loss.
    - position_size_usd > 0; entry_price > 0; leverage > 0.
    - SignalBlueprint.to_dict() JSON-serializável.
    - DemoSessionPlan frozen.
    - DemoSessionPlan rejeita max_orders != 1.
    - DemoSessionPlan.is_planned_for_execution=False por default.
    - DemoSessionPlan.to_dict() JSON-serializável.
    - RecommendedNextAction tem 4 valores estáveis.
    - DemoSessionPlanRejected e DemoSessionRejected são RuntimeError.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.demo_session_execution import (
    BlueprintSide,
    DemoSessionOutcome,
    DemoSessionPlan,
    DemoSessionPlanRejected,
    DemoSessionRejected,
    RecommendedNextAction,
    SignalBlueprint,
)
from crypto_trading_bot.demo_session_readiness import (
    DemoSessionReadinessCheck,
)
from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)
from crypto_trading_bot.execution.provider_registry import (
    ProviderEntry,
    ProviderRegistry,
)
from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_buy_blueprint(**overrides) -> SignalBlueprint:
    defaults = dict(
        symbol="BTCUSDT",
        side=BlueprintSide.BUY,
        entry_price=65000.0,
        stop_loss=64000.0,
        take_profit=67000.0,
        position_size_usd=200.0,
    )
    defaults.update(overrides)
    return SignalBlueprint(**defaults)


def _make_local_registry_with_demo(
    status: ProviderStatus = ProviderStatus.OPT_IN,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    cap = ProviderCapability(
        provider_id="bybit_demo_linear",
        supports_market_order=True,
        is_demo_environment=True,
    )
    reg.register(ProviderEntry(
        provider_id="bybit_demo_linear",
        capability=cap,
        status=status,
        reason="test fixture",
    ))
    return reg


def _make_clean_readiness_report(
    symbol="BTCUSDT", capital=5000.0,
):
    """Produz um readiness report válido usando a FASE 19 real."""
    profile = build_personal_profile(account_size_usd=capital)
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=symbol,
        capital=capital,
        safety_machine=SafetyStateMachine(),
        provider_registry=_make_local_registry_with_demo(),
    )
    return check.evaluate()


# ===========================================================================
# SignalBlueprint
# ===========================================================================

class TestSignalBlueprintFrozen:

    def test_is_frozen(self):
        bp = _make_buy_blueprint()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bp.symbol = "ETHUSDT"  # type: ignore[misc]

    def test_metadata_is_mapping_proxy(self):
        bp = _make_buy_blueprint(metadata={"k": "v"})
        assert isinstance(bp.metadata, MappingProxyType)

    def test_metadata_protected_from_external_mutation(self):
        ext = {"k": "v"}
        bp = _make_buy_blueprint(metadata=ext)
        ext["k"] = "tampered"
        ext["new"] = "x"
        assert bp.metadata["k"] == "v"
        assert "new" not in bp.metadata

    def test_to_dict_json_serializable(self):
        bp = _make_buy_blueprint()
        encoded = json.dumps(bp.to_dict())
        decoded = json.loads(encoded)
        assert decoded["side"] == "buy"
        assert decoded["entry_price"] == 65000.0


class TestSignalBlueprintValidation:

    def test_sl_obrigatorio(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(stop_loss=0.0)

    def test_tp_obrigatorio(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(take_profit=0.0)

    def test_negative_sl_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(stop_loss=-100.0)

    def test_negative_tp_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(take_profit=-100.0)

    def test_zero_position_size_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(position_size_usd=0.0)

    def test_negative_position_size_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(position_size_usd=-100.0)

    def test_zero_entry_price_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(entry_price=0.0)

    def test_empty_symbol_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(symbol="")

    def test_side_must_be_enum(self):
        with pytest.raises(TypeError):
            _make_buy_blueprint(side="buy")  # type: ignore[arg-type]

    def test_leverage_zero_rejects(self):
        with pytest.raises(ValueError):
            _make_buy_blueprint(leverage=0.0)


class TestBuyOrdering:

    def test_buy_correct_ordering_accepted(self):
        bp = SignalBlueprint(
            symbol="BTCUSDT",
            side=BlueprintSide.BUY,
            entry_price=65000.0,
            stop_loss=64000.0,
            take_profit=67000.0,
            position_size_usd=200.0,
        )
        assert bp.side is BlueprintSide.BUY

    def test_buy_sl_above_entry_rejects(self):
        with pytest.raises(ValueError):
            SignalBlueprint(
                symbol="BTCUSDT",
                side=BlueprintSide.BUY,
                entry_price=65000.0,
                stop_loss=66000.0,  # acima do entry — inválido para BUY
                take_profit=67000.0,
                position_size_usd=200.0,
            )

    def test_buy_tp_below_entry_rejects(self):
        with pytest.raises(ValueError):
            SignalBlueprint(
                symbol="BTCUSDT",
                side=BlueprintSide.BUY,
                entry_price=65000.0,
                stop_loss=64000.0,
                take_profit=64500.0,  # abaixo do entry — inválido
                position_size_usd=200.0,
            )

    def test_buy_sl_equals_entry_rejects(self):
        with pytest.raises(ValueError):
            SignalBlueprint(
                symbol="BTCUSDT",
                side=BlueprintSide.BUY,
                entry_price=65000.0,
                stop_loss=65000.0,
                take_profit=66000.0,
                position_size_usd=200.0,
            )


class TestSellOrdering:

    def test_sell_correct_ordering_accepted(self):
        bp = SignalBlueprint(
            symbol="BTCUSDT",
            side=BlueprintSide.SELL,
            entry_price=65000.0,
            stop_loss=66000.0,
            take_profit=64000.0,
            position_size_usd=200.0,
        )
        assert bp.side is BlueprintSide.SELL

    def test_sell_sl_below_entry_rejects(self):
        with pytest.raises(ValueError):
            SignalBlueprint(
                symbol="BTCUSDT",
                side=BlueprintSide.SELL,
                entry_price=65000.0,
                stop_loss=64000.0,  # abaixo — inválido para SELL
                take_profit=63000.0,
                position_size_usd=200.0,
            )

    def test_sell_tp_above_entry_rejects(self):
        with pytest.raises(ValueError):
            SignalBlueprint(
                symbol="BTCUSDT",
                side=BlueprintSide.SELL,
                entry_price=65000.0,
                stop_loss=66000.0,
                take_profit=66500.0,  # acima — inválido para SELL
                position_size_usd=200.0,
            )


# ===========================================================================
# DemoSessionPlan
# ===========================================================================

class TestDemoSessionPlanFrozen:

    def test_plan_is_frozen(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = DemoSessionPlan(
            plan_id="plan-001",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=None,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.plan_id = "other"  # type: ignore[misc]

    def test_default_not_planned_for_execution(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = DemoSessionPlan(
            plan_id="plan-001",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=None,
        )
        assert plan.is_planned_for_execution is False

    def test_max_orders_one_accepted(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = DemoSessionPlan(
            plan_id="plan-001",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=None,
            max_orders=1,
        )
        assert plan.max_orders == 1

    def test_max_orders_other_rejects(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ValueError):
            DemoSessionPlan(
                plan_id="plan-001",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=None,
                max_orders=2,
            )

    def test_max_orders_zero_rejects(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ValueError):
            DemoSessionPlan(
                plan_id="plan-001",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=None,
                max_orders=0,
            )

    def test_empty_plan_id_rejects(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(ValueError):
            DemoSessionPlan(
                plan_id="",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=None,
            )

    def test_to_dict_json_serializable(self):
        report = _make_clean_readiness_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = DemoSessionPlan(
            plan_id="plan-001",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=None,
        )
        encoded = json.dumps(plan.to_dict())
        decoded = json.loads(encoded)
        assert decoded["plan_id"] == "plan-001"
        assert decoded["max_orders"] == 1
        assert decoded["is_planned_for_execution"] is False


# ===========================================================================
# RecommendedNextAction
# ===========================================================================

class TestRecommendedNextAction:

    def test_has_4_values(self):
        assert len(list(RecommendedNextAction)) == 4

    def test_stable_values(self):
        assert RecommendedNextAction.RETURN_TO_PAPER.value == "return_to_paper"
        assert (
            RecommendedNextAction.MANUAL_REVIEW_REQUIRED.value
            == "manual_review_required"
        )
        assert (
            RecommendedNextAction.SAFETY_HALT_ACK_NEEDED.value
            == "safety_halt_ack_needed"
        )
        assert (
            RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION.value
            == "ready_for_next_demo_session"
        )


# ===========================================================================
# Exceptions
# ===========================================================================

class TestExceptionTypes:

    def test_plan_rejected_is_runtime_error(self):
        assert issubclass(DemoSessionPlanRejected, RuntimeError)

    def test_session_rejected_is_runtime_error(self):
        assert issubclass(DemoSessionRejected, RuntimeError)
