"""
Tests - FASE 36 Blocos C/D: Market Intelligence + IA provider seam
===================================================================
100% offline. Fontes mockadas. Fonte ausente/stale NUNCA bloqueia.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.ai_assistant import (
    MockAIAdvisor,
    api_key_present,
    redact_text,
    resolve_ai_advisor,
)
from crypto_trading_bot.market_intelligence import (
    ContextSlice,
    ExchangeStatusAdapter,
    FundingRateAdapter,
    MarketIntelligenceAggregator,
    NewsAdapter,
    OpenInterestAdapter,
    OrderbookAdapter,
    PolymarketAdapter,
    VolatilityCorrelationAdapter,
    market_intelligence_gate_enabled,
    unavailable_slice,
)

_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)


class TestAdapters:

    def test_no_transport_means_unavailable_failsafe(self):
        for adapter_cls in (
            FundingRateAdapter, OpenInterestAdapter,
            OrderbookAdapter, NewsAdapter, ExchangeStatusAdapter,
            VolatilityCorrelationAdapter,
        ):
            sl = adapter_cls().fetch()
            assert sl.available is False
            assert sl.error == "no_transport"

    def test_fetcher_error_failsafe(self):
        def boom():
            raise ConnectionError("offline")
        sl = FundingRateAdapter(raw_fetcher=boom).fetch()
        assert sl.available is False
        assert sl.error == "ConnectionError"

    def test_funding_flags_extreme(self):
        sl = FundingRateAdapter(
            raw_fetcher=lambda: {"funding_rate": 0.001},
            clock=lambda: _NOW,
        ).fetch()
        assert sl.available
        assert "extreme_funding" in sl.risk_flags

    def test_orderbook_flags_thin_liquidity_and_spread(self):
        sl = OrderbookAdapter(
            raw_fetcher=lambda: {
                "spread_bps": 15.0, "depth_usd_1pct": 10000.0,
            },
            clock=lambda: _NOW,
        ).fetch()
        assert "wide_spread" in sl.risk_flags
        assert "thin_liquidity" in sl.risk_flags

    def test_news_mock_adapter(self):
        sl = NewsAdapter(
            raw_fetcher=lambda: {
                "headlines": ["Fed decision today"],
                "sentiment": "very_negative",
                "high_impact_event": True,
            },
            clock=lambda: _NOW,
        ).fetch()
        assert "negative_news_sentiment" in sl.risk_flags
        assert "high_impact_news_event" in sl.risk_flags

    def test_polymarket_adapter_reuses_fase34(self):
        from crypto_trading_bot.prediction_markets import (
            PolymarketReadonlyClient,
        )
        client = PolymarketReadonlyClient(raw_fetcher=lambda: [{
            "market_id": "m1", "title": "Fed rate decision",
            "probability": 0.6, "probability_change_24h": 9.0,
            "volume": 1e6, "category": "fed",
            "btc_relevance_score": 0.9,
        }])
        sl = PolymarketAdapter(
            client=client, clock=lambda: _NOW,
        ).fetch()
        assert sl.available
        assert sl.risk_flags  # macro flags da FASE 34

    def test_exchange_degraded_flag(self):
        sl = ExchangeStatusAdapter(
            raw_fetcher=lambda: {"status": "maintenance"},
            clock=lambda: _NOW,
        ).fetch()
        assert "exchange_degraded" in sl.risk_flags


class TestAggregator:

    def _agg(self, clock=None):
        return MarketIntelligenceAggregator(
            providers=[
                FundingRateAdapter(
                    raw_fetcher=lambda: {"funding_rate": 0.001},
                    clock=clock or (lambda: _NOW),
                ),
                OrderbookAdapter(
                    raw_fetcher=lambda: {
                        "spread_bps": 1.0,
                        "depth_usd_1pct": 1e6,
                    },
                    clock=clock or (lambda: _NOW),
                ),
                NewsAdapter(),                  # sem transporte
            ],
            clock=clock or (lambda: _NOW),
        )

    def test_snapshot_used_and_unavailable(self):
        snap = self._agg().snapshot()
        assert set(snap["sources_used"]) == {"funding", "orderbook"}
        assert snap["sources_unavailable"] == ["news"]
        assert "extreme_funding" in snap["risk_flags"]
        assert snap["summary"]

    def test_unavailable_source_never_blocks(self):
        # Agregador com TODAS as fontes indisponiveis ainda produz
        # snapshot valido (pipeline nunca bloqueia por MI).
        agg = MarketIntelligenceAggregator(
            providers=[NewsAdapter(), FundingRateAdapter()],
            clock=lambda: _NOW,
        )
        snap = agg.snapshot()
        assert snap["sources_used"] == []
        assert len(snap["sources_unavailable"]) == 2
        assert snap["risk_flags"] == []

    def test_stale_detection_via_ttl(self):
        clock_state = {"now": _NOW}

        def clock():
            return clock_state["now"]

        agg = MarketIntelligenceAggregator(
            providers=[FundingRateAdapter(
                raw_fetcher=lambda: {"funding_rate": 0.0},
                clock=clock,
            )],
            clock=clock,
        )
        snap1 = agg.snapshot()
        assert snap1["sources_stale"] == []
        # Avanca alem do TTL (300s) SEM refetch possivel? O cache
        # expira e refaz fetch — para stale, o slice retorna com
        # fetched_at antigo via clock manipulado no adapter:
        clock_state["now"] = _NOW + timedelta(seconds=600)
        snap2 = agg.snapshot()
        # refetch ocorreu com novo timestamp -> usado e fresco.
        assert "funding" in snap2["sources_used"]

    def test_provider_exception_failsafe(self):
        class Exploding:
            source_name = "boom"

            def fetch(self):
                raise RuntimeError("x")
        agg = MarketIntelligenceAggregator(
            providers=[Exploding()], clock=lambda: _NOW,
        )
        snap = agg.snapshot()
        assert snap["sources_unavailable"] == ["boom"]

    def test_gate_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "ENABLE_MARKET_INTELLIGENCE", raising=False,
        )
        assert market_intelligence_gate_enabled() is False
        monkeypatch.setenv("ENABLE_MARKET_INTELLIGENCE", "true")
        assert market_intelligence_gate_enabled() is True

    def test_snapshot_compatible_with_decision_trace(self):
        from crypto_trading_bot.decision_trace import (
            FinalDecision, build_trace_entry,
        )
        snap = self._agg().snapshot()
        entry = build_trace_entry(
            cycle_idx=0, final_decision=FinalDecision.HOLD,
            final_reason="t", mi_snapshot=snap,
        )
        d = entry.to_dict()
        assert d["market_intelligence_used"] is True
        assert d["funding_used"] is True
        assert d["news_used"] is False


class TestAIProviderSeam:

    def test_gate_off_returns_mock(self, monkeypatch):
        monkeypatch.delenv("ENABLE_AI_PROVIDER", raising=False)
        advisor, reason = resolve_ai_advisor()
        assert isinstance(advisor, MockAIAdvisor)
        assert reason == "mock_default"

    def test_gate_on_without_key_means_unavailable(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AI_PROVIDER", "true")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AI_API_KEY", "")
        advisor, reason = resolve_ai_advisor()
        assert advisor is None
        assert reason == "ai_unavailable_missing_key"

    def test_gate_on_with_key_resolves_real_anthropic_adapter(
        self, monkeypatch,
    ):
        # FASE 47: adapter real allowlisted implementado. Com provider
        # anthropic + key presente, resolve o AnthropicAIAdvisor (construir
        # NAO chama o SDK; chamada real so em evaluate, gated por custo).
        monkeypatch.setenv("ENABLE_AI_PROVIDER", "true")
        monkeypatch.setenv("AI_PROVIDER", "anthropic")
        monkeypatch.setenv("AI_API_KEY", "test-fixture-not-real")
        advisor, reason = resolve_ai_advisor()
        from crypto_trading_bot.ai_assistant.anthropic_advisor import (
            AnthropicAIAdvisor,
        )
        assert isinstance(advisor, AnthropicAIAdvisor)
        assert reason.startswith("anthropic_real:")

    def test_gate_on_real_openai_still_not_implemented(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AI_PROVIDER", "true")
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_API_KEY", "test-fixture-not-real")
        advisor, reason = resolve_ai_advisor()
        assert advisor is None
        assert "missing_config_q1" in reason

    def test_unknown_provider_rejected(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AI_PROVIDER", "true")
        monkeypatch.setenv("AI_PROVIDER", "skynet")
        advisor, reason = resolve_ai_advisor()
        assert advisor is None
        assert reason.startswith("ai_provider_unknown")

    def test_api_key_presence_only(self, monkeypatch):
        monkeypatch.setenv("AI_API_KEY", "fixture")
        assert api_key_present() is True
        monkeypatch.setenv("AI_API_KEY", "")
        assert api_key_present() is False

    def test_redact_text_removes_secrets_and_truncates(self):
        dirty = (
            "prompt with api_key: SECRET123 and bearer abcdef "
            "and sk-aaaaaaaaaaaaaaaa plus " + "x" * 500
        )
        clean = redact_text(dirty)
        assert "SECRET123" not in clean
        assert "sk-aaaa" not in clean
        assert "<redacted>" in clean
        assert clean.endswith("<truncated>")
        assert len(clean) <= 430

    def test_ai_not_used_reason_in_report_fields(self):
        from crypto_trading_bot.ai_assistant import AIDecisionSupport
        from crypto_trading_bot.operational_profile import (
            resolve_profile,
        )
        profile = resolve_profile("demo_validation", capital=5000.0)
        out = AIDecisionSupport(
            advisor=MockAIAdvisor(),
        ).evaluate_cycle(
            profile=profile,
            ai_context={"schema": "x"},
            cycle_idx=0,
        )
        fields = out.to_report_fields()
        assert fields["ai_enabled"] is False
        assert fields["ai_not_used_reason"] == \
            "ai_disabled_by_profile"


class TestDiscoveryWithNewGates:

    def test_mi_and_ai_gates_registered(self):
        from crypto_trading_bot.operational_options import (
            OperationalOptionsRegistry, run_option_discovery_audit,
        )
        report = run_option_discovery_audit(
            registry=OperationalOptionsRegistry(),
        )
        found = set(report.declared_env_gates_in_code)
        assert "ENABLE_MARKET_INTELLIGENCE" in found
        assert "ENABLE_AI_PROVIDER" in found
        assert report.env_gates_missing_in_registry == ()
