"""
Testes — build_demo_session_plan (FASE 20)
==============================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Garante:
    - Aceita readiness limpo + invariantes consistentes.
    - Rejeita is_ready_for_gated_demo=False.
    - Rejeita total_blocks > 0.
    - Rejeita provider divergente.
    - Rejeita symbol divergente.
    - Rejeita capital divergente.
    - Rejeita readiness stale (idade > limite).
    - Rejeita readiness no futuro.
    - Exige snapshot quando profile possui risk_config_overrides.
    - Rejeita snapshot preview-only (was_applied=False) com overrides.
    - Rejeita snapshot com issues error.
    - Aceita ausência de snapshot quando overrides vazios.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.demo_session_execution import (
    BlueprintSide,
    DemoSessionPlanRejected,
    SignalBlueprint,
    build_demo_session_plan,
)
from crypto_trading_bot.demo_session_readiness import (
    DemoSessionReadinessCheck,
    DemoSessionReadinessReport,
    ReadinessGate,
    ReadinessIssue,
)
from crypto_trading_bot.execution.provider_capability import (
    ProviderCapability,
    ProviderStatus,
)
from crypto_trading_bot.execution.provider_registry import (
    ProviderEntry,
    ProviderRegistry,
)
from crypto_trading_bot.operational_profile import (
    AppliedRiskConfigSnapshot,
    ProfileRiskOverrideIssue,
    build_personal_profile,
)
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_buy_blueprint(symbol="BTCUSDT") -> SignalBlueprint:
    return SignalBlueprint(
        symbol=symbol,
        side=BlueprintSide.BUY,
        entry_price=65000.0,
        stop_loss=64000.0,
        take_profit=67000.0,
        position_size_usd=200.0,
    )


def _make_local_registry() -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(ProviderEntry(
        provider_id="bybit_demo_linear",
        capability=ProviderCapability(
            provider_id="bybit_demo_linear",
            supports_market_order=True,
            is_demo_environment=True,
        ),
        status=ProviderStatus.OPT_IN,
        reason="test",
    ))
    return reg


def _make_report(
    symbol="BTCUSDT", capital=5000.0, profile=None,
) -> DemoSessionReadinessReport:
    profile = profile or build_personal_profile(account_size_usd=capital)
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=symbol,
        capital=capital,
        safety_machine=SafetyStateMachine(),
        provider_registry=_make_local_registry(),
    )
    return check.evaluate()


def _make_snapshot(was_applied=True, with_error=False) -> AppliedRiskConfigSnapshot:
    issues = ()
    if with_error:
        issues = (
            ProfileRiskOverrideIssue(
                severity="error",
                key="max_daily_loss_pct",
                message="out of range",
            ),
        )
    return AppliedRiskConfigSnapshot(
        profile_name="personal_v1",
        applied_at=datetime.now(timezone.utc),
        operator_token_sanitized="<test>",
        final_config=MappingProxyType({"x": 1}),
        diff_summary=(),
        issues_at_apply=issues,
        was_applied=was_applied,
    )


# ===========================================================================
# Happy path
# ===========================================================================

class TestBuildHappyPath:

    def test_clean_inputs_accepted(self):
        report = _make_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = build_demo_session_plan(
            plan_id="plan-001",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
        )
        assert plan.plan_id == "plan-001"
        assert plan.is_planned_for_execution is False
        assert plan.max_orders == 1

    def test_no_overrides_no_snapshot_ok(self):
        report = _make_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = build_demo_session_plan(
            plan_id="plan-002",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=None,
        )
        assert plan.risk_snapshot is None


# ===========================================================================
# Invariantes do report
# ===========================================================================

class TestBuildRejectionsFromReport:

    def test_rejects_not_ready(self):
        # Constrói report False forçando blocking issue.
        err = ReadinessIssue(
            gate=ReadinessGate.SAFETY_STATE,
            severity="error",
            message="forced",
        )
        bad = DemoSessionReadinessReport(
            profile_name="personal_v1",
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="bybit_demo_linear",
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=False,
            gates_evaluated=tuple(ReadinessGate),
            issues=(err,),
            blocking_reasons=("forced",),
        )
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=bad,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
            )

    def test_rejects_wrong_provider(self):
        # Não há jeito direto de fazer report com provider errado via
        # check normal; construímos manualmente.
        bad = DemoSessionReadinessReport(
            profile_name="personal_v1",
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="paper",  # divergente
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=bad,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
            )

    def test_rejects_symbol_mismatch(self):
        report = _make_report(symbol="BTCUSDT")
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(symbol="ETHUSDT"),
                effective_risk_config=RiskConfig(),
            )

    def test_rejects_capital_mismatch(self):
        report = _make_report(capital=5000.0)
        profile = build_personal_profile(account_size_usd=10000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
            )

    def test_rejects_stale_report(self):
        report = _make_report()
        # Force "now" 600s no futuro vs evaluated_at
        future = report.evaluated_at + timedelta(seconds=600)
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                readiness_max_age_seconds=300,
                now=future,
            )

    def test_rejects_future_report(self):
        report = _make_report()
        # "now" antes do report → idade negativa
        past = report.evaluated_at - timedelta(seconds=60)
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                now=past,
            )

    def test_custom_max_age_accepted(self):
        # Aceita relatório de até 60s atrás dentro de janela 120s.
        report = _make_report()
        now = report.evaluated_at + timedelta(seconds=60)
        profile = build_personal_profile(account_size_usd=5000.0)
        plan = build_demo_session_plan(
            plan_id="plan-x",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            readiness_max_age_seconds=120,
            now=now,
        )
        assert plan.plan_id == "plan-x"


# ===========================================================================
# Snapshot quando há overrides
# ===========================================================================

class TestBuildSnapshotInvariants:

    def test_overrides_without_snapshot_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        # readiness para esse profile vai bloquear no gate de snapshot
        # da FASE 19, então construímos um report manual ready=True para
        # forçar o caminho de validação aqui.
        report = DemoSessionReadinessReport(
            profile_name=profile.name,
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="bybit_demo_linear",
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=None,
            )

    def test_overrides_with_preview_snapshot_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        report = DemoSessionReadinessReport(
            profile_name=profile.name,
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="bybit_demo_linear",
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=_make_snapshot(was_applied=False),
            )

    def test_snapshot_with_errors_rejects(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        report = DemoSessionReadinessReport(
            profile_name=profile.name,
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="bybit_demo_linear",
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="plan-x",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
                risk_snapshot=_make_snapshot(
                    was_applied=True, with_error=True,
                ),
            )

    def test_overrides_with_applied_safe_snapshot_ok(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        report = DemoSessionReadinessReport(
            profile_name=profile.name,
            symbol="BTCUSDT",
            capital=5000.0,
            provider_id="bybit_demo_linear",
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=True,
            gates_evaluated=tuple(ReadinessGate),
            issues=(),
            blocking_reasons=(),
        )
        plan = build_demo_session_plan(
            plan_id="plan-x",
            readiness_report=report,
            profile=profile,
            blueprint=_make_buy_blueprint(),
            effective_risk_config=RiskConfig(),
            risk_snapshot=_make_snapshot(was_applied=True),
        )
        assert plan.risk_snapshot is not None
        assert plan.risk_snapshot.was_applied is True


# ===========================================================================
# plan_id sanitização
# ===========================================================================

class TestBuildPlanIdSanitization:

    def test_empty_plan_id_rejects(self):
        report = _make_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
            )

    def test_suspicious_plan_id_rejects(self):
        report = _make_report()
        profile = build_personal_profile(account_size_usd=5000.0)
        with pytest.raises(DemoSessionPlanRejected):
            build_demo_session_plan(
                plan_id="api_key=sk-fake",
                readiness_report=report,
                profile=profile,
                blueprint=_make_buy_blueprint(),
                effective_risk_config=RiskConfig(),
            )
