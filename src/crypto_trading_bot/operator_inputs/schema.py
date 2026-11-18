"""
OperatorInputSchema (FASE 36 Bloco L)
======================================
Schema COMPLETO dos campos operacionais. Cobre V1-V12 do plano +
conta/estrategia/IA/MI/demo (item 12 da spec).

⚠️  NENHUM campo de risco tem default inventado: required sem
    safe_default => operador OBRIGADO a informar antes de execucao
    real. Campos com default seguro sao apenas os de postura
    conservadora OFF (bool) ja decididos pelo operador no plano.
"""

from __future__ import annotations

from typing import Tuple

from crypto_trading_bot.operator_inputs.input_model import (
    InputSource,
    InputType,
    OperatorInputRequirement,
    RiskImpact,
)

_OP = InputSource.OPERATOR_REQUIRED
_CONF = InputSource.OPERATOR_CONFIRMATION_REQUIRED


def _req(input_id, label, itype, category, **kw):
    defaults = dict(
        description=kw.pop("description", label),
        expected_source=kw.pop("source", _OP),
        required_for_demo=kw.pop("required", True),
        blocks_readiness_if_missing=kw.pop("blocks_readiness", True),
        blocks_execution_if_missing=kw.pop("blocks_execution", True),
        risk_impact=kw.pop("risk_impact", RiskImpact.HIGH),
    )
    return OperatorInputRequirement(
        input_id=input_id, label=label, input_type=itype,
        category=category, **defaults, **kw,
    )


