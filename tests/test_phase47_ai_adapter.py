"""
FASE 47 — IA adapter real (AnthropicAIAdvisor) + AdviceStore.
100% OFFLINE: transporte SEMPRE fake/mockado (ZERO rede); IA real nunca em
teste. AIAdvice so confirma/reduz/veta (does_not_override invariante). Cache/
replay deterministico. Fail-safe (erro/indisponivel nunca levanta; last_state
distingue ok/replay/unavailable/error). Sem secret no store.
"""

from __future__ import annotations

import json

import pytest

from crypto_trading_bot.ai_assistant.advice_store import (
    AdviceRecord,
    AdviceStore,
    prompt_hash,
)
from crypto_trading_bot.ai_assistant.anthropic_advisor import (
    AnthropicAIAdvisor,
    build_prompt,
)

_CTX = {"symbol": "BTCUSDT", "rsi": 72.0, "funding_pctile": 0.95}
_GOOD = json.dumps({"status": "caution", "confidence": 0.6,
                    "reason": "funding extremo", "suggested_action": "wait"})


class TestBuildPrompt:

    def test_excludes_secrets(self):
        p = build_prompt({"symbol": "BTCUSDT", "api_key": "SECRET",
                          "balance": 9999})
        assert "SECRET" not in p and "9999" not in p
        assert "fase47_v" in p


class TestAnthropicAdvisorFakeTransport:

    def test_valid_response_parsed(self):
        adv = AnthropicAIAdvisor(transport=lambda _p: _GOOD)
        out = adv.evaluate_trade_context(_CTX)
        assert out.status.value == "caution"
        assert out.does_not_override_risk_engine is True
        assert adv.last_state == "ok"

    def test_invalid_json_is_failsafe_neutral(self):
        adv = AnthropicAIAdvisor(transport=lambda _p: "not json")
        out = adv.evaluate_trade_context(_CTX)
        assert out.status.value == "neutral"
        assert out.confidence == 0.0

    def test_transport_error_is_failsafe_error_state(self):
        def _boom(_p):
            raise RuntimeError("network down")
        adv = AnthropicAIAdvisor(transport=_boom)
        out = adv.evaluate_trade_context(_CTX)
        assert adv.last_state == "error"
        assert out.status.value == "neutral"   # nunca levanta

    def test_no_transport_is_unavailable(self):
        adv = AnthropicAIAdvisor(transport=None)
        adv.evaluate_trade_context(_CTX)
        assert adv.last_state == "unavailable"

    def test_replay_uses_cache_not_transport(self, tmp_path):
        store = AdviceStore(str(tmp_path / "advice.json"))
        calls = {"n": 0}

        def _t(_p):
            calls["n"] += 1
            return _GOOD
        adv = AnthropicAIAdvisor(transport=_t, store=store)
        adv.evaluate_trade_context(_CTX)
        assert adv.last_state == "ok" and calls["n"] == 1
        # 2a chamada (mesmo contexto) => replay do cache, sem transporte
        adv2 = AnthropicAIAdvisor(transport=_t, store=store)
        out = adv2.evaluate_trade_context(_CTX)
        assert adv2.last_state == "replay" and calls["n"] == 1
        assert out.status.value == "caution"

    def test_replay_only_without_cache_is_unavailable(self):
        adv = AnthropicAIAdvisor(transport=lambda _p: _GOOD,
                                 replay_only=True)
        adv.evaluate_trade_context(_CTX)
        assert adv.last_state == "unavailable"   # nao chama, nao inventa


class TestAdviceStore:

    def test_record_and_replay_roundtrip(self, tmp_path):
        store = AdviceStore(str(tmp_path / "s.json"))
        ph = prompt_hash("p")
        store.record(AdviceRecord(
            ts="2026-01-01T00:00:00+00:00", model="claude-haiku-4-5",
            model_version="claude-haiku-4-5", prompt_hash=ph,
            inputs={"symbol": "BTCUSDT"},
            response={"status": "veto", "confidence": 0.9, "reason": "x",
                      "suggested_action": "manual_review"}))
        assert store.has(ph)
        adv = store.cached(ph)
        assert adv.status.value == "veto"

    def test_secret_is_scrubbed_from_store(self, tmp_path):
        # redaction limpa o secret ANTES de gravar => nunca persiste no store
        p = tmp_path / "s.json"
        store = AdviceStore(str(p))
        store.record(AdviceRecord(
            ts="t", model="m", model_version="m", prompt_hash="h",
            inputs={"note": "api_key=sk-ABCDEFGH12345678"},
            response={"status": "neutral", "confidence": 0.0,
                      "reason": "r", "suggested_action": "proceed"}))
        content = p.read_text(encoding="utf-8")
        assert "sk-ABCDEFGH12345678" not in content
        assert "<redacted>" in content

    def test_traversal_rejected(self):
        with pytest.raises(ValueError):
            AdviceStore("../evil.json")
