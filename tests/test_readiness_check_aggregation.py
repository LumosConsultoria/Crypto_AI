"""
Testes — Agregação do DemoSessionReadinessReport (FASE 19)
=============================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobre:
    - Agregação consolidada de múltiplos gates.
    - is_ready_for_gated_demo True ↔ zero issues 'error'.
    - blocking_reasons agrega TODAS as mensagens de erro.
    - Warnings/info não bloqueiam.
    - Audit emitido (DEMO_SESSION_READINESS_CHECKED) sem secrets.
    - DemoSessionReadinessCheck NÃO importa BybitClient/executores/network.
    - DemoSessionReadinessCheck NÃO chama métodos de mutação do registry.
    - Read-only sobre ProviderRegistry default (singleton).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

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
    get_registry,
)
from crypto_trading_bot.operational_profile import (
    AppliedRiskConfigSnapshot,
    ProfileRiskOverrideIssue,
    build_personal_profile,
    build_hyrotrader_demo_template,
    build_prop_challenge_profile,
)
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)


_READINESS_SRC = (
    Path(__file__).parent.parent
    / "src" / "crypto_trading_bot" / "demo_session_readiness"
    / "readiness_check.py"
)


def _read_check_src() -> str:
    return _READINESS_SRC.read_text(encoding="utf-8")


def _executable_lines(src: str) -> str:
    out: list[str] = []
    in_block = False
    block_quote: str | None = None
    for line in src.splitlines():
        stripped = line.strip()
        if in_block:
            if block_quote and block_quote in line:
                in_block = False
                block_quote = None
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) == 1:
                    in_block = True
                    block_quote = q
                break
        else:
            if stripped.startswith("#"):
                continue
            out.append(line)
            continue
    return "\n".join(out)


def _make_local_registry_with_demo(status: ProviderStatus = ProviderStatus.OPT_IN):
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
        reason="test",
    ))
    return reg


def _clean_check(**overrides):
    defaults = dict(
        profile=build_personal_profile(account_size_usd=5000.0),
        symbol="BTCUSDT",
        capital=5000.0,
        safety_machine=SafetyStateMachine(),
        provider_registry=_make_local_registry_with_demo(),
    )
    defaults.update(overrides)
    return DemoSessionReadinessCheck(**defaults)


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------

class TestAggregation:

    def test_all_gates_clean_ready(self):
        report = _clean_check().evaluate()
        assert report.is_ready_for_gated_demo is True
        assert report.total_blocks == 0
        assert report.blocking_reasons == ()

    def test_six_gates_evaluated(self):
        report = _clean_check().evaluate()
        assert report.gates_evaluated == tuple(ReadinessGate)
        assert len(report.gates_evaluated) == 6

    def test_one_error_blocks(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="test")
        report = _clean_check(safety_machine=m).evaluate()
        assert report.is_ready_for_gated_demo is False
        assert report.total_blocks >= 1
        assert len(report.blocking_reasons) == report.total_blocks

    def test_multiple_errors_aggregate(self):
        m = SafetyStateMachine()
        m.mark_manual_review_required(reason="test")
        report = _clean_check(
            safety_machine=m,
            has_open_position=True,
            has_open_orders=True,
            capital=-1.0,
        ).evaluate()
        # safety + 3 preflight = pelo menos 4 errors
        assert report.total_blocks >= 4
        assert len(report.blocking_reasons) == report.total_blocks
        assert report.is_ready_for_gated_demo is False

    def test_warnings_do_not_block(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            require_manual_ack_on_triangulation=False,
        )
        flags = SafetyFlags(reconciliation_confidence="triangulated")
        report = _clean_check(
            profile=profile,
            last_safety_flags=flags,
        ).evaluate()
        assert report.total_warnings >= 1
        assert report.total_blocks == 0
        assert report.is_ready_for_gated_demo is True

    def test_info_does_not_block(self):
        # sem overrides + snapshot ausente → info (não bloqueia)
        report = _clean_check().evaluate()
        # pode haver info no risk_config_snapshot gate
        assert report.is_ready_for_gated_demo is True
        assert report.total_blocks == 0

    def test_triangulated_with_required_ack_blocks_aggregation(self):
        # default profile.require_manual_ack_on_triangulation=True
        flags = SafetyFlags(reconciliation_confidence="triangulated")
        report = _clean_check(last_safety_flags=flags).evaluate()
        assert report.is_ready_for_gated_demo is False
        assert any(
            "triangulated" in r.lower() or "triangula" in r.lower()
            for r in report.blocking_reasons
        )

    def test_report_has_evaluated_at_utc(self):
        report = _clean_check().evaluate()
        assert report.evaluated_at.tzinfo is timezone.utc

    def test_report_serializable(self):
        import json
        report = _clean_check().evaluate()
        encoded = json.dumps(report.to_dict())
        decoded = json.loads(encoded)
        assert decoded["is_ready_for_gated_demo"] is True
        assert decoded["provider_id"] == "bybit_demo_linear"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

class TestAuditLog:

    def test_audit_emits_readiness_checked(self):
        # Loguru não vai para caplog; usamos mock direto sobre _audit.
        from crypto_trading_bot.demo_session_readiness import readiness_check
        captured: list[str] = []
        with patch.object(
            readiness_check._audit,
            "info",
            side_effect=lambda msg, *a, **kw: captured.append(str(msg)),
        ):
            _clean_check().evaluate()
        joined = " ".join(captured)
        assert "DEMO_SESSION_READINESS_CHECKED" in joined
        assert "bybit_demo_linear" in joined
        assert "ready=" in joined

    def test_audit_does_not_leak_secrets(self):
        from crypto_trading_bot.demo_session_readiness import readiness_check
        captured: list[str] = []
        with patch.object(
            readiness_check._audit,
            "info",
            side_effect=lambda msg, *a, **kw: captured.append(str(msg)),
        ):
            check = _clean_check(notes="approved with api_key=sk-fake")
            report = check.evaluate()
        joined = " ".join(captured)
        assert "sk-fake" not in joined
        assert "sk-fake" not in report.notes

    def test_audit_does_not_leak_bearer(self):
        check = _clean_check(notes="Bearer abcdef123456")
        report = check.evaluate()
        assert "abcdef123456" not in report.notes


# ---------------------------------------------------------------------------
# Provider registry — read-only invariant
# ---------------------------------------------------------------------------

class TestRegistryReadOnly:

    def test_default_registry_not_mutated(self):
        reg = get_registry()
        snap_before = reg.audit_snapshot()
        entry_before = reg.get("bybit_demo_linear")
        check = DemoSessionReadinessCheck(
            profile=build_personal_profile(account_size_usd=5000.0),
            symbol="BTCUSDT",
            capital=5000.0,
            safety_machine=SafetyStateMachine(),
            # default registry (singleton com OPT_IN)
        )
        check.evaluate()
        snap_after = reg.audit_snapshot()
        entry_after = reg.get("bybit_demo_linear")
        assert snap_before == snap_after
        assert entry_after.status is ProviderStatus.OPT_IN
        assert entry_before is entry_after

    def test_register_never_called(self):
        reg = _make_local_registry_with_demo()
        with patch.object(reg, "register", side_effect=AssertionError(
            "register não deve ser chamado"
        )):
            with patch.object(reg, "unregister", side_effect=AssertionError(
                "unregister não deve ser chamado"
            )):
                check = DemoSessionReadinessCheck(
                    profile=build_personal_profile(account_size_usd=5000.0),
                    symbol="BTCUSDT",
                    capital=5000.0,
                    safety_machine=SafetyStateMachine(),
                    provider_registry=reg,
                )
                check.evaluate()


# ---------------------------------------------------------------------------
# Multiple profile builders
# ---------------------------------------------------------------------------

class TestAllBuilders:

    def test_personal_profile_ready(self):
        report = _clean_check(
            profile=build_personal_profile(account_size_usd=5000.0)
        ).evaluate()
        assert report.is_ready_for_gated_demo is True

    def test_prop_challenge_ready(self):
        report = _clean_check(
            profile=build_prop_challenge_profile(account_size_usd=5000.0)
        ).evaluate()
        # prop_challenge default tem kill_switch_enabled e conservative_mode,
        # mas isso não bloqueia readiness por si só.
        assert report.is_ready_for_gated_demo is True

    def test_hyrotrader_template_ready(self):
        report = _clean_check(
            profile=build_hyrotrader_demo_template(account_size_usd=5000.0)
        ).evaluate()
        assert report.is_ready_for_gated_demo is True

    def test_hyrotrader_with_overrides_requires_snapshot(self):
        profile = build_hyrotrader_demo_template(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        # sem snapshot → bloqueia
        report = _clean_check(profile=profile).evaluate()
        assert report.is_ready_for_gated_demo is False
        # Com snapshot aplicado → passa
        snap = AppliedRiskConfigSnapshot(
            profile_name=profile.name,
            applied_at=datetime.now(timezone.utc),
            operator_token_sanitized="<test>",
            final_config=MappingProxyType({}),
            diff_summary=(),
            issues_at_apply=(),
            was_applied=True,
        )
        report2 = _clean_check(profile=profile, risk_snapshot=snap).evaluate()
        assert report2.is_ready_for_gated_demo is True


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_repeated_calls_consistent(self):
        # Mesma config → mesmo veredito (is_ready). Issues podem diferir
        # apenas em evaluated_at.
        c1 = _clean_check()
        r1 = c1.evaluate()
        r2 = c1.evaluate()
        assert r1.is_ready_for_gated_demo == r2.is_ready_for_gated_demo
        assert r1.blocking_reasons == r2.blocking_reasons
        # gates_evaluated determinístico
        assert r1.gates_evaluated == r2.gates_evaluated


# ---------------------------------------------------------------------------
# Imports proibidos no readiness_check.py
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:

    def test_no_bybit_client_import(self):
        src = _executable_lines(_read_check_src())
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient" not in src

    def test_no_demo_executor_import(self):
        src = _executable_lines(_read_check_src())
        assert "bybit_demo_executor" not in src
        assert "BybitDemoExecutor" not in src

    def test_no_testnet_executor_import(self):
        src = _executable_lines(_read_check_src())
        assert "bybit_testnet_executor" not in src
        assert "BybitTestnetExecutor" not in src

    def test_no_demo_execution_result_import(self):
        src = _executable_lines(_read_check_src())
        assert "DemoExecutionResult" not in src

    def test_no_session_runner_import(self):
        src = _executable_lines(_read_check_src())
        assert "session_runner.runner" not in src
        assert "SessionRunner" not in src

    def test_no_bot_engine_import(self):
        src = _executable_lines(_read_check_src())
        assert "from crypto_trading_bot.core.bot_engine" not in src
        assert "BotEngine" not in src

    def test_no_risk_engine_import(self):
        src = _executable_lines(_read_check_src())
        assert "from crypto_trading_bot.risk.risk_engine" not in src

    def test_no_network_imports(self):
        src = _read_check_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_no_apply_overrides_call(self):
        # Garante que readiness NÃO CHAMA o gate de FASE 18.
        # (a string pode aparecer em mensagens informativas de issues,
        # mas nunca como invocação real.)
        src = _executable_lines(_read_check_src())
        assert "apply_profile_overrides_with_gate(" not in src
        assert "import apply_profile_overrides_with_gate" not in src
        # Tampouco importado em statements `from ... import ...`
        for line in src.splitlines():
            stripped = line.strip()
            if stripped.startswith("from ") and "import " in stripped:
                assert "apply_profile_overrides_with_gate" not in stripped

    def test_no_hyrotrader_branch(self):
        src = _executable_lines(_read_check_src())
        # Nenhuma comparação de provider_name == "HyroTrader" no código
        lower = src.lower()
        assert 'provider_name == "hyrotrader"' not in lower
        assert "provider_name=='hyrotrader'" not in lower

    def test_no_registry_mutation_calls(self):
        # Inspeção textual: nenhuma chamada a register/unregister/replace
        # no código executável (não conta argumentos passados a métodos
        # de outros objetos).
        src = _executable_lines(_read_check_src())
        # O método self._registry.<X> NÃO deve aparecer com mutadores
        # Atenção: 'register' aparece em nomes como 'provider_registry'
        # mas NÃO como method call .register(.
        assert "._registry.register(" not in src
        assert "._registry.unregister(" not in src
