"""
Tests - FASE 32: IA como apoio de decisao
==========================================
100% offline. IA mockada. ZERO rede. ZERO secret. A IA NUNCA altera
TradingSignal/RiskResult nem bypassa gate.
"""

from __future__ import annotations

import copy

import pytest

from crypto_trading_bot.ai_assistant import (
    AIAdvice,
    AIAdviceStatus,
    AIAdvisorProtocol,
    AIDecisionSupport,
    AISuggestedAction,
    MockAIAdvisor,
    adapt_prediction_context_for_ai,
    build_ai_context,
    build_risk_commentary,
    compare_long_short,
    explain_hold,
    sanitize_for_ai,
    summarize_signal,
)
from crypto_trading_bot.operational_profile import resolve_profile


def _ctx(**kw):
    base = dict(
        symbol="BTCUSDT", profile_name="ai_assisted_demo", cycle_idx=0,
        signal_snapshot={"signal_side": "buy", "rsi_value": 55.0},
        risk_summary={"approved": True, "reason": ""},
    )
    base.update(kw)
    return build_ai_context(**base)


class TestAIAdviceInvariants:

    def test_advice_never_overrides_risk_engine(self):
        with pytest.raises(ValueError, match="SEMPRE True"):
            AIAdvice(
                status=AIAdviceStatus.NEUTRAL, confidence=0.5,
                reason="x", does_not_override_risk_engine=False,
            )

    def test_advice_to_dict(self):
        a = AIAdvice(
            status=AIAdviceStatus.CAUTION, confidence=0.7,
            reason="r", warnings=("w1",),
            suggested_action=AISuggestedAction.WAIT,
        )
        d = a.to_dict()
        assert d["does_not_override_risk_engine"] is True
        assert d["status"] == "caution"

    def test_mock_implements_protocol(self):
        assert isinstance(MockAIAdvisor(), AIAdvisorProtocol)


class TestNoSecretsReachAI:

    def test_sanitize_drops_secret_keys(self):
        dirty = {
            "api_key": "SECRET", "api_secret": "SECRET2",
            "Authorization": "Bearer x", "X-BAPI-SIGN": "sig",
            "password": "p", "rsi_value": 55,
            "nested": {"token": "t", "last_close": 100.0},
        }
        clean = sanitize_for_ai(dirty)
        text = str(clean).lower()
        assert "secret" not in text
        assert "bearer" not in text
        assert clean["rsi_value"] == 55
        assert clean["nested"]["last_close"] == 100.0
        assert "token" not in clean["nested"]

    def test_objects_never_pass_through(self):
        class Mutable:
            def boom(self):
                pass
        clean = sanitize_for_ai({"engine": Mutable()})
        assert clean["engine"] == "<Mutable>"

    def test_context_builder_sanitizes_all_blocks(self):
        ctx = _ctx(
            signal_snapshot={"api_key": "S", "rsi_value": 50},
            risk_summary={"authorization": "B", "approved": True},
            market_meta={"x-bapi-sign": "x", "ttl": 30},
        )
        text = str(ctx).lower()
        assert "api_key" not in text
        assert "authorization" not in text
        assert ctx["signal_snapshot"]["rsi_value"] == 50
        assert ctx["market_meta"]["ttl"] == 30

    def test_mock_ai_receives_no_secret(self):
        advisor = MockAIAdvisor()
        advisor.evaluate_trade_context(_ctx(
            signal_snapshot={"api_secret": "S", "rsi_value": 50},
        ))
        assert "api_secret" not in str(advisor.last_context)


class TestAIDoesNotMutate:

    def test_ai_does_not_alter_trading_signal(self):
        from crypto_trading_bot.strategies.signal_model import (
            StrategySignal,
        )
        sig = StrategySignal.buy(
            symbol="BTCUSDT", strategy_name="s", entry_price=100.0,
            stop_loss_price=99.0, take_profit_price=102.0,
            position_size_usd=200.0,
        )
        snapshot_before = (
            sig.entry_price, sig.stop_loss_price,
            sig.take_profit_price, sig.action,
        )
        advisor = MockAIAdvisor()
        advisor.evaluate_trade_context(_ctx(
            signal_snapshot={
                "entry_price": sig.entry_price,
                "signal_side": "buy",
            },
        ))
        assert (
            sig.entry_price, sig.stop_loss_price,
            sig.take_profit_price, sig.action,
        ) == snapshot_before

    def test_ai_does_not_alter_risk_summary(self):
        risk = {"approved": False, "reason": "blocked"}
        frozen = copy.deepcopy(risk)
        MockAIAdvisor().evaluate_trade_context(_ctx(risk_summary=risk))
        assert risk == frozen

    def test_ai_defers_when_risk_rejected(self):
        advice = MockAIAdvisor().evaluate_trade_context(_ctx(
            risk_summary={"approved": False, "reason": "limit"},
        ))
        # IA nao aprova o que o risco reprovou.
        assert advice.status is not AIAdviceStatus.NEUTRAL
        assert advice.suggested_action is not AISuggestedAction.PROCEED


