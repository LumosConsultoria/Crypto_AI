"""
demo_endurance - Demo 30 Min Readiness + Controlled Demo Endurance Plan
==========================================================================
FASE 26 - planned/dry-run only. ZERO rede / API / ordem externa.

⚠️  ESTE MODULO NAO:
    - executa demo real;
    - chama Bybit API;
    - importa BybitClient / BybitDemoExecutor / BybitDemoPreflight;
    - chama execute_demo_session_gated;
    - importa build_demo_api_blueprint;
    - le .env / Settings real;
    - envia ordem.

⚠️  Execucao real demo continua exclusivamente via:
    scripts/run_bybit_demo_session_gated.py (Comando A + Comando B,
    runbook FASE 22).

⚠️  Demo endurance REAL (loop multi-ciclo demo) ficara para FASE 27,
    apenas apos aprovacao explicita do operador.
"""

from crypto_trading_bot.demo_endurance.dry_run import (
    DEFAULT_VIRTUAL_CYCLE_SECONDS,
    Demo30MinDryRunSimulator,
)
from crypto_trading_bot.demo_endurance.live_blueprint_provider import (
    LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS,
    LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS,
    LiveBlueprintSnapshot,
    LiveDemoBlueprintError,
    LiveDemoBlueprintProvider,
)
from crypto_trading_bot.demo_endurance.prompt_io import (
    envvar_present,
    is_tty,
    prompt_yes_or_abort,
    TTYRequired,
)
from crypto_trading_bot.demo_endurance.production_wiring import (
    EXPECTED_DEMO_ENDPOINT,
    EXPECTED_PROVIDER_ID,
    ProductionWiringError,
    build_close_executor_wrapper,
    build_live_blueprint_provider,
    build_live_demo_client,
    build_live_demo_executor,
    build_live_preflight_factory,
    build_phase29_exit_resolver,
    build_pnl_tracker,
    build_position_monitor,
    build_provider_registry_with_opt_in,
    build_session_plan_factory,
)
from crypto_trading_bot.demo_endurance.real_runner import (
    API_FAILURE_STRIKES_THRESHOLD,
    DEFAULT_CYCLE_INTERVAL_SECONDS,
    Demo30MinRealRunner,
    MIN_TTL_SECONDS_BEFORE_ORDER,
)
from crypto_trading_bot.demo_endurance.session_telemetry import (
    SessionTelemetryEvent,
    SessionTelemetryRecorder,
)
# FASE 29
from crypto_trading_bot.demo_endurance.close_executor_wrapper import (
    CloseExecutionResult,
    CloseExecutorWrapper,
)
from crypto_trading_bot.demo_endurance.exit_resolver import (
    DEFAULT_ALLOW_OPPOSITE_SIGNAL,
    DEFAULT_EMERGENCY_CLOSE_ENABLED,
    DEFAULT_MAX_TIME_IN_POSITION_SECONDS,
    ExitDecisionResolver,
    build_open_position_state_from_snapshot,
    build_phase29_exit_policy,
)
from crypto_trading_bot.demo_endurance.flat_check_validator import (
    FlatCheckResult,
    validate_flat,
)
from crypto_trading_bot.demo_endurance.cycle_context import (
    TradeCycleContext,
)
from crypto_trading_bot.demo_endurance.endurance_duration import (
    DurationSpec,
)
from crypto_trading_bot.demo_endurance.endurance_limits import (
    EnduranceLimits,
)
from crypto_trading_bot.demo_endurance.endurance_outcome import (
    DemoEnduranceOutcome,
    EnduranceEndedReason,
)
from crypto_trading_bot.demo_endurance.endurance_preflight import (
    EndurancePreflightResult,
    demo_credentials_present_from_env,
    validate_endurance_preflight,
)
from crypto_trading_bot.demo_endurance.endurance_runner import (
    DemoEnduranceRunner,
    ENV_ALLOW_MULTI_ORDER,
    ENV_PREDICTION_CONTEXT,
)
from crypto_trading_bot.demo_endurance.endurance_real_execution import (
    MultiOrderExecutionState,
    RealTradeLifecycle,
    RealTradeRecord,
    build_real_trade_lifecycle,
    can_accept_new_entry,
    env_reduce_only_enabled,
)
from crypto_trading_bot.demo_endurance.gates_phase29 import (
    ENV_ALLOW_SHORT,
    ENV_REAL_ORDER_ENABLED,
    ENV_REDUCE_ONLY_CLOSE_ENABLED,
    ENV_USE_DEMO,
    EXPECTED_PHRASE,
    Phase29GateResult,
    validate_phase29_close_gate,
    validate_phase29_entry_gate,
    validate_phase29_short_gate,
)
from crypto_trading_bot.demo_endurance.gates_phase30 import (
    ENV_REAL_MULTI_ORDER,
    MAX_REAL_ORDERS_SAFE_CAP,
    Phase30GateResult,
    expected_phrase_30_2,
    validate_phase30_2_real_multi_gate,
)
from crypto_trading_bot.demo_endurance.pnl_tracker import (
    PnLResult,
    PnLTracker,
)
from crypto_trading_bot.demo_endurance.position_monitor import (
    API_FAILURE_STRIKES_THRESHOLD as PM_API_FAILURE_STRIKES_THRESHOLD,
    DEFAULT_MAX_MONITOR_MINUTES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    PositionMonitor,
    PositionSnapshot,
)
from crypto_trading_bot.demo_endurance.outcome import (
    default_recommended_next_action,
    Demo30MinOutcome,
    Demo30MinVerdict,
)
from crypto_trading_bot.demo_endurance.plan import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    Demo30MinPlan,
    Demo30MinPlanRejected,
    PlannedDemoBlueprint,
    PlannedDemoBlueprintRejected,
)
from crypto_trading_bot.demo_endurance.readiness import (
    build_demo_30_min_readiness_report,
    Demo30MinReadinessConfig,
    Demo30MinReadinessIssue,
    Demo30MinReadinessReport,
    Demo30MinReadinessSeverity,
    Demo30MinReadinessStatus,
    EnvironmentSnapshot,
    LastSafetyFlags,
)
from crypto_trading_bot.demo_endurance.safety_thresholds import (
    DEMO_30_MIN_APPLY_DEMO_REAL_DEFAULT,
    DEMO_30_MIN_MAX_OPEN_POSITIONS,
    DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
    DEMO_30_MIN_MAX_SESSION_MINUTES,
    DEMO_30_MIN_PLANNED_BLUEPRINT_TTL_SECONDS,
    DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
    DEMO_30_MIN_PLANNED_ENVIRONMENT,
    DEMO_30_MIN_PLANNED_PROVIDER_ID,
    DEMO_30_MIN_SCHEMA_VERSION,
)
from crypto_trading_bot.demo_endurance.stage import (
    DemoEnduranceStage,
    is_valid_stage,
)
from crypto_trading_bot.demo_endurance.ui_snapshot import (
    to_ui_snapshot,
)


