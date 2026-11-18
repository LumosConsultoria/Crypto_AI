"""
Demo Session Execution Gate — single-shot triple-locked (FASE 20)
=====================================================================
⚠️  DOES NOT EXECUTE BY DEFAULT. dry_run=True. Execução real exige
    triple-lock humano completo. Sessão demo curta = no máximo 1 ordem.
⚠️  Provider-agnostic. NÃO importa BybitClient, BybitDemoExecutor,
    BybitTestnetExecutor, httpx, requests, SessionRunner.
⚠️  Executor é INJETADO via DemoExecutorProtocol.
⚠️  bybit_demo_linear continua OPT_IN. SessionRunner permanece paper-only.
⚠️  is_planned_for_execution=False por default. RECOMMENDED_NEXT_ACTION
    default = RETURN_TO_PAPER.

Exports:
    BlueprintSide, SignalBlueprint,
    DemoSessionPlan, DemoSessionPlanRejected, build_demo_session_plan,
    DemoSessionOutcome, DemoSessionRejected, RecommendedNextAction,
    DemoExecutorProtocol, execute_demo_session_gated.
"""

from crypto_trading_bot.demo_session_execution.api_blueprint import (
    DEFAULT_MAX_SPREAD_PCT,
    DEFAULT_TAKE_PROFIT_RR,
    DEFAULT_TTL_SECONDS,
    DemoApiBlueprint,
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
    load_from_json,
    serialize_to_json,
    to_signal_blueprint,
)
from crypto_trading_bot.demo_session_execution.gate import (
    DemoExecutorProtocol,
    execute_demo_session_gated,
)
from crypto_trading_bot.demo_session_execution.outcome import (
    DemoSessionOutcome,
    DemoSessionRejected,
    RecommendedNextAction,
)
from crypto_trading_bot.demo_session_execution.plan import (
    BlueprintSide,
    DemoSessionPlan,
    DemoSessionPlanRejected,
    SignalBlueprint,
    build_demo_session_plan,
)

__all__ = [
    # plan
    "BlueprintSide",
    "SignalBlueprint",
    "DemoSessionPlan",
    "DemoSessionPlanRejected",
    "build_demo_session_plan",
    # outcome
    "DemoSessionOutcome",
    "DemoSessionRejected",
    "RecommendedNextAction",
    # gate
    "DemoExecutorProtocol",
    "execute_demo_session_gated",
    # api_blueprint (FASE 22)
    "DemoApiBlueprint",
    "DemoApiBlueprintRejected",
    "build_demo_api_blueprint",
    "serialize_to_json",
    "load_from_json",
    "to_signal_blueprint",
    "DEFAULT_TTL_SECONDS",
    "DEFAULT_MAX_SPREAD_PCT",
    "DEFAULT_TAKE_PROFIT_RR",
]
