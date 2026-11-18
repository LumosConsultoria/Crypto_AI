"""
decision_trace - Explicabilidade por decisao (FASE 36 Bloco A)
===============================================================
Registro auditavel + narrativa humana de CADA decisao do bot.
O trace NUNCA decide; apenas registra o que cada camada decidiu.
"""

from crypto_trading_bot.decision_trace.human_renderer import (
    render_trace_entries,
    render_trace_entry,
)
from crypto_trading_bot.decision_trace.trace_builder import (
    build_trace_entry,
)
from crypto_trading_bot.decision_trace.trace_model import (
    DecisionTraceEntry,
    FinalDecision,
)

__all__ = [
    "DecisionTraceEntry",
    "FinalDecision",
    "build_trace_entry",
    "render_trace_entries",
    "render_trace_entry",
]
