"""
AI Provider Adapter - seam para LLM real (FASE 36 Bloco C)
===========================================================
Q1/Q2 (provider e dados permitidos) AINDA SEM resposta do operador:
status missing_config no Options Registry. Este modulo entrega o seam
completo SEM provider real:

    - gate ENV proprio: ENABLE_AI_PROVIDER (default OFF);
    - AI_PROVIDER / AI_API_KEY: presence-only (valores NUNCA lidos
      em log/telemetry);
    - sem gate => MockAIAdvisor (offline deterministico);
    - gate ON sem API key => IA real INDISPONIVEL: pipeline segue SEM
      IA (ai_not_used: ai_unavailable_missing_key);
    - resposta invalida (nao-AIAdvice) ja e descartada pelo
      AIDecisionSupport; sugestao fora de escopo e estruturalmente
      impossivel (AIAdvice valida enums + does_not_override=True);
    - redaction: prompts/respostas NUNCA vao integralmente a
      telemetry — redact_text aplica denylist + truncamento.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Tuple

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvisorProtocol,
)
from crypto_trading_bot.ai_assistant.mock_ai_advisor import (
    MockAIAdvisor,
)


ENV_AI_PROVIDER_ENABLED = "ENABLE_AI_PROVIDER"
ENV_AI_PROVIDER_NAME = "AI_PROVIDER"
ENV_AI_API_KEY = "AI_API_KEY"          # presence-only; NUNCA logado

_SUPPORTED_FUTURE_PROVIDERS = ("mock", "anthropic", "openai",
                               "openrouter")

_REDACT_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|api[_-]?secret|bearer|token|"
               r"authorization|x-bapi|sign)\s*[:=]\s*\S+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
)
_REDACT_MAX_LEN = 400


def redact_text(text: str) -> str:
    """Redige segredos e trunca texto de prompt/resposta p/ telemetry."""
    if not isinstance(text, str):
        return ""
    out = text
    for pattern in _REDACT_PATTERNS:
        out = pattern.sub("<redacted>", out)
    if len(out) > _REDACT_MAX_LEN:
        out = out[:_REDACT_MAX_LEN] + "...<truncated>"
    return out


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in (
        "true", "1", "yes",
    )


def api_key_present() -> bool:
    """Presence-only: NUNCA le/loga o valor."""
    return bool(os.environ.get(ENV_AI_API_KEY, "").strip())


def resolve_ai_advisor() -> Tuple[Optional[AIAdvisorProtocol], str]:
    """Resolve o advisor efetivo.

    Returns:
        (advisor, reason):
            - gate OFF                 -> (MockAIAdvisor, "mock_default")
            - gate ON + provider mock  -> (MockAIAdvisor, "mock_explicit")
            - gate ON sem API key      -> (None, "ai_unavailable_missing_key")
            - gate ON + provider real  -> (None,
                "ai_provider_not_implemented_missing_config_q1")
              (Q1 pendente: nenhum adapter real existe nesta fase;
              o pipeline SEGUE sem IA — nunca bloqueia execucao.)
    """
    if not _env_truthy(ENV_AI_PROVIDER_ENABLED):
        return MockAIAdvisor(), "mock_default"
    provider = os.environ.get(
        ENV_AI_PROVIDER_NAME, "mock",
    ).strip().lower()
    if provider not in _SUPPORTED_FUTURE_PROVIDERS:
        return None, f"ai_provider_unknown:{provider[:24]}"
    if provider == "mock":
        return MockAIAdvisor(), "mock_explicit"
    if not api_key_present():
        return None, "ai_unavailable_missing_key"
    if provider == "anthropic":
        # FASE 47: adapter real allowlisted. Construir NAO chama o SDK; a
        # chamada real (transporte) so ocorre em evaluate_trade_context,
        # gated por ENABLE_AI_PROVIDER + AI_API_KEY (custo aprovado).
        from crypto_trading_bot.ai_assistant.anthropic_advisor import (
            AnthropicAIAdvisor,
            default_anthropic_transport,
        )
        model = (os.environ.get("AI_MODEL", "").strip()
                 or "claude-haiku-4-5")
        return (AnthropicAIAdvisor(
            model=model, transport=default_anthropic_transport(model)),
            f"anthropic_real:{model}")
    # openai/openrouter: adapter real ainda nao implementado nesta fase.
    return None, "ai_provider_not_implemented_missing_config_q1"


__all__ = [
    "ENV_AI_API_KEY",
    "ENV_AI_PROVIDER_ENABLED",
    "ENV_AI_PROVIDER_NAME",
    "api_key_present",
    "redact_text",
    "resolve_ai_advisor",
]
