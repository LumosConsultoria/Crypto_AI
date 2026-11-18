"""
Anthropic AI Advisor (FASE 47) — adapter REAL allowlisted (AIAdvisorProtocol)
=============================================================================
Implementa o advisor real plugavel em `resolve_ai_advisor`. Caracteristicas:
- **transporte INJETAVEL** (`transport: prompt->json_text`): em TESTE injeta-se
  um fake (ZERO rede); o transporte real (Anthropic SDK) so e usado quando o
  provider esta habilitado + ha credencial (import tardio).
- **prompt + schema versionados**; resposta JSON -> AIAdvice (status PROCEED/
  caution/veto/manual_review; does_not_override invariante => so reduz/veta).
- **cache/replay deterministico** via AdviceStore (backtest/replay nao re-chama).
- **fail-safe**: erro/indisponivel NUNCA levanta; `last_state` expoe
  ok|replay|mock|unavailable|error p/ a politica de risco (modo E: falha NAO
  e favoravel silencioso — o orquestrador reduz/veta via context_risk).
- **secret** nunca em log/store (redaction no store).

NUNCA envia ordem; NUNCA decide trade; so parecer consultivo.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Mapping, Optional

from crypto_trading_bot.ai_assistant.advice_store import (
    AdviceRecord,
    AdviceStore,
    prompt_hash,
)
from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AISuggestedAction,
)

PROMPT_VERSION = "fase47_v2"
DEFAULT_MODEL = "claude-haiku-4-5"

# Transporte: recebe o prompt e devolve TEXTO JSON ou dict {text,usage}.
Transport = Callable[[str], Any]

# Precos Haiku (REFERENCIA, USD por milhao de tokens; configuravel).
HAIKU_INPUT_USD_PER_MTOK = 1.0
HAIKU_OUTPUT_USD_PER_MTOK = 5.0

# reason_codes PERMITIDOS (P4): a IA so pode usar estes; nada fora da lista,
# e nenhuma afirmacao sobre dados nao fornecidos (ex.: liquidacao/profundidade).
REASON_CODES = (
    "no_objection",
    "stop_too_tight", "stop_distance_ok",
    "funding_extreme_supports_fade", "funding_not_extreme",
    "oi_expansion_confirms", "oi_divergence", "oi_insufficient",
    "volatility_adverse", "volatility_ok",
    "rr_unfavorable", "rr_ok",
    "hyro_budget_tight",
    "polymarket_elevated_risk", "polymarket_contrary",
    "insufficient_data",
)

_SYSTEM = (
    "Voce e um assistente CONSULTIVO de risco para um bot BTCUSDT perpetual. "
    "NAO decide trades, NAO envia ordens, NUNCA aumenta risco: so confirmar "
    "(neutral/proceed), cautela (caution), revisao (manual_review) ou vetar "
    "(veto). Baseie-se SOMENTE nos campos fornecidos no CONTEXTO; NAO afirme "
    "nada sobre dados ausentes (ex.: NAO mencione liquidacao/liquidation_price "
    "nem profundidade/orderbook, pois nao foram fornecidos). Use APENAS estes "
    f"reason_codes: {list(REASON_CODES)}. Responda SOMENTE com JSON valido: "
    '{"status":"neutral|caution|veto|manual_review","confidence":0..1,'
    '"reason_codes":["..."],"reason":"<=200 chars, so dados fornecidos",'
    '"suggested_action":"proceed|wait|manual_review|research_required"}.'
)


def build_prompt(context: Mapping[str, Any], *,
                 version: str = PROMPT_VERSION) -> str:
    """Prompt versionado a partir do contexto SANITIZADO (so tecnico)."""
    safe = {k: v for k, v in dict(context or {}).items()
            if k not in ("secret", "api_key", "balance", "credentials")}
    return (f"[{version}] {_SYSTEM}\nCONTEXTO:\n"
            f"{json.dumps(safe, sort_keys=True, default=str)}")


def _extract_json(text: str) -> str:
    """Extrai o 1o objeto JSON do texto (tolera markdown fences/preambulo)."""
    if not text:
        return ""
    t = text.strip()
    # remove fences ```json ... ```
    if "```" in t:
        import re as _re
        m = _re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, _re.DOTALL)
        if m:
            return m.group(1)
    # 1o '{' ... ultimo '}' balanceado (heuristica simples)
    i = t.find("{")
    j = t.rfind("}")
    if i != -1 and j != -1 and j > i:
        return t[i:j + 1]
    return t


def _parse_advice(text: str):
    """Parseia JSON -> (AIAdvice, reason_codes). Invalido => NEUTRAL fail-safe.
    reason_codes filtrados ao conjunto permitido (P4)."""
    try:
        data = json.loads(_extract_json(text))
        status = AIAdviceStatus(str(data.get("status", "neutral")).lower())
        action = AISuggestedAction(
            str(data.get("suggested_action", "proceed")).lower())
        conf = min(1.0, max(0.0, float(data.get("confidence", 0.0) or 0.0)))
        raw_codes = data.get("reason_codes", []) or []
        codes = [c for c in raw_codes if c in REASON_CODES]
        advice = AIAdvice(status=status, confidence=conf,
                          reason=str(data.get("reason", "")),
                          warnings=tuple(data.get("warnings", ()) or ()),
                          suggested_action=action)
        return advice, codes
    except Exception:  # noqa: BLE001
        return (AIAdvice(status=AIAdviceStatus.NEUTRAL, confidence=0.0,
                         reason="resposta invalida (fail-safe neutral)",
                         suggested_action=AISuggestedAction.PROCEED),
                ["insufficient_data"])


def default_anthropic_transport(model: str = DEFAULT_MODEL) -> Transport:
    """Transporte REAL via HTTP (urllib; SEM dependencia nova). Le AI_API_KEY
    do ambiente (presence-only; nunca logado). So invocado quando habilitado;
    em teste use transporte fake (zero rede). POST autorizado a API Anthropic
    (apenas parecer consultivo; nunca ordem)."""
    def _call(prompt: str) -> str:
        import json as _json
        import os
        import urllib.request
        api_key = os.environ.get("AI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("AI_API_KEY ausente")
        body = _json.dumps({
            "model": model, "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            method="POST", headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            })
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            payload = _json.loads(resp.read().decode("utf-8"))
        text = ""
        for part in (payload.get("content") or []):
            if part.get("text"):
                text = part["text"]
                break
        usage = payload.get("usage") or {}
        return {"text": text,
                "usage": {"input_tokens": usage.get("input_tokens", 0),
                          "output_tokens": usage.get("output_tokens", 0)}}
    return _call


def usage_cost_usd(usage: Mapping[str, Any]) -> float:
    """Custo real (USD) a partir dos tokens de uso (precos Haiku ref.)."""
    i = float((usage or {}).get("input_tokens", 0) or 0)
    o = float((usage or {}).get("output_tokens", 0) or 0)
    return round(i / 1e6 * HAIKU_INPUT_USD_PER_MTOK
                 + o / 1e6 * HAIKU_OUTPUT_USD_PER_MTOK, 6)


class AnthropicAIAdvisor:
    """Advisor real (AIAdvisorProtocol). last_state expoe o estado p/ a
    politica de risco do orquestrador."""

    def __init__(self, *, model: str = DEFAULT_MODEL,
                 transport: Optional[Transport] = None,
                 store: Optional[AdviceStore] = None,
                 replay_only: bool = False,
                 prompt_version: str = PROMPT_VERSION,
                 is_mock: bool = False) -> None:
        self._model = model
        self._transport = transport
        self._store = store
        self._replay_only = replay_only
        self._prompt_version = prompt_version
        self._is_mock = is_mock
        self.last_state: str = "init"
        self.last_prompt_hash: Optional[str] = None
        self.last_reason_codes: list = []
        self.last_usage: dict = {"input_tokens": 0, "output_tokens": 0}
        self.last_cost_usd: float = 0.0
        self.last_from_cache: bool = False

    def _fail_safe(self, state: str, reason: str) -> AIAdvice:
        self.last_state = state
        self.last_reason_codes = ["insufficient_data"]
        self.last_usage = {"input_tokens": 0, "output_tokens": 0}
        self.last_cost_usd = 0.0
        self.last_from_cache = False
        return AIAdvice(status=AIAdviceStatus.NEUTRAL, confidence=0.0,
                        reason=reason,
                        suggested_action=AISuggestedAction.PROCEED)

    def evaluate_trade_context(self, context: Mapping[str, Any]) -> AIAdvice:
        prompt = build_prompt(context, version=self._prompt_version)
        ph = prompt_hash(prompt)
        self.last_prompt_hash = ph
        # 1) replay/cache
        if self._store is not None and self._store.has(ph):
            adv = self._store.cached(ph)
            if adv is not None:
                self.last_state = "replay"
                self.last_from_cache = True
                self.last_usage = {"input_tokens": 0, "output_tokens": 0}
                self.last_cost_usd = 0.0
                return adv
        # 2) sem cache e replay_only => indisponivel (NUNCA inventa favoravel)
        if self._replay_only:
            return self._fail_safe("unavailable",
                                   "replay_only sem cache (indisponivel)")
        # 3) chamada real (gated)
        if self._transport is None:
            return self._fail_safe("unavailable", "sem transporte de IA")
        try:
            t0 = time.time()
            raw = self._transport(prompt)
            latency = (time.time() - t0) * 1000.0
        except Exception as e:  # noqa: BLE001
            return self._fail_safe("error", f"falha transporte: "
                                   f"{type(e).__name__}")
        # transporte pode devolver str (texto) ou dict {text, usage}
        if isinstance(raw, Mapping):
            text = str(raw.get("text", ""))
            usage = dict(raw.get("usage") or {})
        else:
            text, usage = str(raw), {"input_tokens": 0, "output_tokens": 0}
        advice, codes = _parse_advice(text)
        self.last_state = "mock" if self._is_mock else "ok"
        self.last_reason_codes = codes
        self.last_from_cache = False
        self.last_usage = {"input_tokens": int(usage.get("input_tokens", 0)),
                           "output_tokens": int(usage.get("output_tokens", 0))}
        self.last_cost_usd = usage_cost_usd(self.last_usage)
        # 4) grava no store (versionado + sanitizado) com reason_codes + usage
        if self._store is not None:
            try:
                from datetime import datetime, timezone
                resp = advice.to_dict()
                resp["reason_codes"] = codes
                resp["usage"] = self.last_usage
                resp["cost_usd"] = self.last_cost_usd
                self._store.record(AdviceRecord(
                    ts=datetime.now(timezone.utc).isoformat(),
                    model=self._model, model_version=self._model,
                    prompt_hash=ph, inputs=dict(context or {}),
                    response=resp, latency_ms=round(latency, 2),
                    source=("mock" if self._is_mock else "real")))
            except Exception:  # noqa: BLE001
                pass
        return advice


__all__ = [
    "AnthropicAIAdvisor", "DEFAULT_MODEL", "PROMPT_VERSION", "REASON_CODES",
    "build_prompt", "default_anthropic_transport", "usage_cost_usd",
]
