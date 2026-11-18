"""
OperationalOptionsRegistry (FASE 36 Bloco H)
=============================================
Catalogo GLOBAL de opcoes/capacidades do bot inteiro (nao apenas
FASES 30-35). Toda capacidade arquitetural aparece aqui — mesmo
bloqueada, missing_config ou missing_limits.

⚠️  Offline. Seed deterministico; discovery.py audita lacunas.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from crypto_trading_bot.operational_options.option_model import (
    ExecutionImpact as EI,
    OperationalOption,
    OptionRiskImpact as RI,
    OptionStatus as ST,
)

_DEMO_PROVIDERS = ("paper", "bybit_demo_linear")


def _opt(option_id, label, category, **kw) -> OperationalOption:
    return OperationalOption(
        option_id=option_id, label=label,
        description=kw.pop("description", label),
        category=category,
        source_location=kw.pop("source", "registry_seed"),
        **kw,
    )


def build_default_registry() -> Tuple[OperationalOption, ...]:
    """Seed completo do inventario conhecido. IDs estaveis."""
    options = [
        # ===================== MODOS DE EXECUCAO =====================
        _opt("paper_trading", "Paper trading (default)", "modes",
             source="config/settings.py:TRADING_MODE",
             default_enabled=True, selectable_by_user=True,
             risk_impact=RI.NONE, execution_impact=EI.SIMULATION_ONLY,
             supported_modes=("paper",), status=ST.AVAILABLE,
             ui_group="modes", ui_order=1),
        _opt("backtest_research", "Backtest/research offline", "modes",
             source="backtesting/backtest_engine.py",
             default_enabled=True, selectable_by_user=True,
             risk_impact=RI.NONE, execution_impact=EI.SIMULATION_ONLY,
             status=ST.AVAILABLE, ui_group="modes", ui_order=2),
        _opt("wired_dry_run", "Demo endurance wired dry-run", "modes",
             source="demo_endurance/endurance_runner.py",
             selectable_by_user=True, risk_impact=RI.LOW,
             execution_impact=EI.SIMULATION_ONLY,
             supported_modes=("demo",),
             supported_providers=_DEMO_PROVIDERS,
             status=ST.AVAILABLE, ui_group="modes", ui_order=3),
        _opt("observation_mode", "Modo observacao dry-run", "modes",
             source="scripts/run_demo_endurance.py:"
                    "--continue-after-would-order",
             selectable_by_user=True, risk_impact=RI.LOW,
             execution_impact=EI.SIMULATION_ONLY,
             conflicts_with=("demo_real_multi_order",),
             status=ST.AVAILABLE, ui_group="modes", ui_order=4),
        _opt("testnet_execution", "Execucao testnet (Bybit)", "modes",
             source="config/settings.py:ENABLE_TESTNET_EXECUTION",
             requires_gate=True,
             required_gate_name="ENABLE_TESTNET_EXECUTION",
             risk_impact=RI.MEDIUM, execution_impact=EI.DEMO_POSSIBLE,
             supported_modes=("testnet",),
             status=ST.DISABLED_BY_DEFAULT, ui_group="modes",
             ui_order=5),
        _opt("live_mainnet", "Execucao live/mainnet", "modes",
             source="core/mode_guard.py:assert_live_allowed",
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             status=ST.BLOCKED,
             blocked_reason=(
                 "Fora de escopo nesta macrofase. ModeGuard + "
                 "assert_live_allowed bloqueiam."
             ),
             ui_group="modes", ui_order=99),
        # ===================== EXECUCAO DEMO REAL =====================
        _opt("demo_execution_enabled", "Execucao demo habilitada",
             "demo_gates",
             source="config/settings.py:ENABLE_DEMO_EXECUTION",
             requires_gate=True,
             required_gate_name="ENABLE_DEMO_EXECUTION",
             risk_impact=RI.HIGH, execution_impact=EI.DEMO_POSSIBLE,
             supported_modes=("demo",), ui_group="demo", ui_order=10),
        _opt("bybit_use_demo", "Endpoint api-demo.bybit.com",
             "demo_gates", source="gates_phase29.py:ENV_USE_DEMO",
             requires_gate=True, required_gate_name="BYBIT_USE_DEMO",
             risk_impact=RI.HIGH, execution_impact=EI.DEMO_POSSIBLE,
             ui_group="demo", ui_order=11),
        _opt("real_runner_deployed", "Runner real habilitado (FASE 28)",
             "demo_gates",
             source="run_demo_30_min_endurance.py",
             requires_gate=True,
             required_gate_name="DEMO_30_MIN_REAL_RUNNER_DEPLOYED",
             risk_impact=RI.HIGH, execution_impact=EI.DEMO_POSSIBLE,
             ui_group="demo", ui_order=12),
        _opt("phase29_real_order", "1a ordem real demo (FASE 29)",
             "demo_gates",
             source="gates_phase29.py:ENV_REAL_ORDER_ENABLED",
             requires_gate=True,
             required_gate_name="DEMO_30_MIN_REAL_ORDER_PHASE29_ENABLED",
             requires_operator_confirmation=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             supported_providers=("bybit_demo_linear",),
             ui_group="demo", ui_order=13),
        _opt("reduce_only_close", "ReduceOnly close gated (FASE 29)",
             "demo_gates",
             source="gates_phase29.py:ENV_REDUCE_ONLY_CLOSE_ENABLED",
             requires_gate=True,
             required_gate_name=(
                 "DEMO_30_MIN_REDUCE_ONLY_CLOSE_PHASE29_ENABLED"
             ),
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             ui_group="demo", ui_order=14),
        _opt("short_demo", "SELL/short real demo", "demo_gates",
             source="gates_phase29.py:ENV_ALLOW_SHORT",
             requires_gate=True,
             required_gate_name=(
                 "DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED"
             ),
             requires_profile_permission=True,
             required_profile_field="allow_short_demo",
             requires_operator_confirmation=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             ui_group="demo", ui_order=15),
        _opt("multi_order_session", "Multi-ordem por sessao (gate)",
             "demo_gates",
             source="endurance_runner.py:ENV_ALLOW_MULTI_ORDER",
             requires_gate=True,
             required_gate_name="DEMO_ALLOW_MULTI_ORDER_PER_SESSION",
             requires_profile_permission=True,
             required_profile_field="allow_multi_order_demo",
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             ui_group="demo", ui_order=16),
        _opt("demo_real_multi_order",
             "Multi-ordem real demo SEQUENCIAL (FASE 30.2)",
             "demo_gates",
             source="gates_phase30.py:ENV_REAL_MULTI_ORDER",
             requires_gate=True,
             required_gate_name=(
                 "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED"
             ),
             requires_profile_permission=True,
             required_profile_field="allow_multi_order_demo",
             requires_operator_confirmation=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             depends_on=("demo_execution_enabled", "bybit_use_demo",
                         "real_runner_deployed",
                         "multi_order_session"),
             conflicts_with=("observation_mode",),
             missing_information=(
                 "operator_inputs:V1-V4 (capital/risco/limites)",
             ),
             ui_group="demo", ui_order=17),
        # ===================== POSITION MANAGEMENT =====================
        _opt("multi_order_sequential",
             "Multi-ordem sequencial (1 posicao por vez)",
             "position_mgmt",
             source="endurance_real_execution.py",
             requires_gate=True,
             required_gate_name=(
                 "DEMO_ENDURANCE_REAL_MULTI_ORDER_ENABLED"
             ),
             requires_profile_permission=True,
             required_profile_field="allow_multi_order_demo",
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             ui_group="position", ui_order=20),
        _opt("scale_in", "Scale-in / aumento de posicao",
             "position_mgmt",
             source="position_management/ (FASE 36 Bloco E2)",
             requires_gate=True,
             required_gate_name="DEMO_ALLOW_SCALE_IN_ENABLED",
             requires_profile_permission=True,
             required_profile_field="allow_scale_in",
             requires_operator_confirmation=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             status=ST.MISSING_LIMITS,
             missing_information=(
                 "V5: max_scale_ins_per_position",
                 "V5: max_aggregated_risk_per_position",
                 "V5: max_added_risk_per_scale_in",
                 "V5: distancia/tempo minimos entre entradas",
                 "V6: politica de SL pos scale-in",
             ),
             description=(
                 "Capacidade arquitetural presente; DESABILITADA por "
                 "default; exige profile + gate + limites V5-V6 + "
                 "risco agregado revalidado no RiskEngine + "
                 "confirmacao humana."
             ),
             ui_group="position", ui_order=21),
        _opt("partial_reduce", "Reducao parcial (reduceOnly)",
             "position_mgmt",
             source="position_management/ (FASE 36 Bloco E2)",
             requires_gate=True,
             required_gate_name="DEMO_ALLOW_PARTIAL_REDUCE_ENABLED",
             requires_profile_permission=True,
             required_profile_field="allow_partial_reduce",
             requires_operator_confirmation=True,
             risk_impact=RI.HIGH,
             execution_impact=EI.REAL_POSSIBLE,
             status=ST.MISSING_LIMITS,
             missing_information=(
                 "V7: percentual maximo de reducao parcial",
             ),
             ui_group="position", ui_order=22),
        _opt("controlled_reversal", "Reversao controlada",
             "position_mgmt",
             source="position_management/ (FASE 36 Bloco E2)",
             requires_gate=True,
             required_gate_name="DEMO_ALLOW_REVERSAL_ENABLED",
             requires_profile_permission=True,
             required_profile_field="allow_reversal",
             requires_operator_confirmation=True,
             requires_manual_review=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             status=ST.MISSING_LIMITS,
             missing_information=(
                 "V8: politica (manual review only nesta fase)",
             ),
             ui_group="position", ui_order=23),
        # ===================== IA / MARKET INTELLIGENCE ================
        _opt("ai_assistance", "IA consultiva (mock offline)",
             "ai_mi", source="ai_assistant/decision_support.py",
             requires_profile_permission=True,
             required_profile_field="allow_ai_assistance",
             selectable_by_user=True, risk_impact=RI.LOW,
             execution_impact=EI.NONE,
             status=ST.AVAILABLE, ui_group="ai", ui_order=30),
        _opt("ai_veto", "Soft veto consultivo da IA", "ai_mi",
             source="ai_assistant/decision_support.py",
             requires_profile_permission=True,
             required_profile_field="allow_ai_veto",
             risk_impact=RI.LOW, execution_impact=EI.NONE,
             status=ST.AVAILABLE, ui_group="ai", ui_order=31),
        _opt("ai_manual_review", "IA pode pedir manual review",
             "ai_mi",
             source="decision_support.py:ENV_AI_MANUAL_REVIEW",
             requires_gate=True,
             required_gate_name="DEMO_ALLOW_AI_MANUAL_REVIEW",
             requires_profile_permission=True,
             required_profile_field="allow_ai_veto",
             risk_impact=RI.LOW, execution_impact=EI.NONE,
             ui_group="ai", ui_order=32),
        _opt("ai_real_provider", "IA com provider real (LLM)",
             "ai_mi", source="ai_assistant/ (FASE 36 Bloco C)",
             requires_gate=True,
             required_gate_name="ENABLE_AI_PROVIDER",
             risk_impact=RI.MEDIUM, execution_impact=EI.NONE,
             status=ST.MISSING_CONFIG,
             missing_information=(
                 "Q1: provider (mock/OpenAI/Anthropic/OpenRouter)",
                 "Q2: dados permitidos no contexto",
                 "API key (presence-only; nunca em log)",
             ),
             ui_group="ai", ui_order=33),
        _opt("prediction_context", "Prediction markets read-only",
             "ai_mi",
             source="endurance_runner.py:ENV_PREDICTION_CONTEXT",
             requires_gate=True,
             required_gate_name="ENABLE_PREDICTION_MARKET_CONTEXT",
             requires_profile_permission=True,
             required_profile_field=(
                 "allow_prediction_market_context"
             ),
             risk_impact=RI.LOW, execution_impact=EI.NONE,
             ui_group="ai", ui_order=34),
        _opt("prediction_execution", "Execucao em prediction markets",
             "ai_mi",
             source="prediction_markets/execution_protocol.py",
             risk_impact=RI.CRITICAL,
             execution_impact=EI.REAL_POSSIBLE,
             status=ST.BLOCKED,
             blocked_reason=(
                 "Seam permanentemente bloqueado nesta macrofase "
                 "(PredictionExecutionBlocked)."
             ),
             ui_group="ai", ui_order=35),
        _opt("market_intelligence", "Market Intelligence agregada",
             "ai_mi",
             source="market_intelligence/ (FASE 36 Bloco D)",
             requires_gate=True,
             required_gate_name="ENABLE_MARKET_INTELLIGENCE",
             risk_impact=RI.LOW, execution_impact=EI.NONE,
             status=ST.MISSING_CONFIG,
             missing_information=(
                 "Q3: fontes com transporte real vs mock",
                 "Q4: adapter de noticias",
             ),
             ui_group="ai", ui_order=36),
        # ===================== ESTRATEGIA / ADVISOR ====================
        _opt("strategy_selection", "Selecao de estrategia",
             "strategy", source="challenge_readiness/strategy_factory.py",
             selectable_by_user=True, default_enabled=True,
             requires_profile_permission=True,
             required_profile_field="allowed_strategies",
             risk_impact=RI.MEDIUM,
             execution_impact=EI.DEMO_POSSIBLE,
             status=ST.AVAILABLE, ui_group="strategy", ui_order=40),
        _opt("profile_selection", "Selecao de perfil operacional",
             "strategy",
             source="operational_profile/profile_registry.py",
             selectable_by_user=True, default_enabled=True,
             risk_impact=RI.HIGH, execution_impact=EI.DEMO_POSSIBLE,
             status=ST.AVAILABLE,
             description=(
                 "13 perfis. Templates numericos exigem confirmacao "
                 "do operador (V12)."
             ),
             missing_information=(
                 "V12: confirmar templates numericos dos perfis",
             ),
             requires_gate=True,
             required_gate_name="ENABLE_DEMO_EXECUTION",
             ui_group="strategy", ui_order=41),
        _opt("parameter_advisor", "Strategy Parameter Advisor",
             "strategy",
             source="research/strategy_parameter_advisor.py",
             selectable_by_user=True, risk_impact=RI.LOW,
             execution_impact=EI.NONE, status=ST.AVAILABLE,
             description=(
                 "Acionado apenas pelo operador; sugestoes "
                 "consultivas; aceite manual auditado."
             ),
             ui_group="strategy", ui_order=42),
        _opt("risk_overrides", "Risk overrides por perfil (gated)",
             "strategy",
             source="operational_profile/risk_adapter.py",
             requires_operator_confirmation=True,
             risk_impact=RI.CRITICAL,
             execution_impact=EI.DEMO_POSSIBLE,
             requires_gate=True,
             required_gate_name="ENABLE_DEMO_EXECUTION",
             ui_group="strategy", ui_order=43),
        # ===================== POLITICAS OPERACIONAIS ==================
        _opt("stale_data_policy", "Politica de dados stale",
             "policies",
             source="endurance_runner.py:_is_stale",
             default_enabled=True, risk_impact=RI.MEDIUM,
             execution_impact=EI.NONE, status=ST.AVAILABLE,
             description=(
                 "Stale se idade > timeframe + max_stale_data_seconds; "
                 "ciclo e pulado e warning registrado."
             ),
             ui_group="policies", ui_order=50),
        _opt("api_failure_policy", "Politica de falhas de API",
             "policies",
             source="endurance_runner.py (max_api_failures)",
             default_enabled=True, risk_impact=RI.MEDIUM,
             execution_impact=EI.NONE, status=ST.AVAILABLE,
             ui_group="policies", ui_order=51),
        _opt("operator_inputs_enforcement",
             "Bloqueio por Operator Inputs ausentes", "policies",
             source="operator_inputs/store.py",
             default_enabled=True, risk_impact=RI.NONE,
             execution_impact=EI.NONE, status=ST.AVAILABLE,
             ui_group="policies", ui_order=52),
    ]
    ids = [o.option_id for o in options]
    assert len(ids) == len(set(ids)), "option_id duplicado"
    return tuple(options)


class OperationalOptionsRegistry:
    """Registry consultavel + snapshot UI-ready."""

    def __init__(
        self, options: Optional[Tuple[OperationalOption, ...]] = None,
    ) -> None:
        self._options: Dict[str, OperationalOption] = {
            o.option_id: o
            for o in (options or build_default_registry())
        }

    def get(self, option_id: str) -> Optional[OperationalOption]:
        return self._options.get(option_id)

    @property
    def all_options(self) -> Tuple[OperationalOption, ...]:
        return tuple(
            sorted(
                self._options.values(),
                key=lambda o: (o.ui_group, o.ui_order),
            )
        )

    def non_default_options(self) -> Tuple[OperationalOption, ...]:
        return tuple(
            o for o in self.all_options if not o.default_enabled
        )

    def declared_gate_names(self) -> Tuple[str, ...]:
        return tuple(sorted({
            o.required_gate_name for o in self._options.values()
            if o.required_gate_name
        }))

    def to_snapshot(self) -> dict:
        """OperatorSelectableOptionSnapshot (UI-ready)."""
        return {
            "schema": "operational_options_snapshot_v1",
            "options": [o.to_dict() for o in self.all_options],
            "total": len(self._options),
            "non_default_visible": len(self.non_default_options()),
        }


__all__ = [
    "OperationalOptionsRegistry",
    "build_default_registry",
]
