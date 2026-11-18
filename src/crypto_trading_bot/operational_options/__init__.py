"""
operational_options - Catalogo global de opcoes (FASE 36 Bloco H)
==================================================================
Toda capacidade operacional do bot (default ou nao) aparece aqui com
metadados UI-ready. Capacidade perigosa = disabled_by_default + gate +
profile + limites. discovery audita lacunas no bot inteiro.
"""

from crypto_trading_bot.operational_options.discovery import (
    KNOWN_INCONSISTENCIES,
    OptionDiscoveryAuditReport,
    run_option_discovery_audit,
)
from crypto_trading_bot.operational_options.option_model import (
    ExecutionImpact,
    OperationalOption,
    OptionRiskImpact,
    OptionStatus,
)
from crypto_trading_bot.operational_options.registry import (
    OperationalOptionsRegistry,
    build_default_registry,
)

__all__ = [
    "ExecutionImpact",
    "KNOWN_INCONSISTENCIES",
    "OperationalOption",
    "OperationalOptionsRegistry",
    "OptionDiscoveryAuditReport",
    "OptionRiskImpact",
    "OptionStatus",
    "build_default_registry",
    "run_option_discovery_audit",
]
