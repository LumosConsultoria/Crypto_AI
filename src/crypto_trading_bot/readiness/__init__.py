"""
readiness - Readiness supervisionado (FASE 35)
===============================================
Consolida evidencias (demo curta/longa, advisor, IA, prediction,
safety, P&L, flat-checks) ANTES de qualquer avanco futuro para
live/mainnet/challenge real.

⚠️  CONSULTIVO + OFFLINE: 'ready' NUNCA habilita live/mainnet.
"""

from crypto_trading_bot.readiness.readiness_report import (
    ReadinessReport,
    ReadinessVerdict,
)
from crypto_trading_bot.readiness.readiness_rules import (
    MAX_API_FAILURES_TOTAL,
    MAX_SAFETY_EVENTS,
    MIN_TOTAL_SESSIONS,
    ReadinessEvidence,
    evaluate_rules,
)
from crypto_trading_bot.readiness.supervised_readiness import (
    collect_evidence_from_reports_dir,
    evaluate_supervised_readiness,
    run_supervised_readiness_from_dir,
)

__all__ = [
    "MAX_API_FAILURES_TOTAL",
    "MAX_SAFETY_EVENTS",
    "MIN_TOTAL_SESSIONS",
    "ReadinessEvidence",
    "ReadinessReport",
    "ReadinessVerdict",
    "collect_evidence_from_reports_dir",
    "evaluate_rules",
    "evaluate_supervised_readiness",
    "run_supervised_readiness_from_dir",
]
