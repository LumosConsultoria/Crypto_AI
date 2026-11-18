"""
Testes — execute_demo_session_gated (FASE 20)
==================================================
⚠️  100% offline. ZERO rede. ZERO API real. ZERO secrets. ZERO ordem.

Cobre:
    - Rejeições de cada gate (10 gates).
    - dry_run=True default; executor recebido com flag.
    - Triangulated → manual_review + nunca canonical fill.
    - Reconciliation failed/none → safety halt.
    - Canonical clean fill → READY_FOR_NEXT_DEMO_SESSION.
    - post_session_check_fn injetado é chamado quando fornecido.
    - post_session_check_fn com residual → outcome reflete.
    - safety_machine.from_safety_flags é chamado após resultado.
    - Audit emitido sanitizado.
    - Executor é chamado no máximo 1 vez.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.demo_session_execution import (
    BlueprintSide,
    DemoSessionPlan,
    DemoSessionRejected,
    RecommendedNextAction,
    SignalBlueprint,
    build_demo_session_plan,
    execute_demo_session_gated,
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
from crypto_trading_bot.operational_safety.safety_state import SafetyState
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine


# ---------------------------------------------------------------------------
# Fixtures
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


def _make_local_registry(
    status: ProviderStatus = ProviderStatus.OPT_IN,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(ProviderEntry(
        provider_id="bybit_demo_linear",
        capability=ProviderCapability(
            provider_id="bybit_demo_linear",
            supports_market_order=True,
            is_demo_environment=True,
        ),
        status=status,
        reason="test",
    ))
    return reg


def _make_mode_guard_allowing_demo() -> ModeGuard:
    """ModeGuard com Settings sintético que permite demo execution."""
    settings = Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_live_trading=False,
        enable_testnet_execution=False,
    )
    return ModeGuard(settings)


def _make_mode_guard_blocking_demo() -> ModeGuard:
    settings = Settings(
        trading_mode=TradingMode.PAPER,
        enable_demo_execution=False,
        enable_live_trading=False,
        enable_testnet_execution=False,
    )
    return ModeGuard(settings)


def _make_clean_plan(
    *,
    profile=None,
    blueprint=None,
    capital=5000.0,
    symbol="BTCUSDT",
) -> DemoSessionPlan:
    profile = profile or build_personal_profile(account_size_usd=capital)
    blueprint = blueprint or _make_buy_blueprint(symbol=symbol)
    check = DemoSessionReadinessCheck(
        profile=profile,
        symbol=symbol,
        capital=capital,
        safety_machine=SafetyStateMachine(),
        provider_registry=_make_local_registry(),
    )
    report = check.evaluate()
    return build_demo_session_plan(
        plan_id="plan-001",
        readiness_report=report,
        profile=profile,
        blueprint=blueprint,
        effective_risk_config=RiskConfig(),
    )


class _FakeExecutor:
    """Implementa DemoExecutorProtocol — count chamadas."""

    def __init__(self, result):
        self._result = result
        self.calls: list[tuple] = []

    def execute(self, risk_result, dry_run=True):
        self.calls.append((risk_result, dry_run))
        return self._result


def _make_demo_result(
    *,
    success=True,
    operation="place_order",
    dry_run=False,
    reason="",
    manual_review_required=False,
    safety_halt_recommended=False,
    reconciliation_confidence="canonical",
) -> SimpleNamespace:
    """Duck-typed result imitando DemoExecutionResult."""
    ns = SimpleNamespace(
        success=success,
        operation=operation,
        dry_run=dry_run,
        reason=reason,
        manual_review_required=manual_review_required,
        safety_halt_recommended=safety_halt_recommended,
        reconciliation_confidence=reconciliation_confidence,
        trade=None,
    )
    # Adiciona to_dict mínimo para snapshot consistente
    def _to_dict():
        return {
            "success": success,
            "operation": operation,
            "dry_run": dry_run,
            "reason": reason,
            "manual_review_required": manual_review_required,
            "safety_halt_recommended": safety_halt_recommended,
            "reconciliation_confidence": reconciliation_confidence,
        }
    ns.to_dict = _to_dict
    return ns


def _make_risk_engine() -> RiskEngine:
    return RiskEngine(initial_capital=5000.0)


# ===========================================================================
# Gates de rejeição (ANTES de chamar executor)
# ===========================================================================

class TestGateRejections:

    def _common_kwargs(self):
        return dict(
            plan=_make_clean_plan(),
            risk_engine=_make_risk_engine(),
            demo_executor=_FakeExecutor(_make_demo_result()),
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
        )

    def test_confirm_false_rejects(self):
        kw = self._common_kwargs()
        with pytest.raises(DemoSessionRejected, match="confirm_demo_session"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=False, dry_run=True,
            )
        # Executor NÃO foi chamado
        assert kw["demo_executor"].calls == []

    def test_empty_token_rejects(self):
        kw = self._common_kwargs()
        kw["operator_token"] = ""
        with pytest.raises(DemoSessionRejected, match="operator_token"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )
        assert kw["demo_executor"].calls == []

    def test_whitespace_token_rejects(self):
        kw = self._common_kwargs()
        kw["operator_token"] = "   "
        with pytest.raises(DemoSessionRejected, match="operator_token"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )

    def test_non_bool_dry_run_rejects(self):
        kw = self._common_kwargs()
        with pytest.raises(DemoSessionRejected, match="dry_run"):
            execute_demo_session_gated(
                **kw,
                confirm_demo_session=True,
                dry_run="true",  # type: ignore[arg-type]
            )

    def test_safety_not_normal_rejects(self):
        kw = self._common_kwargs()
        kw["safety_machine"].mark_manual_review_required(reason="test")
        with pytest.raises(DemoSessionRejected, match="Safety"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )
        assert kw["demo_executor"].calls == []

    def test_mode_guard_blocks(self):
        kw = self._common_kwargs()
        kw["mode_guard"] = _make_mode_guard_blocking_demo()
        with pytest.raises(DemoSessionRejected, match="ModeGuard"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )
        assert kw["demo_executor"].calls == []

    def test_provider_not_opt_in_blocks(self):
        kw = self._common_kwargs()
        kw["provider_registry"] = _make_local_registry(
            ProviderStatus.RESTRICTED,
        )
        with pytest.raises(DemoSessionRejected, match="Provider"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )

    def test_risk_engine_blocks_executor_not_called(self):
        kw = self._common_kwargs()
        # Mock RiskEngine para rejeitar
        risk = MagicMock()
        risk.validate_signal.return_value = SimpleNamespace(
            approved=False, reason="forced rejection", signal=None,
        )
        kw["risk_engine"] = risk
        with pytest.raises(DemoSessionRejected, match="RiskEngine"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )
        assert kw["demo_executor"].calls == []
        risk.validate_signal.assert_called_once()

    def test_non_plan_input_rejects(self):
        kw = self._common_kwargs()
        kw["plan"] = "not-a-plan"  # type: ignore[arg-type]
        with pytest.raises(DemoSessionRejected, match="plan"):
            execute_demo_session_gated(
                **kw, confirm_demo_session=True, dry_run=True,
            )


# ===========================================================================
# Happy path dry_run
# ===========================================================================

class TestHappyPathDryRun:

    def test_dry_run_default_true(self):
        # Confirma que dry_run é True por default e executor recebe True.
        plan = _make_clean_plan()
        executor = _FakeExecutor(
            _make_demo_result(dry_run=True, reconciliation_confidence="canonical")
        )
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            # dry_run omitido → default True
        )
        assert outcome.dry_run is True
        assert len(executor.calls) == 1
        assert executor.calls[0][1] is True

    def test_dry_run_true_returns_return_to_paper(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(
            _make_demo_result(dry_run=True)
        )
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=True,
        )
        # Dry-run nunca pode ser canonical fill.
        assert outcome.is_filled_canonical is False
        # Default safe action: dry-run sucedido sem flags → RETURN_TO_PAPER
        assert outcome.recommended_next_action is (
            RecommendedNextAction.RETURN_TO_PAPER
        )

    def test_executor_called_exactly_once(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result())
        execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=True,
        )
        assert len(executor.calls) == 1

    def test_post_session_check_called_when_provided(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(dry_run=True))
        post_called: list[int] = []

        def _post():
            post_called.append(1)
            return SimpleNamespace(
                success=True,
                operation="safe_check",
                reason="clean",
                dry_run=True,
                manual_review_required=False,
                safety_halt_recommended=False,
                reconciliation_confidence="canonical",
            )

        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=True,
            post_session_check_fn=_post,
        )
        assert post_called == [1]
        assert outcome.post_session_check_summary is not None

    def test_post_session_check_skipped_when_none(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(dry_run=True))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=True,
            post_session_check_fn=None,
        )
        assert outcome.post_session_check_summary is None


# ===========================================================================
# Pós-submit: triangulated / reconciliation_failed
# ===========================================================================

class TestPostSubmitTransitions:

    def test_canonical_clean_fill_ready_for_next(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            reconciliation_confidence="canonical",
            manual_review_required=False,
            safety_halt_recommended=False,
        ))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        assert outcome.is_filled_canonical is True
        assert outcome.recommended_next_action is (
            RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
        )

    def test_triangulated_never_canonical(self):
        # Mesmo com success=True, triangulated ≠ canonical.
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            reconciliation_confidence="triangulated",
        ))
        safety = SafetyStateMachine()
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=safety,
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        assert outcome.is_filled_canonical is False
        # profile default require_manual_ack_on_triangulation=True
        assert outcome.requires_manual_review is True
        assert outcome.recommended_next_action is (
            RecommendedNextAction.MANUAL_REVIEW_REQUIRED
        )

    def test_triangulated_with_opt_out_still_not_canonical(self):
        # Profile com require_manual_ack=False — outcome marca não-canonical
        # mas pode não exigir manual_review explícito por isso.
        profile = build_personal_profile(
            account_size_usd=5000.0,
            require_manual_ack_on_triangulation=False,
        )
        plan = _make_clean_plan(profile=profile)
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            reconciliation_confidence="triangulated",
        ))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        # Invariante crítica: triangulated NUNCA é canonical.
        assert outcome.is_filled_canonical is False

    def test_manual_review_flag_triggers_review(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            manual_review_required=True,
            reconciliation_confidence="canonical",
        ))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        assert outcome.requires_manual_review is True
        assert outcome.is_filled_canonical is False

    def test_safety_halt_recommended_triggers_halt_action(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=False,
            dry_run=False,
            safety_halt_recommended=True,
            reconciliation_confidence="canonical",
        ))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        assert outcome.safety_halt_recommended is True
        assert outcome.recommended_next_action is (
            RecommendedNextAction.SAFETY_HALT_ACK_NEEDED
        )

    def test_reconciliation_none_triggers_halt_action(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=False,
            dry_run=False,
            reconciliation_confidence="none",
        ))
        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        assert outcome.recommended_next_action is (
            RecommendedNextAction.SAFETY_HALT_ACK_NEEDED
        )
        assert outcome.outcome_reason == "RECONCILIATION_FAILED"

    def test_safety_machine_fed_after_executor(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            safety_halt_recommended=True,
            reason="rec failed",
        ))
        safety = SafetyStateMachine()
        execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=safety,
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
        )
        # safety_machine.from_safety_flags chamado → estado mudou de NORMAL
        assert safety.state is not SafetyState.NORMAL


# ===========================================================================
# Post-session-check com problemas
# ===========================================================================

class TestPostSessionCheckImpact:

    def test_post_check_failure_reflects_manual_review(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            reconciliation_confidence="canonical",
        ))

        def _post():
            return SimpleNamespace(
                success=False,
                operation="safe_check",
                reason="residual position",
                manual_review_required=True,
            )

        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
            post_session_check_fn=_post,
        )
        assert outcome.requires_manual_review is True
        assert outcome.is_filled_canonical is False

    def test_post_check_safety_halt_reflects_in_outcome(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True,
            dry_run=False,
            reconciliation_confidence="canonical",
        ))

        def _post():
            return SimpleNamespace(
                success=False,
                safety_halt_recommended=True,
                reason="residual orders",
            )

        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
            post_session_check_fn=_post,
        )
        assert outcome.safety_halt_recommended is True

    def test_post_check_exception_does_not_crash(self):
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(
            success=True, dry_run=False,
        ))

        def _post():
            raise RuntimeError("network down")

        outcome = execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=_make_local_registry(),
            operator_token="consultorialumos@gmail.com",
            confirm_demo_session=True,
            dry_run=False,
            post_session_check_fn=_post,
        )
        assert outcome.post_session_check_summary is not None
        assert outcome.post_session_check_summary.get("success") is False


# ===========================================================================
# Audit sanitização
# ===========================================================================

class TestAuditSanitization:

    def test_audit_does_not_leak_token(self):
        from crypto_trading_bot.demo_session_execution import gate as gate_mod
        captured: list[str] = []
        with patch.object(
            gate_mod._audit, "info",
            side_effect=lambda msg, *a, **kw: captured.append(str(msg)),
        ):
            plan = _make_clean_plan()
            executor = _FakeExecutor(_make_demo_result(dry_run=True))
            execute_demo_session_gated(
                plan=plan,
                risk_engine=_make_risk_engine(),
                demo_executor=executor,
                safety_machine=SafetyStateMachine(),
                mode_guard=_make_mode_guard_allowing_demo(),
                provider_registry=_make_local_registry(),
                operator_token="consultorialumos@gmail.com_TOKEN_RAW",
                confirm_demo_session=True,
                dry_run=True,
            )
        joined = " ".join(captured)
        assert "consultorialumos@gmail.com_TOKEN_RAW" not in joined
        # truncado em 8 chars
        assert "consulto..." in joined

    def test_audit_redacts_suspicious_notes(self):
        from crypto_trading_bot.demo_session_execution import gate as gate_mod
        captured: list[str] = []
        with patch.object(
            gate_mod._audit, "info",
            side_effect=lambda msg, *a, **kw: captured.append(str(msg)),
        ):
            plan = _make_clean_plan()
            executor = _FakeExecutor(_make_demo_result(dry_run=True))
            outcome = execute_demo_session_gated(
                plan=plan,
                risk_engine=_make_risk_engine(),
                demo_executor=executor,
                safety_machine=SafetyStateMachine(),
                mode_guard=_make_mode_guard_allowing_demo(),
                provider_registry=_make_local_registry(),
                operator_token="op@example.com",
                confirm_demo_session=True,
                dry_run=True,
                notes="approved with api_key=sk-fake",
            )
        joined_log = " ".join(captured)
        assert "sk-fake" not in joined_log
        assert "sk-fake" not in outcome.notes

    def test_rejection_audit_does_not_leak_token(self):
        from crypto_trading_bot.demo_session_execution import gate as gate_mod
        captured: list[str] = []
        with patch.object(
            gate_mod._audit, "info",
            side_effect=lambda msg, *a, **kw: captured.append(str(msg)),
        ):
            plan = _make_clean_plan()
            with pytest.raises(DemoSessionRejected):
                execute_demo_session_gated(
                    plan=plan,
                    risk_engine=_make_risk_engine(),
                    demo_executor=_FakeExecutor(_make_demo_result()),
                    safety_machine=SafetyStateMachine(),
                    mode_guard=_make_mode_guard_allowing_demo(),
                    provider_registry=_make_local_registry(),
                    operator_token="raw_full_token_should_not_leak",
                    confirm_demo_session=False,  # força rejeição
                    dry_run=True,
                )
        joined = " ".join(captured)
        assert "raw_full_token_should_not_leak" not in joined


# ===========================================================================
# ProviderRegistry / Safety / structural invariants
# ===========================================================================

class TestNoMutationInvariants:

    def test_provider_registry_status_unchanged(self):
        reg = _make_local_registry(ProviderStatus.OPT_IN)
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(dry_run=True))
        execute_demo_session_gated(
            plan=plan,
            risk_engine=_make_risk_engine(),
            demo_executor=executor,
            safety_machine=SafetyStateMachine(),
            mode_guard=_make_mode_guard_allowing_demo(),
            provider_registry=reg,
            operator_token="op@x.com",
            confirm_demo_session=True,
            dry_run=True,
        )
        # bybit_demo_linear continua OPT_IN
        assert reg.get("bybit_demo_linear").status is ProviderStatus.OPT_IN

    def test_provider_registry_register_never_called(self):
        reg = _make_local_registry(ProviderStatus.OPT_IN)
        plan = _make_clean_plan()
        with patch.object(reg, "register", side_effect=AssertionError(
            "register não deve ser chamado"
        )):
            with patch.object(reg, "unregister", side_effect=AssertionError(
                "unregister não deve ser chamado"
            )):
                executor = _FakeExecutor(_make_demo_result(dry_run=True))
                execute_demo_session_gated(
                    plan=plan,
                    risk_engine=_make_risk_engine(),
                    demo_executor=executor,
                    safety_machine=SafetyStateMachine(),
                    mode_guard=_make_mode_guard_allowing_demo(),
                    provider_registry=reg,
                    operator_token="op@x.com",
                    confirm_demo_session=True,
                    dry_run=True,
                )

    def test_safety_machine_not_reset(self):
        # Gate não chama acknowledge/resolve/reset.
        safety = SafetyStateMachine()
        safety.mark_manual_review_required(reason="pre-existing")
        plan = _make_clean_plan()
        executor = _FakeExecutor(_make_demo_result(dry_run=True))
        with pytest.raises(DemoSessionRejected):
            execute_demo_session_gated(
                plan=plan,
                risk_engine=_make_risk_engine(),
                demo_executor=executor,
                safety_machine=safety,
                mode_guard=_make_mode_guard_allowing_demo(),
                provider_registry=_make_local_registry(),
                operator_token="op@x.com",
                confirm_demo_session=True,
                dry_run=True,
            )
        # Estado preservado
        assert safety.state is SafetyState.MANUAL_REVIEW_REQUIRED
