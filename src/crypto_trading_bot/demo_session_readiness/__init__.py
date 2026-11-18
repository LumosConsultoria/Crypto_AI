"""
Demo Session Readiness — Camada de preparação gated (FASE 19)
================================================================
⚠️  DOES NOT EXECUTE. Esta camada agrega evidência local para preparar
    uma futura sessão Bybit Demo gated. NÃO envia ordem, NÃO chama rede,
    NÃO promove provider, NÃO altera o SessionRunner.
⚠️  is_ready_for_gated_demo=True é apenas SINAL — não autoriza ordem.
⚠️  Provider-agnostic. NÃO importa BybitClient, BybitDemoExecutor,
    BybitTestnetExecutor, DemoExecutionResult, httpx ou requests.

Exports:
    SafetyFlags,
    safety_flags_from_dict, safety_flags_from_result_like,
    ReadinessGate, ReadinessIssue, DemoSessionReadinessReport,
    DemoSessionReadinessCheck.
"""

from crypto_trading_bot.demo_session_readiness.flags_adapter import (
    SafetyFlags,
    safety_flags_from_dict,
    safety_flags_from_result_like,
)
from crypto_trading_bot.demo_session_readiness.readiness_check import (
    DemoSessionReadinessCheck,
    DemoSessionReadinessReport,
    ReadinessGate,
    ReadinessIssue,
)

__all__ = [
    # flags
    "SafetyFlags",
    "safety_flags_from_dict",
    "safety_flags_from_result_like",
    # readiness
    "ReadinessGate",
    "ReadinessIssue",
    "DemoSessionReadinessReport",
    "DemoSessionReadinessCheck",
]
