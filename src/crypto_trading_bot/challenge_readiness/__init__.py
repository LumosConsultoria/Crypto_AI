"""
Challenge Readiness + Endurance Progressivo (FASE 23)
========================================================
⚠️  Paper-only nesta fase. DEMO_* eh planned-only.
⚠️  Provider-agnostic. NUNCA importa BybitClient, BybitDemoExecutor,
    BybitTestnetExecutor, DemoExecutionResult, httpx, requests.
⚠️  Challenge target eh KPI; NUNCA bloqueia readiness/endurance por
    lucro insuficiente.
⚠️  Reusa SessionRunner sem alterar.

Exports:
    Stages:        ChallengeEnduranceStage, STAGE_ORDER,
                   get_stage_definition, is_paper_stage,
                   is_demo_planned_stage, next_recommended_stage.
    Readiness:     ChallengeReadinessConfig, ChallengeReadinessReport,
                   ChallengeReadinessStatus, ChallengeReadinessBlocker,
                   build_challenge_readiness_report.
    Endurance:     ChallengeEnduranceRunner, ChallengeEnduranceResult,
                   StageNotExecutableInThisPhase,
                   EnduranceReadinessRejected.
"""

from crypto_trading_bot.challenge_readiness.endurance_runner import (
    ChallengeEnduranceRunner,
    EnduranceReadinessRejected,
    StageNotExecutableInThisPhase,
)
from crypto_trading_bot.challenge_readiness.readiness import (
    ChallengeReadinessBlocker,
    ChallengeReadinessConfig,
    ChallengeReadinessReport,
    ChallengeReadinessStatus,
    build_challenge_readiness_report,
)
from crypto_trading_bot.challenge_readiness.result import (
    ChallengeEnduranceResult,
)
from crypto_trading_bot.challenge_readiness.stages import (
    STAGE_ORDER,
    ChallengeEnduranceStage,
    get_stage_definition,
    is_demo_planned_stage,
    is_paper_stage,
    next_recommended_stage,
)

__all__ = [
    # stages
    "ChallengeEnduranceStage",
    "STAGE_ORDER",
    "get_stage_definition",
    "is_paper_stage",
    "is_demo_planned_stage",
    "next_recommended_stage",
    # readiness
    "ChallengeReadinessConfig",
    "ChallengeReadinessReport",
    "ChallengeReadinessStatus",
    "ChallengeReadinessBlocker",
    "build_challenge_readiness_report",
    # endurance
    "ChallengeEnduranceRunner",
    "ChallengeEnduranceResult",
    "StageNotExecutableInThisPhase",
    "EnduranceReadinessRejected",
]
