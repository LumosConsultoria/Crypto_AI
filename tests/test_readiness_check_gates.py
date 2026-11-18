"""
Testes — Gates individuais do DemoSessionReadinessCheck (FASE 19)
===================================================================
⚠️  100% offline. ZERO rede. ZERO API key. ZERO secrets.

Cobre cada um dos 6 gates isoladamente:
    SAFETY_STATE / PROFILE_CHECK / PROVIDER_STATUS /
    RISK_CONFIG_SNAPSHOT / LAST_FLAGS_CLEAN / PREFLIGHT_LOCAL
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.demo_session_readiness import (
    DemoSessionReadinessCheck,
    ReadinessGate,
    SafetyFlags,
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
from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.operational_safety.safety_state import SafetyState
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_clean_check(
    *,
    profile=None,
    safety_machine=None,
    risk_snapshot=None,
    last_safety_flags=None,
    symbol="BTCUSDT",
    capital=5000.0,
    has_open_position=False,
    has_open_orders=False,
    provider_registry=None,
) -> DemoSessionReadinessCheck:
    """Constrói um check "tudo limpo" por default, com overrides pontuais."""
    return DemoSessionReadinessCheck(
        profile=profile or build_personal_profile(account_size_usd=5000.0),
        symbol=symbol,
        capital=capital,
        safety_machine=safety_machine or SafetyStateMachine(),
        risk_snapshot=risk_snapshot,
        last_safety_flags=last_safety_flags,
        has_open_position=has_open_position,
        has_open_orders=has_open_orders,
        provider_registry=provider_registry,
    )


def _make_local_registry_with_demo(
    status: ProviderStatus = ProviderStatus.OPT_IN,
) -> ProviderRegistry:
    """Registry local isolado com bybit_demo_linear em status declarado."""
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


def _make_snapshot(
    *,
    was_applied: bool,
    issues=(),
    profile_name="personal_v1",
) -> AppliedRiskConfigSnapshot:
    return AppliedRiskConfigSnapshot(
        profile_name=profile_name,
        applied_at=datetime.now(timezone.utc),
        operator_token_sanitized="<test>",
        final_config=MappingProxyType({"x": 1}),
        diff_summary=(),
        issues_at_apply=tuple(issues),
        was_applied=was_applied,
    )


# ===========================================================================
# 1. SAFETY_STATE
# ===========================================================================

class TestSafetyStateGate:

    def test_normal_passes(self):
        report = _make_clean_check().evaluate()
        assert not report.issues_by_gate(ReadinessGate.SAFETY_STATE)

    def test_manual_review_blocks(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="test")
        report = _make_clean_check(safety_machine=m).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.SAFETY_STATE)
        assert len(gate_issues) >= 1
        assert any(i.severity == "error" for i in gate_issues)
        assert not report.is_ready_for_gated_demo

    def test_halt_recommended_blocks(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="test")
        report = _make_clean_check(safety_machine=m).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.SAFETY_STATE)
        assert any(i.severity == "error" for i in gate_issues)

    def test_safety_halt_active_blocks(self):
        m = SafetyStateMachine()
        m.recommend_safety_halt(reason="test")
        m.activate_safety_halt(reason="test")
        report = _make_clean_check(safety_machine=m).evaluate()
        assert not report.is_ready_for_gated_demo


# ===========================================================================
# 2. PROFILE_CHECK
# ===========================================================================

class TestProfileCheckGate:

    def test_personal_profile_passes(self):
        report = _make_clean_check().evaluate()
        assert not report.issues_by_gate(ReadinessGate.PROFILE_CHECK)

    def test_invalid_profile_blocks(self):
        # max_concurrent_positions=0 é aceito pelo dataclass mas detectado
        # como issue por validate_profile_self → readiness deve bloquear.
        bad = OperationalProfile(
            name="bad",
            description="bad",
            provider_type="custom",
            max_concurrent_positions=0,
        )
        report = _make_clean_check(profile=bad).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PROFILE_CHECK)
        assert any(i.severity == "error" for i in gate_issues)
        assert not report.is_ready_for_gated_demo


# ===========================================================================
# 3. PROVIDER_STATUS
# ===========================================================================

class TestProviderStatusGate:

    def test_opt_in_passes(self):
        reg = _make_local_registry_with_demo(ProviderStatus.OPT_IN)
        report = _make_clean_check(provider_registry=reg).evaluate()
        assert not report.issues_by_gate(ReadinessGate.PROVIDER_STATUS)

    def test_active_blocks(self):
        # FASE 19 exige EXATAMENTE OPT_IN — ACTIVE deve bloquear.
        reg = _make_local_registry_with_demo(ProviderStatus.ACTIVE)
        report = _make_clean_check(provider_registry=reg).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PROVIDER_STATUS)
        assert any(i.severity == "error" for i in gate_issues)

    def test_candidate_revalidation_blocks(self):
        reg = _make_local_registry_with_demo(
            ProviderStatus.CANDIDATE_REVALIDATION
        )
        report = _make_clean_check(provider_registry=reg).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PROVIDER_STATUS)
        assert any(i.severity == "error" for i in gate_issues)

    def test_restricted_blocks(self):
        reg = _make_local_registry_with_demo(ProviderStatus.RESTRICTED)
        report = _make_clean_check(provider_registry=reg).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PROVIDER_STATUS)
        assert any(i.severity == "error" for i in gate_issues)

    def test_unregistered_blocks(self):
        reg = ProviderRegistry()  # vazio
        report = _make_clean_check(provider_registry=reg).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PROVIDER_STATUS)
        assert any(i.severity == "error" for i in gate_issues)
        assert not report.is_ready_for_gated_demo

    def test_registry_not_mutated(self):
        reg = _make_local_registry_with_demo(ProviderStatus.OPT_IN)
        snap_before = reg.audit_snapshot()
        entry_before = reg.get("bybit_demo_linear")
        _make_clean_check(provider_registry=reg).evaluate()
        snap_after = reg.audit_snapshot()
        entry_after = reg.get("bybit_demo_linear")
        assert snap_before == snap_after
        assert entry_before is entry_after
        assert entry_after.status is ProviderStatus.OPT_IN


# ===========================================================================
# 4. RISK_CONFIG_SNAPSHOT
# ===========================================================================

class TestRiskSnapshotGate:

    def test_no_overrides_no_snapshot_info_only(self):
        report = _make_clean_check().evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        # Sem overrides + sem snapshot ⇒ apenas info, não bloqueia
        assert all(i.severity != "error" for i in gate_issues)

    def test_overrides_no_snapshot_blocks(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        report = _make_clean_check(profile=profile).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        assert any(i.severity == "error" for i in gate_issues)
        assert not report.is_ready_for_gated_demo

    def test_overrides_with_preview_snapshot_blocks(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        snap = _make_snapshot(was_applied=False)
        report = _make_clean_check(
            profile=profile, risk_snapshot=snap,
        ).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        assert any(i.severity == "error" for i in gate_issues)

    def test_overrides_with_applied_safe_snapshot_passes(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        snap = _make_snapshot(was_applied=True, issues=())
        report = _make_clean_check(
            profile=profile, risk_snapshot=snap,
        ).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        assert not any(i.severity == "error" for i in gate_issues)

    def test_snapshot_with_error_blocks(self):
        snap = _make_snapshot(
            was_applied=True,
            issues=(
                ProfileRiskOverrideIssue(
                    severity="error",
                    key="max_daily_loss_pct",
                    message="value out of range",
                ),
            ),
        )
        report = _make_clean_check(risk_snapshot=snap).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        assert any(i.severity == "error" for i in gate_issues)
        assert not report.is_ready_for_gated_demo

    def test_no_overrides_preview_snapshot_info(self):
        # Sem overrides, snapshot preview gera info (não bloqueia)
        snap = _make_snapshot(was_applied=False)
        report = _make_clean_check(risk_snapshot=snap).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        assert all(i.severity != "error" for i in gate_issues)


# ===========================================================================
# 5. LAST_FLAGS_CLEAN
# ===========================================================================

class TestLastFlagsGate:

    def test_no_flags_passes(self):
        report = _make_clean_check(last_safety_flags=None).evaluate()
        assert not report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)

    def test_clean_flags_passes(self):
        flags = SafetyFlags()  # tudo default — limpo
        report = _make_clean_check(last_safety_flags=flags).evaluate()
        assert not report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)

    def test_manual_review_blocks(self):
        flags = SafetyFlags(manual_review_required=True, reason="x")
        report = _make_clean_check(last_safety_flags=flags).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        assert any(i.severity == "error" for i in gate_issues)

    def test_safety_halt_blocks(self):
        flags = SafetyFlags(safety_halt_recommended=True, reason="x")
        report = _make_clean_check(last_safety_flags=flags).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        assert any(i.severity == "error" for i in gate_issues)

    def test_triangulated_with_required_ack_blocks(self):
        # profile default: require_manual_ack_on_triangulation=True
        flags = SafetyFlags(reconciliation_confidence="triangulated")
        report = _make_clean_check(last_safety_flags=flags).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        assert any(i.severity == "error" for i in gate_issues)

    def test_triangulated_without_required_ack_warning_only(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            require_manual_ack_on_triangulation=False,
        )
        flags = SafetyFlags(reconciliation_confidence="triangulated")
        report = _make_clean_check(
            profile=profile, last_safety_flags=flags,
        ).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        # Pelo menos 1 warning, e nenhum error neste gate.
        assert any(i.severity == "warning" for i in gate_issues)
        assert not any(i.severity == "error" for i in gate_issues)

    def test_triangulated_is_not_canonical_fill(self):
        # Mesmo com require_manual_ack=False, triangulated NÃO pode ser
        # tratado como canonical. O check explicita "NÃO é fill canônico"
        # ou similar no detail/message.
        profile = build_personal_profile(
            account_size_usd=5000.0,
            require_manual_ack_on_triangulation=False,
        )
        flags = SafetyFlags(reconciliation_confidence="triangulated")
        report = _make_clean_check(
            profile=profile, last_safety_flags=flags,
        ).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        # Algum aviso deve existir indicando triangulação.
        assert len(gate_issues) >= 1
        joined = " ".join(
            (i.message + " " + (i.detail or "")) for i in gate_issues
        ).lower()
        assert "triangulated" in joined or "triangula" in joined

    def test_reconciliation_none_blocks(self):
        flags = SafetyFlags(reconciliation_confidence="none", reason="failed")
        report = _make_clean_check(last_safety_flags=flags).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.LAST_FLAGS_CLEAN)
        assert any(i.severity == "error" for i in gate_issues)


# ===========================================================================
# 6. PREFLIGHT_LOCAL
# ===========================================================================

class TestPreflightGate:

    def test_clean_passes(self):
        report = _make_clean_check().evaluate()
        assert not report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)

    def test_zero_capital_blocks(self):
        report = _make_clean_check(capital=0.0).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)

    def test_negative_capital_blocks(self):
        report = _make_clean_check(capital=-100.0).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)

    def test_empty_symbol_blocks(self):
        report = _make_clean_check(symbol="").evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)

    def test_open_position_blocks(self):
        report = _make_clean_check(has_open_position=True).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)

    def test_open_orders_blocks(self):
        report = _make_clean_check(has_open_orders=True).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)

    def test_symbol_outside_profile_blocks(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            allowed_symbols=("ETHUSDT",),
        )
        report = _make_clean_check(
            profile=profile, symbol="BTCUSDT",
        ).evaluate()
        gate_issues = report.issues_by_gate(ReadinessGate.PREFLIGHT_LOCAL)
        assert any(i.severity == "error" for i in gate_issues)