class TestDecisionSupportFusion:

    def test_profile_without_ai_never_calls_advisor(self):
        profile = resolve_profile("demo_validation", capital=5000.0)
        advisor = MockAIAdvisor()
        out = AIDecisionSupport(advisor=advisor).evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        assert out.ai_enabled is False
        assert advisor.calls == 0

    def test_veto_blocks_cycle_when_profile_allows(self):
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(forced_status=AIAdviceStatus.VETO),
        )
        out = ds.evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        assert out.cycle_blocked is True
        assert out.manual_review_required is False

    def test_veto_is_consultive_when_profile_disallows(self):
        profile = resolve_profile(
            "ai_assisted_demo", capital=5000.0, allow_ai_veto=False,
        )
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(forced_status=AIAdviceStatus.VETO),
        )
        out = ds.evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        assert out.cycle_blocked is False  # parecer vira warning

    def test_manual_review_requires_env_gate(self, monkeypatch):
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(
                forced_status=AIAdviceStatus.MANUAL_REVIEW,
            ),
        )
        monkeypatch.delenv(
            "DEMO_ALLOW_AI_MANUAL_REVIEW", raising=False,
        )
        out = ds.evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        # Sem gate: degrade conservador (bloqueia ciclo, sem escalar).
        assert out.cycle_blocked is True
        assert out.manual_review_required is False
        monkeypatch.setenv("DEMO_ALLOW_AI_MANUAL_REVIEW", "true")
        out2 = ds.evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=1,
        )
        assert out2.manual_review_required is True

    def test_advisor_exception_never_breaks_pipeline(self):
        class Exploding:
            def evaluate_trade_context(self, context):
                raise RuntimeError("boom")
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        out = AIDecisionSupport(advisor=Exploding()).evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        assert out.ai_enabled is True
        assert out.cycle_blocked is False  # falha da IA nao bloqueia

    def test_report_fields_present(self):
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        out = AIDecisionSupport(advisor=MockAIAdvisor()).evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        fields = out.to_report_fields()
        for key in ("ai_enabled", "ai_status", "ai_reason",
                    "ai_warnings", "ai_manual_review_required"):
            assert key in fields

    def test_telemetry_events_emitted(self):
        events = []
        profile = resolve_profile("ai_assisted_demo", capital=5000.0)
        ds = AIDecisionSupport(
            advisor=MockAIAdvisor(forced_status=AIAdviceStatus.VETO),
            telemetry_emit=lambda et, **s: events.append(et),
        )
        ds.evaluate_cycle(
            profile=profile, ai_context=_ctx(), cycle_idx=0,
        )
        assert "ai_context_built" in events
        assert "ai_advice_generated" in events
        assert "ai_veto_triggered" in events


class TestExplainers:

    def test_explain_hold_known_reason(self):
        text = explain_hold({
            "hold_reason": "no_uptrend",
            "failed_conditions_long": ["no_uptrend"],
        })
        assert "EMA" in text
        assert "no_uptrend" in text

    def test_summarize_and_compare(self):
        snap = {
            "symbol": "BTCUSDT", "signal_side": "buy",
            "last_close": 100.0, "ema_fast_value": 101.0,
            "ema_slow_value": 99.0, "rsi_value": 50.0,
            "long_conditions": {"uptrend": True, "rsi_ok": True},
            "short_conditions": {"downtrend": False},
        }
        assert "BTCUSDT" in summarize_signal(snap)
        assert "long_conditions_met=2/2" in compare_long_short(snap)

    def test_risk_commentary_flags_extremes(self):
        notes = build_risk_commentary(
            risk_summary={"approved": True},
            signal_snapshot={"rsi_value": 85.0, "last_close": 100.0,
                             "atr_value": 5.0},
            prediction_context={"risk_flags": ["macro_event_volatility"],
                                "stale": True},
        )
        text = " ".join(notes)
        assert "RSI" in text
        assert "STALE" in text


class TestPredictionAdapter:

    def test_adapter_handles_disabled_and_none(self):
        assert adapt_prediction_context_for_ai(None) is None
        assert adapt_prediction_context_for_ai(
            {"enabled": False},
        ) is None

    def test_adapter_reduces_events_to_consultive_fields(self):
        ctx = {
            "enabled": True, "provider": "polymarket_readonly",
            "mode": "advisory", "stale": False, "age_seconds": 10.0,
            "risk_flags": ["macro_event_volatility"],
            "summary": "s", "events_considered": 1,
            "btc_relevant_events": [{
                "event_title": "Fed", "category": "fed",
                "probability": 0.6, "probability_change_24h": 8.0,
                "volume": 1.0, "risk_flag": "macro_event_volatility",
                "api_key": "SHOULD_NOT_PASS",
            }],
        }
        adapted = adapt_prediction_context_for_ai(ctx)
        assert adapted["risk_flags"] == ["macro_event_volatility"]
        assert "api_key" not in str(adapted).lower()
