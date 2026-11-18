"""
Tests - FASE 36 Bloco H: Options Registry global + discovery
=============================================================
100% offline. Prova: nenhuma capacidade nao-default fica invisivel;
perigosas sao disabled_by_default + gate; discovery audita o bot
inteiro e detecta gates fora do registry.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.operational_options import (
    ExecutionImpact,
    OperationalOption,
    OperationalOptionsRegistry,
    OptionRiskImpact,
    OptionStatus,
    build_default_registry,
    run_option_discovery_audit,
)


class TestRegistrySeed:

    def test_registry_has_global_coverage(self):
        reg = OperationalOptionsRegistry()
        ids = {o.option_id for o in reg.all_options}
        # Capacidades-chave do bot INTEIRO (nao so FASES 30-35).
        for required in (
            "paper_trading", "backtest_research", "wired_dry_run",
            "observation_mode", "testnet_execution", "live_mainnet",
            "demo_execution_enabled", "phase29_real_order",
            "reduce_only_close", "short_demo", "multi_order_session",
            "demo_real_multi_order", "multi_order_sequential",
            "scale_in", "partial_reduce", "controlled_reversal",
            "ai_assistance", "ai_veto", "ai_manual_review",
            "ai_real_provider", "prediction_context",
            "prediction_execution", "market_intelligence",
            "strategy_selection", "profile_selection",
            "parameter_advisor", "risk_overrides",
            "stale_data_policy", "api_failure_policy",
        ):
            assert required in ids, f"opcao ausente: {required}"

    def test_non_default_options_visible(self):
        reg = OperationalOptionsRegistry()
        non_default = reg.non_default_options()
        assert len(non_default) >= 20
        ids = {o.option_id for o in non_default}
        assert "scale_in" in ids
        assert "live_mainnet" in ids

    def test_dangerous_options_gated_or_blocked(self):
        for opt in build_default_registry():
            if opt.risk_impact in (
                OptionRiskImpact.HIGH, OptionRiskImpact.CRITICAL,
            ) and opt.execution_impact is \
                    ExecutionImpact.REAL_POSSIBLE:
                assert not opt.default_enabled, opt.option_id
                assert opt.requires_gate or \
                    opt.status is OptionStatus.BLOCKED, opt.option_id

    def test_live_mainnet_blocked(self):
        opt = OperationalOptionsRegistry().get("live_mainnet")
        assert opt.status is OptionStatus.BLOCKED
        assert opt.current_enabled() is False
        assert "ModeGuard" in opt.blocked_reason

    def test_prediction_execution_blocked(self):
        opt = OperationalOptionsRegistry().get("prediction_execution")
        assert opt.status is OptionStatus.BLOCKED

    def test_scale_in_missing_limits_with_v_references(self):
        opt = OperationalOptionsRegistry().get("scale_in")
        assert opt.status is OptionStatus.MISSING_LIMITS
        assert opt.requires_gate
        assert opt.required_gate_name == \
            "DEMO_ALLOW_SCALE_IN_ENABLED"
        assert opt.required_profile_field == "allow_scale_in"
        assert any("V5" in m for m in opt.missing_information)
        assert any("V6" in m for m in opt.missing_information)
        assert opt.requires_operator_confirmation

    def test_ai_real_provider_missing_config(self):
        opt = OperationalOptionsRegistry().get("ai_real_provider")
        assert opt.status is OptionStatus.MISSING_CONFIG
        assert any("Q1" in m for m in opt.missing_information)

    def test_current_enabled_follows_gate_env(self, monkeypatch):
        opt = OperationalOptionsRegistry().get("multi_order_session")
        monkeypatch.delenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", raising=False,
        )
        assert opt.current_enabled() is False
        monkeypatch.setenv(
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION", "true",
        )
        assert opt.current_enabled() is True

    def test_snapshot_ui_ready(self):
        snap = OperationalOptionsRegistry().to_snapshot()
        assert snap["schema"] == "operational_options_snapshot_v1"
        assert snap["total"] >= 30
        row = snap["options"][0]
        for key in (
            "option_id", "source_location", "label", "category",
            "default_enabled", "current_enabled",
            "selectable_by_user", "requires_gate",
            "required_gate_name", "risk_impact", "execution_impact",
            "supported_modes", "blocked_reason",
            "missing_information", "depends_on", "conflicts_with",
            "ui_group", "ui_order", "status",
        ):
            assert key in row, key


class TestOptionModelInvariants:

    def test_dangerous_default_enabled_rejected(self):
        with pytest.raises(ValueError, match="perigosa"):
            OperationalOption(
                option_id="bad", source_location="x", label="x",
                description="x", category="x",
                default_enabled=True,
                risk_impact=OptionRiskImpact.CRITICAL,
                execution_impact=ExecutionImpact.REAL_POSSIBLE,
            )

    def test_dangerous_without_gate_rejected(self):
        with pytest.raises(ValueError, match="gate"):
            OperationalOption(
                option_id="bad2", source_location="x", label="x",
                description="x", category="x",
                risk_impact=OptionRiskImpact.HIGH,
                execution_impact=ExecutionImpact.REAL_POSSIBLE,
                status=OptionStatus.DISABLED_BY_DEFAULT,
            )

    def test_gate_requires_name(self):
        with pytest.raises(ValueError, match="required_gate_name"):
            OperationalOption(
                option_id="bad3", source_location="x", label="x",
                description="x", category="x", requires_gate=True,
            )


class TestDiscoveryAudit:

    def test_no_gaps_against_current_code(self):
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        assert report.env_gates_missing_in_registry == ()
        assert report.profile_fields_missing_in_registry == ()
        assert not report.has_gaps

    def test_all_code_gates_discovered(self):
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        found = set(report.declared_env_gates_in_code)
        for gate in (
            "BYBIT_USE_DEMO",
            "DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED",
            "DEMO_ALLOW_MULTI_ORDER_PER_SESSION",
            "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED",
            "DEMO_ALLOW_AI_MANUAL_REVIEW",
            "ENABLE_PREDICTION_MARKET_CONTEXT",
        ):
            assert gate in found, gate

    def test_detects_unregistered_gate(self):
        # Registry SEM a opcao multi_order_session => gap detectado.
        partial = tuple(
            o for o in build_default_registry()
            if o.option_id not in (
                "multi_order_session", "demo_real_multi_order",
                "multi_order_sequential",
            )
        )
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(partial),
        )
        assert "DEMO_ALLOW_MULTI_ORDER_PER_SESSION" in \
            report.env_gates_missing_in_registry
        assert report.has_gaps

    def test_known_inconsistencies_documented(self):
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        text = " ".join(report.known_inconsistencies)
        assert "DEMO_ALLOW_SHORT_ENABLED" in text
        assert "apply-demo-real-final" in text

    def test_cli_flags_discovered(self):
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        flags = set(report.cli_flags_found)
        for flag in (
            "--execute-demo-real-multi",
            "--continue-after-would-order",
            "--real-time", "--synthetic-feed", "--inputs-store",
        ):
            assert flag in flags, flag

    def test_report_to_dict(self):
        d = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        ).to_dict()
        assert d["schema"] == "option_discovery_audit_v1"
        assert "known_inconsistencies" in d
