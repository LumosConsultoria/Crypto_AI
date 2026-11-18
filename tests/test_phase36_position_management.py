"""
Tests - FASE 36 Bloco E2: Position Management / risco agregado
===============================================================
100% offline. Capacidade existe, mas e DEFAULT OFF: sem gate +
perfil + limites + confirmacao, TUDO bloqueia.
Limites usados aqui sao FIXTURES DE TESTE explicitamente marcadas.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.operational_profile import resolve_profile
from crypto_trading_bot.position_management import (
    AggregatedRiskSnapshot,
    MultiOrderPolicy,
    PositionEntry,
    PositionState,
    ScaleInLimits,
    ScaleInProposal,
    evaluate_partial_reduce,
    evaluate_reversal,
    evaluate_scale_in,
)

_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

# FIXTURE DE TESTE (limites V5-V6 arbitrarios p/ exercitar mecanismo).
_TEST_LIMITS = ScaleInLimits(
    max_scale_ins_per_position=2,
    max_added_risk_pct=0.5,
    max_aggregated_risk_pct=1.0,
    min_entry_distance_pct=0.5,
    min_time_between_scale_ins_minutes=15,
    sl_move_policy="never",
)

_TEST_CAPITAL = 5000.0  # FIXTURE DE TESTE


def _position(side="buy", entries=None, sl=99.0):
    return PositionState(
        symbol="BTCUSDT", side=side,
        entries=tuple(entries or [
            PositionEntry(price=100.0, qty=0.2, entered_at=_NOW),
        ]),
        stop_loss=sl, take_profit=104.0,
    )


def _proposal(**kw):
    base = dict(
        symbol="BTCUSDT", side="buy", add_qty=0.1, add_price=101.0,
        signal_independent=True, minutes_since_last_entry=30.0,
    )
    base.update(kw)
    return ScaleInProposal(**base)


def _scale_profile(**ov):
    return resolve_profile(
        "demo_multi_order_validation", capital=_TEST_CAPITAL,
        allow_scale_in=True, **ov,
    )


class _RiskApprove:
    def __init__(self):
        self.signals = []

    def validate_signal(self, signal):
        self.signals.append(signal)

        class _R:
            approved = True
            reason = ""
        return _R()


class _RiskReject:
    def validate_signal(self, signal):
        class _R:
            approved = False
            reason = "fixture: incremento reprovado"
        return _R()


def _eval(monkeypatch=None, *, gate=True, profile=None, limits=None,
          position=None, proposal=None, risk=None, confirmed=True):
    if monkeypatch is not None:
        if gate:
            monkeypatch.setenv("DEMO_ALLOW_SCALE_IN_ENABLED", "true")
        else:
            monkeypatch.delenv(
                "DEMO_ALLOW_SCALE_IN_ENABLED", raising=False,
            )
    return evaluate_scale_in(
        profile=profile or _scale_profile(),
        limits=limits or _TEST_LIMITS,
        position=position or _position(),
        proposal=proposal or _proposal(),
        capital_usd=_TEST_CAPITAL,
        risk_engine=risk or _RiskApprove(),
        operator_confirmed=confirmed,
    )


class TestPositionState:

    def test_avg_price_and_aggregated_qty(self):
        pos = _position(entries=[
            PositionEntry(price=100.0, qty=0.2, entered_at=_NOW),
            PositionEntry(price=102.0, qty=0.1, entered_at=_NOW),
        ])
        assert pos.qty == pytest.approx(0.3)
        assert pos.avg_entry_price == pytest.approx(100.6667, abs=1e-3)
        assert pos.scale_in_count == 1

    def test_risk_to_stop(self):
        pos = _position()
        assert pos.risk_to_stop_usd() == pytest.approx(0.2)  # 1*0.2

    def test_aggregated_risk_snapshot_pcts(self):
        snap = AggregatedRiskSnapshot(
            capital_usd=_TEST_CAPITAL, current_risk_usd=10.0,
            added_risk_usd=5.0, sl_used_for_calc=99.0,
        )
        assert snap.total_risk_usd == 15.0
        assert snap.total_risk_pct == pytest.approx(0.3)


class TestScaleInDefaultOff:

    def test_blocked_without_gate(self, monkeypatch):
        d = _eval(monkeypatch, gate=False)
        assert not d.approved
        assert any("DEMO_ALLOW_SCALE_IN_ENABLED" in b
                   for b in d.blockers)

    def test_blocked_without_profile_permission(self, monkeypatch):
        profile = resolve_profile(
            "demo_multi_order_validation", capital=_TEST_CAPITAL,
        )  # allow_scale_in default False
        d = _eval(monkeypatch, profile=profile)
        assert not d.approved
        assert any("allow_scale_in" in b for b in d.blockers)

    def test_blocked_missing_limits(self, monkeypatch):
        d = _eval(monkeypatch, limits=ScaleInLimits())
        assert not d.approved
        assert any("blocked_missing_limits" in b for b in d.blockers)
        assert any("max_aggregated_risk_pct" in b for b in d.blockers)

    def test_blocked_without_confirmation(self, monkeypatch):
        d = _eval(monkeypatch, confirmed=False)
        assert not d.approved
        assert any("confirmacao humana" in b for b in d.blockers)

    def test_all_profiles_default_scale_in_off(self):
        from crypto_trading_bot.operational_profile import (
            SUPPORTED_PROFILE_NAMES,
        )
        for name in SUPPORTED_PROFILE_NAMES:
            p = resolve_profile(name, capital=_TEST_CAPITAL)
            assert p.allow_scale_in is False, name
            assert p.allow_partial_reduce is False, name
            assert p.allow_reversal == "blocked", name


class TestScaleInRules:

    def test_approved_with_everything(self, monkeypatch):
        risk = _RiskApprove()
        d = _eval(monkeypatch, risk=risk)
        assert d.approved, d.blockers
        assert d.aggregated_risk is not None
        # RiskEngine FOI consultado com o incremento (soberania).
        assert len(risk.signals) == 1
        assert risk.signals[0].position_size_usd == \
            pytest.approx(10.1)

    def test_risk_engine_rejection_blocks(self, monkeypatch):
        d = _eval(monkeypatch, risk=_RiskReject())
        assert not d.approved
        assert any("RiskEngine reprovou" in b for b in d.blockers)

    def test_never_sums_position_without_risk_recalc(self, monkeypatch):
        d = _eval(monkeypatch)
        # Decisao SEMPRE carrega o snapshot de risco agregado.
        assert d.aggregated_risk.added_risk_usd > 0
        assert d.aggregated_risk.total_risk_usd >= \
            d.aggregated_risk.current_risk_usd

    def test_opposite_side_blocked(self, monkeypatch):
        d = _eval(monkeypatch, proposal=_proposal(side="sell"))
        assert not d.approved
        assert any("reversao via scale-in proibida" in b
                   for b in d.blockers)

    def test_max_scale_ins_enforced(self, monkeypatch):
        pos = _position(entries=[
            PositionEntry(price=100.0, qty=0.1, entered_at=_NOW),
            PositionEntry(price=101.0, qty=0.1, entered_at=_NOW),
            PositionEntry(price=102.0, qty=0.1, entered_at=_NOW),
        ])  # ja tem 2 scale-ins; max fixture = 2
        d = _eval(monkeypatch, position=pos,
                  proposal=_proposal(add_price=103.0))
        assert not d.approved
        assert any("max_scale_ins" in b for b in d.blockers)

    def test_min_distance_enforced(self, monkeypatch):
        d = _eval(monkeypatch, proposal=_proposal(add_price=100.1))
        assert not d.approved
        assert any("distancia" in b for b in d.blockers)

    def test_min_time_enforced(self, monkeypatch):
        d = _eval(
            monkeypatch,
            proposal=_proposal(minutes_since_last_entry=5.0),
        )
        assert not d.approved
        assert any("tempo desde a ultima" in b for b in d.blockers)

    def test_non_independent_signal_blocked(self, monkeypatch):
        d = _eval(
            monkeypatch,
            proposal=_proposal(signal_independent=False),
        )
        assert not d.approved

    def test_sl_move_never_policy(self, monkeypatch):
        d = _eval(
            monkeypatch,
            proposal=_proposal(proposed_new_sl=100.0),
        )
        assert not d.approved
        assert any("sl_move_policy=never" in b for b in d.blockers)

    def test_sl_move_only_in_favor(self, monkeypatch):
        limits = ScaleInLimits(
            max_scale_ins_per_position=2, max_added_risk_pct=0.5,
            max_aggregated_risk_pct=1.0, min_entry_distance_pct=0.5,
            min_time_between_scale_ins_minutes=15,
            sl_move_policy="only_in_favor",
        )
        # BUY: SL p/ cima = a favor.
        d = _eval(monkeypatch, limits=limits,
                  proposal=_proposal(proposed_new_sl=99.5))
        assert d.approved, d.blockers
        assert d.effective_sl == 99.5
        # SL p/ baixo = contra => bloqueia.
        d2 = _eval(monkeypatch, limits=limits,
                   proposal=_proposal(proposed_new_sl=98.0))
        assert not d2.approved

    def test_aggregated_risk_cap_enforced(self, monkeypatch):
        # FIXTURE: add grande estoura max_added_risk_pct (0.5% de 5000
        # = 25 USD; risco = |101-99|*qty => qty 20 = 40 USD > 25).
        d = _eval(monkeypatch, proposal=_proposal(add_qty=20.0))
        assert not d.approved
        assert any("risco" in b for b in d.blockers)


class TestPartialReduce:

    def test_blocked_without_gate(self, monkeypatch):
        monkeypatch.delenv(
            "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED", raising=False,
        )
        d = evaluate_partial_reduce(
            profile=_scale_profile(allow_partial_reduce=True),
            max_reduce_pct=50.0, position=_position(),
            reduce_qty=0.05, operator_confirmed=True,
        )
        assert not d.approved

    def test_never_inverts_position(self, monkeypatch):
        monkeypatch.setenv(
            "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED", "true",
        )
        d = evaluate_partial_reduce(
            profile=_scale_profile(allow_partial_reduce=True),
            max_reduce_pct=100.0, position=_position(),
            reduce_qty=0.5,   # > qty 0.2 => inversao proibida
            operator_confirmed=True,
        )
        assert not d.approved
        assert any("inversao proibida" in b for b in d.blockers)

    def test_reduce_only_always_true(self, monkeypatch):
        monkeypatch.setenv(
            "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED", "true",
        )
        d = evaluate_partial_reduce(
            profile=_scale_profile(allow_partial_reduce=True),
            max_reduce_pct=50.0, position=_position(),
            reduce_qty=0.05, operator_confirmed=True,
        )
        assert d.approved, d.blockers
        assert d.reduce_only is True
        assert d.remaining_qty == pytest.approx(0.15)

    def test_missing_limit_blocks(self, monkeypatch):
        monkeypatch.setenv(
            "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED", "true",
        )
        d = evaluate_partial_reduce(
            profile=_scale_profile(allow_partial_reduce=True),
            max_reduce_pct=None, position=_position(),
            reduce_qty=0.05, operator_confirmed=True,
        )
        assert not d.approved
        assert any("blocked_missing_limits" in b for b in d.blockers)


class TestReversal:

    def test_auto_execution_structurally_impossible(self):
        from crypto_trading_bot.position_management import (
            ReversalDecision,
        )
        with pytest.raises(ValueError, match="PROIBIDA"):
            ReversalDecision(
                approved_for_auto_execution=True,
                manual_review_required=False, blockers=(),
            )

    def test_requires_flat_first(self, monkeypatch):
        monkeypatch.setenv("DEMO_ALLOW_REVERSAL_ENABLED", "true")
        d = evaluate_reversal(
            profile=_scale_profile(
                allow_reversal="manual_review_only",
            ),
            position_flat_confirmed=False, operator_confirmed=True,
        )
        assert not d.manual_review_required
        assert any("flat" in b for b in d.blockers)

    def test_best_case_is_manual_review(self, monkeypatch):
        monkeypatch.setenv("DEMO_ALLOW_REVERSAL_ENABLED", "true")
        d = evaluate_reversal(
            profile=_scale_profile(
                allow_reversal="manual_review_only",
            ),
            position_flat_confirmed=True, operator_confirmed=True,
        )
        assert d.manual_review_required is True
        assert d.approved_for_auto_execution is False

    def test_blocked_profile_blocks(self, monkeypatch):
        monkeypatch.setenv("DEMO_ALLOW_REVERSAL_ENABLED", "true")
        d = evaluate_reversal(
            profile=_scale_profile(),   # allow_reversal=blocked
            position_flat_confirmed=True, operator_confirmed=True,
        )
        assert not d.manual_review_required
        assert any("blocked" in b for b in d.blockers)

    def test_invalid_profile_value_rejected(self):
        with pytest.raises(ValueError, match="allow_reversal"):
            resolve_profile(
                "personal", capital=_TEST_CAPITAL,
                allow_reversal="auto",
            )


class TestMultiOrderPolicy:

    def test_sequential_blocks_with_open_position(self):
        policy = MultiOrderPolicy(max_open_positions=1)
        ok, why = policy.can_enter_new(
            open_positions_count=1, open_orders_count=0,
            conditional_orders_count=0,
        )
        assert not ok and "sequencial" in why

    def test_blocks_with_pending_orders(self):
        policy = MultiOrderPolicy()
        ok, _ = policy.can_enter_new(
            open_positions_count=0, open_orders_count=1,
            conditional_orders_count=0,
        )
        assert not ok
        ok2, _ = policy.can_enter_new(
            open_positions_count=0, open_orders_count=0,
            conditional_orders_count=2,
        )
        assert not ok2

    def test_allows_when_flat(self):
        ok, why = MultiOrderPolicy().can_enter_new(
            open_positions_count=0, open_orders_count=0,
            conditional_orders_count=0,
        )
        assert ok and why == ""


class TestDiscoveryStillClean:

    def test_e2_gates_now_in_code_and_registry(self):
        from crypto_trading_bot.operational_options import (
            OperationalOptionsRegistry, run_option_discovery_audit,
        )
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        found = set(report.declared_env_gates_in_code)
        assert "DEMO_ALLOW_SCALE_IN_ENABLED" in found
        assert "DEMO_ALLOW_PARTIAL_REDUCE_ENABLED" in found
        assert "DEMO_ALLOW_REVERSAL_ENABLED" in found
        assert report.env_gates_missing_in_registry == ()
        assert report.profile_fields_missing_in_registry == ()
