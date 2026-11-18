"""
Tests - FASE 34: Polymarket / prediction markets READ-ONLY
===========================================================
100% offline. Client mockado. ZERO rede. ZERO aposta/ordem.
Execution seam BLOQUEADO.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.prediction_markets import (
    MarketEvent,
    PolymarketReadonlyClient,
    PredictionExecutionBlocked,
    PredictionMarketExecutionProtocol,
    build_prediction_context,
    derive_risk_flags,
    disabled_context,
    normalize_raw_event,
    normalize_raw_events,
)
from crypto_trading_bot.operational_profile import resolve_profile


_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)

_RAW_FED = {
    "market_id": "mk-1", "title": "Fed rate decision June",
    "probability": 0.62, "probability_change_24h": 8.5,
    "volume": 1200000.0, "liquidity": 500000.0,
    "category": "fed", "btc_relevance_score": 0.9,
}


class TestReadonlyClient:

    def test_client_is_readonly_and_mocked(self):
        client = PolymarketReadonlyClient(
            raw_fetcher=lambda: [_RAW_FED],
        )
        events = client.fetch_events()
        assert len(events) == 1
        assert isinstance(events[0], MarketEvent)
        with pytest.raises(PermissionError):
            client.place_bet("anything")
        with pytest.raises(PermissionError):
            client.place_order("anything")

    def test_no_fetcher_returns_empty_failsafe(self):
        client = PolymarketReadonlyClient(raw_fetcher=None)
        assert client.fetch_events() == []

    def test_fetcher_error_failsafe_no_raise(self):
        def boom():
            raise ConnectionError("offline")
        client = PolymarketReadonlyClient(raw_fetcher=boom)
        assert client.fetch_events() == []
        assert client.fetch_failures == 1


class TestExecutionSeamBlocked:

    def test_all_execution_methods_blocked(self):
        seam = PredictionMarketExecutionProtocol()
        assert seam.enabled is False
        for method in ("place_bet", "place_order", "cancel",
                       "withdraw"):
            with pytest.raises(PredictionExecutionBlocked):
                getattr(seam, method)()


class TestNormalizer:

    def test_normalizes_valid_payload(self):
        ev = normalize_raw_event(_RAW_FED)
        assert ev is not None
        assert ev.category == "fed"
        assert ev.risk_flag is not None  # 8.5pp shift -> flag

    def test_invalid_payloads_dropped_not_raised(self):
        assert normalize_raw_event({}) is None
        assert normalize_raw_event({"market_id": "x"}) is None
        events = normalize_raw_events(
            [_RAW_FED, {}, "not-a-dict", None],
        )
        assert len(events) == 1

    def test_probability_clamped(self):
        ev = normalize_raw_event(
            {**_RAW_FED, "probability": 7.5},
        )
        assert ev.probability == 1.0


class TestRiskFlags:

    def test_macro_volatility_flag(self):
        ev = normalize_raw_event(_RAW_FED)
        flags = derive_risk_flags(ev)
        assert "macro_event_volatility" in flags
        assert "rapid_probability_shift" in flags

    def test_no_flags_for_quiet_event(self):
        ev = MarketEvent(
            market_id="m", event_title="quiet", category="other",
            outcome="yes", probability=0.5,
            probability_change_24h=0.5, liquidity=1e9,
        )
        assert derive_risk_flags(ev) == []


class TestPredictionContext:

    def test_context_builds_with_flags_and_summary(self):
        events = normalize_raw_events([_RAW_FED])
        ctx = build_prediction_context(
            events=events, mode="advisory", fetched_at=_NOW, now=_NOW,
        )
        assert ctx.enabled
        assert ctx.risk_flags
        assert ctx.summary and "uncertainty" in ctx.summary
        assert not ctx.stale
        d = ctx.to_dict()
        assert d["events_considered"] == 1
        assert d["risk_flags"]

    def test_stale_context_flagged(self):
        events = normalize_raw_events([_RAW_FED])
        ctx = build_prediction_context(
            events=events, mode="read_only",
            fetched_at=_NOW - timedelta(seconds=600), now=_NOW,
            max_age_seconds=300.0,
        )
        assert ctx.stale is True

    def test_disabled_context(self):
        ctx = disabled_context()
        assert not ctx.enabled
        assert ctx.mode == "disabled"

    def test_context_never_produces_buy_sell(self):
        # Defesa estrutural: contexto nao tem campo de acao/ordem.
        ctx = build_prediction_context(
            events=normalize_raw_events([_RAW_FED]),
            fetched_at=_NOW, now=_NOW,
        )
        d = ctx.to_dict()
        text = str(d).lower()
        for forbidden in ("'action'", "place_order", "place_bet",
                          "side="):
            assert forbidden not in text


class TestContextDoesNotMutateSignalOrRisk:

    def test_signal_and_risk_untouched(self):
        from crypto_trading_bot.strategies.signal_model import (
            StrategySignal,
        )
        sig = StrategySignal.buy(
            symbol="BTCUSDT", strategy_name="s", entry_price=100.0,
            stop_loss_price=99.0, position_size_usd=200.0,
        )
        before = (sig.entry_price, sig.stop_loss_price, sig.action)
        risk = {"approved": True, "reason": ""}
        risk_before = dict(risk)
        build_prediction_context(
            events=normalize_raw_events([_RAW_FED]),
            fetched_at=_NOW, now=_NOW,
        )
        assert (sig.entry_price, sig.stop_loss_price,
                sig.action) == before
        assert risk == risk_before


class TestProfilesControlPrediction:

    def test_profile_can_disable(self):
        p = resolve_profile("prop_challenge", capital=5000.0)
        assert p.prediction_context_mode == "disabled"
        assert p.allow_prediction_market_context is False

    def test_profile_read_only_and_advisory(self):
        ro = resolve_profile("research_only", capital=5000.0)
        assert ro.prediction_context_mode == "read_only"
        adv = resolve_profile("ai_assisted_demo", capital=5000.0)
        assert adv.prediction_context_mode == "advisory"

    def test_execution_always_false_in_all_profiles(self):
        from crypto_trading_bot.operational_profile import (
            SUPPORTED_PROFILE_NAMES,
        )
        for name in SUPPORTED_PROFILE_NAMES:
            p = resolve_profile(name, capital=5000.0)
            assert p.prediction_market_execution_allowed is False


class TestPredictionViaAIManualReview:

    def test_stale_context_generates_caution_via_ai(self):
        from crypto_trading_bot.ai_assistant import (
            MockAIAdvisor, build_ai_context,
            adapt_prediction_context_for_ai,
        )
        ctx = build_prediction_context(
            events=normalize_raw_events([_RAW_FED]),
            fetched_at=_NOW - timedelta(seconds=900), now=_NOW,
        )
        adapted = adapt_prediction_context_for_ai(ctx)
        advice = MockAIAdvisor().evaluate_trade_context(
            build_ai_context(
                symbol="BTCUSDT", profile_name="p", cycle_idx=0,
                prediction_context=adapted,
            ),
        )
        assert advice.status.value == "caution"
        assert any("stale" in w for w in advice.warnings)

    def test_no_secret_persisted_in_context(self):
        raw = {**_RAW_FED, "api_key": "SHOULD_NEVER_APPEAR"}
        events = normalize_raw_events([raw])
        ctx = build_prediction_context(
            events=events, fetched_at=_NOW, now=_NOW,
        )
        assert "SHOULD_NEVER_APPEAR" not in str(ctx.to_dict())
