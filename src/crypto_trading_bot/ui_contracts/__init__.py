"""
ui_contracts - Contratos de dados para UI futura (FASE 36 Bloco G)
===================================================================
Snapshots JSON-ready produzidos JA nesta fase. UI visual fora do
escopo; contrato dentro.
"""

from crypto_trading_bot.ui_contracts.snapshots import (
    build_decision_trace_snapshot,
    build_operator_dashboard_snapshot,
    build_position_management_snapshot,
    build_readiness_snapshot,
    build_session_snapshot,
)
from crypto_trading_bot.ui_contracts.view_models import (
    FieldSpec,
    build_backtest_run_view_model,
    build_historical_data_view_model,
    build_operator_input_view_model,
)

__all__ = [
    "FieldSpec",
    "build_backtest_run_view_model",
    "build_decision_trace_snapshot",
    "build_historical_data_view_model",
    "build_operator_dashboard_snapshot",
    "build_operator_input_view_model",
    "build_position_management_snapshot",
    "build_readiness_snapshot",
    "build_session_snapshot",
]
