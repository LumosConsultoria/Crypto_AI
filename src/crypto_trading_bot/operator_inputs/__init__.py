"""
operator_inputs - Campos obrigatorios do operador (FASE 36 Bloco L)
====================================================================
O bot NUNCA inventa limite/valor operacional. O que ele nao consegue
obter via API/config/calculo seguro vira requisito do operador;
ausente => bloqueia readiness/execucao real.
"""

from crypto_trading_bot.operator_inputs.input_model import (
    InputSource,
    InputStatus,
    InputType,
    MissingOperatorInput,
    OperatorInputRequirement,
    OperatorInputValue,
    RiskImpact,
)
from crypto_trading_bot.operator_inputs.schema import (
    build_default_schema,
)
from crypto_trading_bot.operator_inputs.store import (
    OperatorInputStore,
    OperatorInputValidationResult,
    build_required_inputs_for_demo_report,
    get_effective_value,
    validate_operator_inputs,
)

__all__ = [
    "InputSource",
    "InputStatus",
    "InputType",
    "MissingOperatorInput",
    "OperatorInputRequirement",
    "OperatorInputStore",
    "OperatorInputValidationResult",
    "OperatorInputValue",
    "RiskImpact",
    "build_default_schema",
    "build_required_inputs_for_demo_report",
    "get_effective_value",
    "validate_operator_inputs",
]