__all__ = [
    # Stage
    "DemoEnduranceStage",
    "is_valid_stage",
    # Safety thresholds
    "DEMO_30_MIN_APPLY_DEMO_REAL_DEFAULT",
    "DEMO_30_MIN_MAX_OPEN_POSITIONS",
    "DEMO_30_MIN_MAX_ORDERS_HARD_CAP",
    "DEMO_30_MIN_MAX_SESSION_MINUTES",
    "DEMO_30_MIN_PLANNED_BLUEPRINT_TTL_SECONDS",
    "DEMO_30_MIN_PLANNED_ENDPOINT_TYPE",
    "DEMO_30_MIN_PLANNED_ENVIRONMENT",
    "DEMO_30_MIN_PLANNED_PROVIDER_ID",
    "DEMO_30_MIN_SCHEMA_VERSION",
    # Plan + blueprint
    "PlannedDemoBlueprint",
    "PlannedDemoBlueprintRejected",
    "build_default_planned_blueprint",
    "Demo30MinPlan",
    "Demo30MinPlanRejected",
    "build_demo_30_min_plan",
    # Readiness
    "Demo30MinReadinessConfig",
    "Demo30MinReadinessIssue",
    "Demo30MinReadinessReport",
    "Demo30MinReadinessSeverity",
    "Demo30MinReadinessStatus",
    "EnvironmentSnapshot",
    "LastSafetyFlags",
    "build_demo_30_min_readiness_report",
    # Outcome
    "Demo30MinOutcome",
    "Demo30MinVerdict",
    "default_recommended_next_action",
    # Dry-run
    "Demo30MinDryRunSimulator",
    "DEFAULT_VIRTUAL_CYCLE_SECONDS",
    # FASE 27 - Live blueprint provider
    "LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS",
    "LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS",
    "LiveBlueprintSnapshot",
    "LiveDemoBlueprintError",
    "LiveDemoBlueprintProvider",
    # FASE 27 - prompt IO
    "envvar_present",
    "is_tty",
    "prompt_yes_or_abort",
    "TTYRequired",
    # FASE 27 - Real runner
    "API_FAILURE_STRIKES_THRESHOLD",
    "DEFAULT_CYCLE_INTERVAL_SECONDS",
    "Demo30MinRealRunner",
    "MIN_TTL_SECONDS_BEFORE_ORDER",
    # FASE 28 - Production wiring
    "EXPECTED_DEMO_ENDPOINT",
    "EXPECTED_PROVIDER_ID",
    "ProductionWiringError",
    "build_live_blueprint_provider",
    "build_live_demo_client",
    "build_live_demo_executor",
    "build_live_preflight_factory",
    "build_provider_registry_with_opt_in",
    "build_session_plan_factory",
    # FASE 28 - Session telemetry
    "SessionTelemetryEvent",
    "SessionTelemetryRecorder",
    # UI snapshot
    "to_ui_snapshot",
    # FASE 29 - Exit management
    "CloseExecutionResult",
    "CloseExecutorWrapper",
    "DEFAULT_ALLOW_OPPOSITE_SIGNAL",
    "DEFAULT_EMERGENCY_CLOSE_ENABLED",
    "DEFAULT_MAX_TIME_IN_POSITION_SECONDS",
    "ExitDecisionResolver",
    "build_open_position_state_from_snapshot",
    "build_phase29_exit_policy",
    # FASE 29 - Flat check + PnL
    "FlatCheckResult",
    "validate_flat",
    "PnLResult",
    "PnLTracker",
    # FASE 29 - Position monitor
    "DEFAULT_MAX_MONITOR_MINUTES",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "PM_API_FAILURE_STRIKES_THRESHOLD",
    "PositionMonitor",
    "PositionSnapshot",
    # FASE 30.2 - Multi-ordem real demo sequencial
    "ENV_REAL_MULTI_ORDER",
    "MAX_REAL_ORDERS_SAFE_CAP",
    "MultiOrderExecutionState",
    "Phase30GateResult",
    "RealTradeLifecycle",
    "RealTradeRecord",
    "build_real_trade_lifecycle",
    "can_accept_new_entry",
    "env_reduce_only_enabled",
    "expected_phrase_30_2",
    "validate_phase30_2_real_multi_gate",
    # FASE 30 - Demo endurance real-time
    "DemoEnduranceOutcome",
    "DemoEnduranceRunner",
    "DurationSpec",
    "ENV_ALLOW_MULTI_ORDER",
    "ENV_PREDICTION_CONTEXT",
    "EnduranceEndedReason",
    "EnduranceLimits",
    "EndurancePreflightResult",
    "TradeCycleContext",
    "demo_credentials_present_from_env",
    "validate_endurance_preflight",
    # FASE 29 - Gates
    "ENV_ALLOW_SHORT",
    "ENV_REAL_ORDER_ENABLED",
    "ENV_REDUCE_ONLY_CLOSE_ENABLED",
    "ENV_USE_DEMO",
    "EXPECTED_PHRASE",
    "Phase29GateResult",
    "validate_phase29_close_gate",
    "validate_phase29_entry_gate",
    "validate_phase29_short_gate",
    # FASE 29 - Production wiring factories
    "build_phase29_exit_resolver",
    "build_position_monitor",
    "build_pnl_tracker",
    "build_close_executor_wrapper",
]
