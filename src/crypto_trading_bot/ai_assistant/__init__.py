"""
Módulo de IA Auxiliar
=======================
Módulo de inteligência artificial AUXILIAR — NÃO toma decisões de trading.

⚠️  REGRA FUNDAMENTAL E INVIOLÁVEL:
    A IA NUNCA decide compra, venda, stop loss, posição ou risco.
    Estas decisões são EXCLUSIVAMENTE das estratégias determinísticas
    e do RiskEngine.

    A IA é usada APENAS como camada de apoio analítico.

Funcionalidades planejadas (FASE 4+):

    news_analyzer.py:
        - Classificação e resumo de notícias de crypto
        - Análise de sentimento de mercado
        - Identificação de eventos relevantes (halvings, regulação, etc.)
        - Output: tags e scores de contexto (não sinais de trading)

    log_reviewer.py:
        - Revisão e resumo de logs de auditoria
        - Identificação de padrões nos logs
        - Sugestões de investigação para o operador humano

    context_summarizer.py:
        - Resumo do contexto atual de mercado para análise humana
        - Geração de relatórios periódicos

    polymarket_client.py:
        - Consulta de probabilidades de eventos em Polymarket
        - Uso como dado de contexto APENAS (não como sinal)

FASE 32 — AI Decision Support Engine (consultivo, offline-first):
    advisor_protocol.py      AIAdvisorProtocol + AIAdvice
    decision_support.py      AIDecisionSupport (fusao com perfil/gates)
    context_builder.py       build_ai_context + sanitize_for_ai
    market_explainer.py      explicacoes deterministicas (HOLD etc.)
    risk_commentary.py       comentarios deterministicos de risco
    mock_ai_advisor.py       MockAIAdvisor (testes/offline)
    prediction_context_adapter.py  adapta FASE 34 -> payload da IA
"""

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AIAdvisorProtocol,
    AISuggestedAction,
)
from crypto_trading_bot.ai_assistant.context_builder import (
    build_ai_context,
    sanitize_for_ai,
)
from crypto_trading_bot.ai_assistant.decision_support import (
    AIDecisionOutcome,
    AIDecisionSupport,
    ENV_AI_MANUAL_REVIEW,
)
from crypto_trading_bot.ai_assistant.market_explainer import (
    compare_long_short,
    explain_hold,
    summarize_signal,
)
from crypto_trading_bot.ai_assistant.mock_ai_advisor import MockAIAdvisor
from crypto_trading_bot.ai_assistant.prediction_context_adapter import (
    adapt_prediction_context_for_ai,
)
from crypto_trading_bot.ai_assistant.provider_adapter import (
    ENV_AI_API_KEY,
    ENV_AI_PROVIDER_ENABLED,
    ENV_AI_PROVIDER_NAME,
    api_key_present,
    redact_text,
    resolve_ai_advisor,
)
from crypto_trading_bot.ai_assistant.risk_commentary import (
    build_risk_commentary,
)

__all__ = [
    "AIAdvice",
    "AIAdviceStatus",
    "AIAdvisorProtocol",
    "AIDecisionOutcome",
    "AIDecisionSupport",
    "AISuggestedAction",
    "ENV_AI_MANUAL_REVIEW",
    "ENV_AI_API_KEY",
    "ENV_AI_PROVIDER_ENABLED",
    "ENV_AI_PROVIDER_NAME",
    "MockAIAdvisor",
    "adapt_prediction_context_for_ai",
    "api_key_present",
    "redact_text",
    "resolve_ai_advisor",
    "build_ai_context",
    "build_risk_commentary",
    "compare_long_short",
    "explain_hold",
    "sanitize_for_ai",
    "summarize_signal",
]