def build_default_schema() -> Tuple[OperatorInputRequirement, ...]:
    """Schema padrao FASE 36. IDs estaveis (nao renomear)."""
    items = [
        # ================= V1 - Conta / perfil =================
        _req("session_capital_usd", "Capital operacional da sessao",
             InputType.DECIMAL, "account", min_value=1.0,
             risk_impact=RiskImpact.CRITICAL,
             used_by=("RiskEngine", "DemoEnduranceRunner")),
        _req("account_type", "Tipo de conta", InputType.ENUM,
             "account",
             enum_values=("personal", "prop_firm", "hyrotrader",
                          "challenge", "demo_validation"),
             risk_impact=RiskImpact.MEDIUM),
        _req("account_currency", "Moeda da conta", InputType.ENUM,
             "account", enum_values=("USDT", "USDC", "USD"),
             risk_impact=RiskImpact.LOW),
        _req("operational_timezone", "Timezone operacional",
             InputType.STRING, "account",
             risk_impact=RiskImpact.LOW, blocks_execution=False),
        _req("profile_name", "Perfil operacional", InputType.STRING,
             "account", source=InputSource.CONFIG_DERIVED,
             description="Resolvido via --profile (registry FASE 31)."),
        # ================= V2 - Limites de perda =================
        _req("max_risk_per_trade_pct", "Risco maximo por trade (%)",
             InputType.PERCENT, "risk", min_value=0.01, max_value=5.0,
             risk_impact=RiskImpact.CRITICAL,
             used_by=("RiskEngine",)),
        _req("max_daily_loss_pct", "Perda diaria maxima (%)",
             InputType.PERCENT, "risk", min_value=0.1, max_value=10.0,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_session_loss_pct", "Perda maxima por sessao (%)",
             InputType.PERCENT, "risk", min_value=0.1, max_value=10.0,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_total_loss_pct", "Perda total maxima (%)",
             InputType.PERCENT, "risk", min_value=0.5, max_value=50.0,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_drawdown_pct", "Drawdown maximo (%)",
             InputType.PERCENT, "risk", min_value=0.5, max_value=50.0,
             risk_impact=RiskImpact.CRITICAL),
        # ================= V3 - Exposicao =================
        _req("max_position_notional_usd",
             "Notional maximo por posicao (USD)", InputType.DECIMAL,
             "risk", min_value=1.0, risk_impact=RiskImpact.CRITICAL),
        _req("max_exposure_per_symbol",
             "Exposicao maxima por simbolo (USD)", InputType.DECIMAL,
             "risk", min_value=1.0, risk_impact=RiskImpact.HIGH),
        _req("max_total_exposure", "Exposicao total maxima (USD)",
             InputType.DECIMAL, "risk", min_value=1.0,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_leverage", "Alavancagem maxima", InputType.DECIMAL,
             "risk", min_value=1.0, max_value=10.0,
             risk_impact=RiskImpact.CRITICAL),
        # ================= V4 - Limites de atividade ==============
        _req("max_open_positions", "Posicoes abertas maximas",
             InputType.INT, "risk", min_value=1, max_value=5),
        _req("max_orders_per_session", "Ordens maximas por sessao",
             InputType.INT, "risk", min_value=1, max_value=10),
        _req("max_orders_per_day", "Ordens maximas por dia",
             InputType.INT, "risk", min_value=1, max_value=20),
        _req("max_consecutive_losses", "Perdas consecutivas maximas",
             InputType.INT, "risk", min_value=1, max_value=10),
        _req("cooldown_after_loss_minutes",
             "Cooldown apos perda (min)", InputType.DURATION, "risk",
             min_value=0, risk_impact=RiskImpact.MEDIUM,
             blocks_execution=False),
        _req("kill_switch_loss_limit_usd",
             "Kill switch: limite de perda (USD)", InputType.DECIMAL,
             "risk", min_value=1.0, risk_impact=RiskImpact.CRITICAL),
        # ============ V5-V8 - Position management ============
        _req("allow_multi_order_sequential",
             "Permitir multi-ordem sequencial", InputType.BOOL,
             "position_mgmt", needs_human_confirmation=True),
        _req("allow_scale_in", "Permitir scale-in", InputType.BOOL,
             "position_mgmt", can_have_default=True,
             safe_default=False, required=False,
             blocks_readiness=False, blocks_execution=False,
             needs_human_confirmation=True,
             risk_impact=RiskImpact.CRITICAL,
             description="Default OFF (postura aprovada no plano)."),
        _req("max_scale_ins_per_position",
             "Max scale-ins por posicao", InputType.INT,
             "position_mgmt", min_value=1, max_value=5,
             required=False, blocks_readiness=False,
             description="Obrigatorio APENAS se allow_scale_in=true.",
             risk_impact=RiskImpact.CRITICAL),
        _req("max_added_risk_per_scale_in_pct",
             "Risco maximo por entrada adicional (%)",
             InputType.PERCENT, "position_mgmt", min_value=0.01,
             max_value=5.0, required=False, blocks_readiness=False,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_aggregated_risk_per_position_pct",
             "Risco agregado maximo por posicao (%)",
             InputType.PERCENT, "position_mgmt", min_value=0.01,
             max_value=10.0, required=False, blocks_readiness=False,
             risk_impact=RiskImpact.CRITICAL),
        _req("min_entry_distance_pct",
             "Distancia minima entre entradas (%)",
             InputType.PERCENT, "position_mgmt", min_value=0.0,
             required=False, blocks_readiness=False),
        _req("min_time_between_scale_ins_minutes",
             "Tempo minimo entre scale-ins (min)",
             InputType.DURATION, "position_mgmt", min_value=0,
             required=False, blocks_readiness=False),
        _req("allow_move_sl_after_scale_in",
             "Permitir mover SL apos scale-in", InputType.ENUM,
             "position_mgmt",
             enum_values=("never", "only_in_favor", "recalculate"),
             required=False, blocks_readiness=False,
             needs_human_confirmation=True,
             risk_impact=RiskImpact.CRITICAL),
        _req("allow_partial_reduce", "Permitir reducao parcial",
             InputType.BOOL, "position_mgmt", can_have_default=True,
             safe_default=False, required=False,
             blocks_readiness=False, blocks_execution=False,
             needs_human_confirmation=True),
        _req("partial_reduce_max_pct",
             "Percentual maximo de reducao parcial (%)",
             InputType.PERCENT, "position_mgmt", min_value=1.0,
             max_value=100.0, required=False,
             blocks_readiness=False),
        _req("allow_reversal", "Permitir reversao controlada",
             InputType.ENUM, "position_mgmt",
             enum_values=("blocked", "manual_review_only"),
             can_have_default=True, safe_default="blocked",
             required=False, blocks_readiness=False,
             blocks_execution=False, needs_human_confirmation=True,
             risk_impact=RiskImpact.CRITICAL),
        _req("allow_auto_reduce_only_close",
             "Permitir reduceOnly close automatico (fallback)",
             InputType.BOOL, "position_mgmt",
             needs_human_confirmation=True),
        # ================= Estrategia =================
        _req("strategy_name", "Estrategia selecionada",
             InputType.STRING, "strategy",
             source=InputSource.CONFIG_DERIVED,
             description="Via --strategy; validada pelo perfil."),
        _req("strategy_params_accepted",
             "Parametros de estrategia aceitos pelo operador",
             InputType.BOOL, "strategy", needs_human_confirmation=True,
             risk_impact=RiskImpact.MEDIUM,
             description="Confirma que os parametros atuais (ou da "
                         "recomendacao aceita) sao os desejados."),
        _req("advisor_suggestion_profile",
             "Perfil de sugestao do advisor", InputType.ENUM,
             "strategy",
             enum_values=("conservador", "moderado", "arrojado"),
             required=False, blocks_readiness=False,
             blocks_execution=False, risk_impact=RiskImpact.LOW),
        # ================= IA / MI =================
        _req("ai_enabled", "IA consultiva habilitada",
             InputType.BOOL, "ai_mi", can_have_default=True,
             safe_default=False, required=False,
             blocks_readiness=False, blocks_execution=False,
             risk_impact=RiskImpact.LOW),
        _req("prediction_context_enabled",
             "Prediction/Market context habilitado",
             InputType.BOOL, "ai_mi", can_have_default=True,
             safe_default=False, required=False,
             blocks_readiness=False, blocks_execution=False,
             risk_impact=RiskImpact.LOW),
        # ================= Demo / execucao =================
        _req("demo_real_authorized",
             "Autorizacao para demo real", InputType.BOOL,
             "demo_execution", needs_human_confirmation=True,
             risk_impact=RiskImpact.CRITICAL),
        _req("max_real_orders_per_session",
             "Limite de ordens reais demo por sessao",
             InputType.INT, "demo_execution", min_value=1,
             max_value=3, risk_impact=RiskImpact.CRITICAL),
        _req("max_session_duration_minutes",
             "Duracao maxima da sessao (min)", InputType.DURATION,
             "demo_execution", min_value=1),
        _req("blueprint_ttl_max_seconds",
             "TTL maximo do blueprint (s)", InputType.DURATION,
             "demo_execution", min_value=10,
             risk_impact=RiskImpact.MEDIUM),
        _req("require_post_session_check",
             "Exigir post-session check", InputType.BOOL,
             "demo_execution", can_have_default=True,
             safe_default=True, required=False,
             blocks_readiness=False, blocks_execution=False),
    ]
    ids = [r.input_id for r in items]
    assert len(ids) == len(set(ids)), "input_id duplicado no schema"
    return tuple(items)


__all__ = ["build_default_schema"]
