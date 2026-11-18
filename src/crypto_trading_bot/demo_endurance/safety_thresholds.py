"""
Demo30Min safety thresholds (FASE 26)
=======================================
Constantes auditaveis para uma sessao demo controlada de 30 min.
Sem hardcode operacional de capital/leverage/sizing aqui — apenas
limites de SESSAO/CONTAGEM/TEMPO que protegem contra overtrade.

⚠️  Estas constantes sao TEMPLATES validaveis; podem ser overrideadas
    via campos do profile/RiskConfig do operador. Nao sao tuning.

⚠️  ZERO importacao de rede / API / BybitClient / BybitDemoExecutor /
    BybitDemoPreflight / .env.
"""

from __future__ import annotations


# Janela maxima de sessao demo nesta fase.
DEMO_30_MIN_MAX_SESSION_MINUTES: int = 30

# Numero maximo absoluto de ordens permitidas em UMA sessao de 30 min
# nesta fase. Mesmo que o profile permita mais, esta fase fixa o teto.
DEMO_30_MIN_MAX_ORDERS_HARD_CAP: int = 1

# Posicoes simultaneas: sempre 1 nesta fase. Nao ha DCA/martingale.
DEMO_30_MIN_MAX_OPEN_POSITIONS: int = 1

# Default p/ apply_demo_real: SEMPRE False nesta fase. FASE 27 abrira
# o caminho com aprovacao explicita do operador.
DEMO_30_MIN_APPLY_DEMO_REAL_DEFAULT: bool = False

# TTL de blueprint planejado (segundos). Valor curto para evitar uso
# de dados estagnados em decisao operacional futura.
DEMO_30_MIN_PLANNED_BLUEPRINT_TTL_SECONDS: int = 300

# Schema version dos artefatos serializaveis (plan/outcome).
DEMO_30_MIN_SCHEMA_VERSION: int = 1

# Provider id esperado nesta fase (planejamento; nao usado em execucao
# real nesta fase).
DEMO_30_MIN_PLANNED_PROVIDER_ID: str = "bybit_demo_linear"

# Environment esperado: apenas demo.
DEMO_30_MIN_PLANNED_ENVIRONMENT: str = "demo"

# Endpoint type esperado em blueprint planejado.
DEMO_30_MIN_PLANNED_ENDPOINT_TYPE: str = "api-demo.bybit.com"
