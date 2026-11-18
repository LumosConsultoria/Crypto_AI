"""
Production Wiring (FASE 28)
==================================
Helpers factory para wiring operacional explicito do pipeline
Demo30MinRealRunner com infraestrutura Bybit demo real (read-only +
gated single-shot via FASE 22).

⚠️  RESTRICOES OBRIGATORIAS:
    - Imports de BybitClient, BybitDemoExecutor, BybitDemoPreflight
      SAO LAZY dentro de cada funcao factory. Ao importar este modulo,
      ZERO classes de rede sao carregadas.
    - Cada factory valida pre-condicoes ANTES de instanciar.
    - Nenhum metodo aqui envia ordem.
    - Nenhum metodo aqui chama rede; eles APENAS instanciam
      colaboradores que, posteriormente, podem chamar rede sob
      orquestracao do runner/CLI com triple-lock.
    - bybit_demo_linear EXATAMENTE em status OPT_IN; qualquer outro
      status aborta.
    - Nao promove provider. Nao torna demo default. Nao altera
      assert_live_allowed/ModeGuard/RiskEngine.

ACESSO DEFENSIVO A ENDPOINT:
    BybitClient nao expoe propriedade publica para base_url. Para
    validar endpoint apos instanciacao, usamos helper
    `_resolve_demo_endpoint_safely(client)` que primeiro tenta
    `getattr(client, 'endpoint', None)` (futuro), depois fallback
    para `_base_url` SOMENTE como leitura defensiva auditada e
    isolada. O helper eh testavel independentemente.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional


# Endpoint demo esperado (mesma constante usada em BybitClient.BASE_URL_DEMO).
EXPECTED_DEMO_ENDPOINT = "https://api-demo.bybit.com"

# Provider id alvo nesta fase.
EXPECTED_PROVIDER_ID = "bybit_demo_linear"


class ProductionWiringError(RuntimeError):
    """Wiring abortado por pre-condicao de safety."""


# ---------------------------------------------------------------------------
# Helpers isolados / testaveis
# ---------------------------------------------------------------------------

def _resolve_demo_endpoint_safely(client: Any) -> Optional[str]:
    """Le endpoint do client de forma defensiva e auditavel.

    Ordem de preferencia:
        1. `getattr(client, 'endpoint', None)` (futuro).
        2. `getattr(client, 'base_url', None)` (futuro).
        3. `getattr(client, '_base_url', None)` (leitura defensiva,
            documentada como fallback isolado).

    Retorna None se nenhum atributo for encontrado.
    """
    for attr_name in ("endpoint", "base_url", "_base_url"):
        val = getattr(client, attr_name, None)
        if isinstance(val, str) and val:
            return val
    return None


def _envvar_truthy(name: str) -> bool:
    """True se env var contem 'true'/'1'/'yes' (case-insensitive)."""
    val = os.environ.get(name, "")
    return val.strip().lower() in ("true", "1", "yes")


def _envvar_present(name: str) -> bool:
    """True se env var contem string nao-vazia (presence-only)."""
    val = os.environ.get(name, "")
    return bool(val.strip())


def _read_env_credentials() -> tuple:
    """Le credentials do env. Retorna tupla (api_key, api_secret).

    ⚠️  Helper INTERNO. NUNCA logamos os valores. NUNCA expomos
        via repr. Caller (helper factory) usa imediatamente e
        descarta a referencia local.
    """
    return (
        os.environ.get("BYBIT_DEMO_API_KEY", "").strip(),
        os.environ.get("BYBIT_DEMO_API_SECRET", "").strip(),
    )


# ---------------------------------------------------------------------------
# build_live_demo_client
# ---------------------------------------------------------------------------

def build_live_demo_client(
    *,
    client_class: Optional[type] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    timeout: int = 10,
) -> Any:
    """Instancia BybitClient demo com validacoes safety.

    Validacoes (ABORTA se qualquer falhar):
        1. ENABLE_LIVE_TRADING nao truthy.
        2. credentials presentes (api_key + api_secret nao-vazios).
        3. apos instanciacao, client.environment == "demo".
        4. apos instanciacao, endpoint resolvido == EXPECTED_DEMO_ENDPOINT.
        5. apos instanciacao, client.has_credentials == True.

    Args:
        client_class: opcional, injetavel em testes para evitar instanciar
                      BybitClient real. Default lazy-imports o real.
        api_key, api_secret: opcionais; defaults leem do env. Valores
                             NUNCA sao logados/retornados.
        timeout: HTTP timeout em segundos.

    Returns:
        Instancia do client_class (BybitClient ou injetado).

    Raises:
        ProductionWiringError: qualquer validacao falhou.
    """
    if _envvar_truthy("ENABLE_LIVE_TRADING"):
        raise ProductionWiringError(
            "ENABLE_LIVE_TRADING is truthy; aborting wiring "
            "(demo path forbids live)"
        )
    key_env, secret_env = _read_env_credentials()
    eff_key = api_key if api_key else key_env
    eff_secret = api_secret if api_secret else secret_env
    if not eff_key or not eff_secret:
        raise ProductionWiringError(
            "BYBIT_DEMO_API_KEY / BYBIT_DEMO_API_SECRET required "
            "(values never logged)"
        )

    if client_class is None:
        # Lazy import: zero rede ate aqui.
        from crypto_trading_bot.exchange.bybit_client import (
            BybitClient as _BybitClient,
        )
        cls = _BybitClient
    else:
        cls = client_class

    client = cls(
        environment="demo",
        api_key=eff_key,
        api_secret=eff_secret,
        timeout=timeout,
    )

    # Validacao post-instanciacao
    env = getattr(client, "environment", None)
    if env != "demo":
        raise ProductionWiringError(
            f"client.environment expected 'demo', got {env!r}"
        )
    endpoint = _resolve_demo_endpoint_safely(client)
    if endpoint != EXPECTED_DEMO_ENDPOINT:
        raise ProductionWiringError(
            f"client endpoint expected {EXPECTED_DEMO_ENDPOINT!r}, "
            f"got {endpoint!r}"
        )
    if not bool(getattr(client, "has_credentials", False)):
        raise ProductionWiringError(
            "client.has_credentials False; credentials lost during init"
        )
    return client


# ---------------------------------------------------------------------------
# build_live_demo_executor
# ---------------------------------------------------------------------------

def build_live_demo_executor(
    *,
    client: Any,
    mode_guard: Any,
    risk_engine: Any,
    confirm_demo_execution: bool = False,
    executor_class: Optional[type] = None,
    extra_kwargs: Optional[dict] = None,
) -> Any:
    """Instancia BybitDemoExecutor usando o client demo dado.

    REUSA mode_guard e risk_engine ja construidos no wired path; nao
    instancia novas dependencias internamente. Isso garante coerencia
    com as instancias ja validadas pelo readiness + flat-check.

    Args:
        client: BybitClient demo (deve passar pelos asserts de
                build_live_demo_client antes).
        mode_guard: ModeGuard ja validado pelo wired path.
        risk_engine: RiskEngine soberano ja validado.
        confirm_demo_execution: Default False (gate FASE 22 decide
                                via execute_demo_session_gated +
                                triple-lock). NAO autoriza ordem real
                                por si so.
        executor_class: injetavel em testes.
        extra_kwargs: opcionais (reconciliation_attempts, qty_step, etc.).

    Returns:
        Instancia do executor.

    Raises:
        ProductionWiringError: client/mode_guard/risk_engine invalidos.
    """
    if client is None:
        raise ProductionWiringError("client required")
    if getattr(client, "environment", None) != "demo":
        raise ProductionWiringError(
            "executor requires client.environment == 'demo'"
        )
    if mode_guard is None:
        raise ProductionWiringError(
            "mode_guard required (reuse the instance built in wired path)"
        )
    if risk_engine is None:
        raise ProductionWiringError(
            "risk_engine required (reuse the instance built in wired path)"
        )
    if executor_class is None:
        from crypto_trading_bot.execution.bybit_demo_executor import (
            BybitDemoExecutor as _BybitDemoExecutor,
        )
        cls = _BybitDemoExecutor
    else:
        cls = executor_class
    kw = dict(extra_kwargs or {})
    return cls(
        client=client,
        mode_guard=mode_guard,
        risk_engine=risk_engine,
        confirm_demo_execution=bool(confirm_demo_execution),
        **kw,
    )


# ---------------------------------------------------------------------------
# build_live_preflight_factory
# ---------------------------------------------------------------------------

def build_live_preflight_factory(
    *,
    client: Any,
    mode_guard: Any,
    risk_engine: Any,
    symbol: str,
    side: str = "buy",
    leverage_target: float = 1.0,
    target_take_profit_rr: Optional[float] = 2.0,
    preflight_class: Optional[type] = None,
) -> Callable[[], Any]:
    """Constroi factory zero-argumento de PreflightReport-like.

    Cada chamada da factory instancia BybitDemoPreflight com os
    colaboradores dados e chama .run() (read-only).

    Args:
        client: BybitClient demo validado.
        mode_guard: ModeGuard.
        risk_engine: RiskEngine.
        symbol/side/leverage_target/target_take_profit_rr:
            parametros do preflight.
        preflight_class: injetavel para testes (evita instanciar real).

    Returns:
        Callable() -> PreflightReport-like.
    """
    if client is None:
        raise ProductionWiringError("client required")
    if getattr(client, "environment", None) != "demo":
        raise ProductionWiringError(
            "preflight requires client.environment == 'demo'"
        )
    if mode_guard is None or risk_engine is None:
        raise ProductionWiringError(
            "mode_guard and risk_engine required"
        )
    if not isinstance(symbol, str) or not symbol.strip():
        raise ProductionWiringError("symbol required")

    cls_ref = preflight_class

    def _factory():
        if cls_ref is None:
            from crypto_trading_bot.execution.bybit_demo_preflight import (
                BybitDemoPreflight as _BybitDemoPreflight,
            )
            cls_local = _BybitDemoPreflight
        else:
            cls_local = cls_ref
        preflight = cls_local(
            client=client,
            mode_guard=mode_guard,
            risk_engine=risk_engine,
            symbol=symbol,
            side=side,
            leverage_target=leverage_target,
            confirm_demo_execution=True,
            target_take_profit_rr=target_take_profit_rr,
        )
        return preflight.run()

    return _factory


# ---------------------------------------------------------------------------
# build_live_blueprint_provider
# ---------------------------------------------------------------------------

def build_live_blueprint_provider(
    *,
    preflight_factory: Callable[[], Any],
    ttl_seconds: Optional[int] = None,
    clock: Optional[Callable] = None,
):
    """Constroi LiveDemoBlueprintProvider FASE 27 com factory dada.

    Args:
        preflight_factory: callable() -> PreflightReport-like (de
                           build_live_preflight_factory ou fake).
        ttl_seconds: TTL custom (default usa
                     LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS).
        clock:       injetavel.
    """
    from crypto_trading_bot.demo_endurance.live_blueprint_provider import (
        LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS,
        LiveDemoBlueprintProvider,
    )
    effective_ttl = (
        int(ttl_seconds) if ttl_seconds is not None
        else LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS
    )
    return LiveDemoBlueprintProvider(
        preflight_factory=preflight_factory,
        ttl_seconds=effective_ttl,
        clock=clock,
    )


# ---------------------------------------------------------------------------
# build_provider_registry_with_opt_in
# ---------------------------------------------------------------------------

def build_provider_registry_with_opt_in(
    *,
    registry: Optional[Any] = None,
    registry_factory: Optional[Callable] = None,
) -> Any:
    """Retorna ProviderRegistry validando bybit_demo_linear == OPT_IN.

    Aceita registry pre-existente OU usa default. Aborta se entry
    nao existir ou status NAO for EXATAMENTE OPT_IN.

    Args:
        registry: instancia de ProviderRegistry pre-populada
                  (injetavel em testes).
        registry_factory: callable() -> ProviderRegistry; usado se
                          registry=None. Default: lazy get_registry().

    Returns:
        ProviderRegistry validado.

    Raises:
        ProductionWiringError: bybit_demo_linear ausente ou nao OPT_IN.
    """
    if registry is None:
        if registry_factory is not None:
            registry = registry_factory()
        else:
            from crypto_trading_bot.execution.provider_registry import (
                get_registry,
            )
            registry = get_registry()
    if registry is None:
        raise ProductionWiringError("registry resolution returned None")

    try:
        entry = registry.get(EXPECTED_PROVIDER_ID)
    except KeyError:
        raise ProductionWiringError(
            f"provider {EXPECTED_PROVIDER_ID!r} not registered"
        )
    from crypto_trading_bot.execution.provider_capability import (
        ProviderStatus,
    )
    status = getattr(entry, "status", None)
    if status is not ProviderStatus.OPT_IN:
        status_val = getattr(status, "value", str(status))
        raise ProductionWiringError(
            f"provider {EXPECTED_PROVIDER_ID!r} status must be "
            f"EXACTLY OPT_IN; got {status_val!r}"
        )
    return registry


# ---------------------------------------------------------------------------
# build_session_plan_factory
# ---------------------------------------------------------------------------

def build_session_plan_factory(
    *,
    plan_builder: Optional[Callable] = None,
    readiness_check_class: Optional[type] = None,
    signal_blueprint_class: Optional[type] = None,
    blueprint_side_enum: Optional[type] = None,
) -> Callable:
    """Constroi factory injetavel para DemoSessionPlan FASE 22.

    Default: lazy-imports FASE 22 builders. Testes podem injetar
    classes/fakes alternativas para evitar exigencia de
    OperationalProfile/RiskConfig reais.

    Returns:
        Callable com assinatura:
            factory(*, plan_id, live_snapshot, trading_signal,
                    runner_plan, profile, effective_risk_config, now)
            -> DemoSessionPlan-like
    """
    def _factory(*, plan_id, live_snapshot, trading_signal,
                 runner_plan, profile, effective_risk_config, now):
        # Lazy imports - zero rede.
        if signal_blueprint_class is None or blueprint_side_enum is None:
            from crypto_trading_bot.demo_session_execution.plan import (
                BlueprintSide, SignalBlueprint,
            )
            bp_side_cls = blueprint_side_enum or BlueprintSide
            sig_cls = signal_blueprint_class or SignalBlueprint
        else:
            bp_side_cls = blueprint_side_enum
            sig_cls = signal_blueprint_class
        bp = live_snapshot.blueprint
        side_enum = (
            bp_side_cls.BUY if bp.side == "buy" else bp_side_cls.SELL
        )
        sig_blueprint = sig_cls(
            symbol=runner_plan.symbol,
            side=side_enum,
            entry_price=float(bp.entry_price),
            stop_loss=float(bp.stop_loss),
            take_profit=float(bp.take_profit),
            position_size_usd=float(bp.notional_usd),
            strategy_name=runner_plan.strategy_name,
            leverage=1.0,
        )
        if plan_builder is None:
            from crypto_trading_bot.demo_session_execution.plan import (
                build_demo_session_plan,
            )
            from crypto_trading_bot.demo_session_readiness.readiness_check \
                import DemoSessionReadinessCheck
            rcls = readiness_check_class or DemoSessionReadinessCheck
            readiness_check = rcls(
                profile=profile,
                effective_risk_config=effective_risk_config,
                provider_id=EXPECTED_PROVIDER_ID,
                now=now,
            )
            readiness_report = readiness_check.evaluate()
            return build_demo_session_plan(
                plan_id=plan_id,
                readiness_report=readiness_report,
                profile=profile,
                blueprint=sig_blueprint,
                effective_risk_config=effective_risk_config,
                risk_snapshot=None,
                now=now,
            )
        return plan_builder(
            plan_id=plan_id,
            blueprint=sig_blueprint,
            profile=profile,
            effective_risk_config=effective_risk_config,
            now=now,
        )

    return _factory


# ---------------------------------------------------------------------------
# FASE 29 factories
# ---------------------------------------------------------------------------

def build_phase29_exit_resolver(
    *,
    max_time_in_position_seconds: Optional[int] = None,
    allow_close_on_opposite_signal: bool = False,
    emergency_close_enabled: bool = True,
    clock: Optional[Callable] = None,
):
    """Constroi ExitDecisionResolver FASE 29 com policy default."""
    from crypto_trading_bot.demo_endurance.exit_resolver import (
        DEFAULT_MAX_TIME_IN_POSITION_SECONDS,
        ExitDecisionResolver,
        build_phase29_exit_policy,
    )
    eff_time = (
        int(max_time_in_position_seconds)
        if max_time_in_position_seconds is not None
        else DEFAULT_MAX_TIME_IN_POSITION_SECONDS
    )
    policy = build_phase29_exit_policy(
        max_time_in_position_seconds=eff_time,
        allow_close_on_opposite_signal=allow_close_on_opposite_signal,
        emergency_close_enabled=emergency_close_enabled,
    )
    return ExitDecisionResolver(exit_policy=policy, clock=clock)


def build_position_monitor(
    *,
    client: Any,
    symbol: str,
    poll_interval_seconds: float = 60.0,
    max_monitor_minutes: int = 30,
    clock: Optional[Callable] = None,
    sleep: Optional[Callable] = None,
    monitor_class: Optional[type] = None,
):
    """Constroi PositionMonitor FASE 29 com client demo dado.

    Fetches mapeados:
        positions_fetch          -> client.get_positions(symbol)
        orders_fetch             -> client.get_open_orders(symbol)
        conditional_orders_fetch -> client.get_open_orders(symbol,
                                       orderFilter='StopOrder')
        ticker_fetch             -> client.get_ticker(symbol).mark_price
    """
    if client is None:
        raise ProductionWiringError("client required")
    if getattr(client, "environment", None) != "demo":
        raise ProductionWiringError(
            "position monitor requires client.environment == 'demo'"
        )
    if monitor_class is None:
        from crypto_trading_bot.demo_endurance.position_monitor import (
            PositionMonitor as _PM,
        )
        cls = _PM
    else:
        cls = monitor_class

    def _positions_fetch(*, symbol):
        try:
            return client.get_positions(symbol=symbol)
        except Exception:  # noqa: BLE001
            raise

    def _orders_fetch(*, symbol):
        try:
            res = client.get_open_orders(symbol=symbol)
            return res or []
        except Exception:  # noqa: BLE001
            raise

    def _cond_orders_fetch(*, symbol):
        try:
            res = client.get_open_orders(
                symbol=symbol, orderFilter="StopOrder",
            )
            return res or []
        except Exception:  # noqa: BLE001
            return []

    def _ticker_fetch(*, symbol):
        try:
            t = client.get_ticker(symbol=symbol)
            return float(
                getattr(t, "mark_price", None)
                or getattr(t, "last_price", 0.0)
                or 0.0
            ) or None
        except Exception:  # noqa: BLE001
            return None

    return cls(
        symbol=symbol,
        positions_fetch=_positions_fetch,
        orders_fetch=_orders_fetch,
        conditional_orders_fetch=_cond_orders_fetch,
        ticker_fetch=_ticker_fetch,
        poll_interval_seconds=poll_interval_seconds,
        max_monitor_minutes=max_monitor_minutes,
        clock=clock,
        sleep=sleep,
    )


def build_pnl_tracker(
    *,
    client: Any,
    tracker_class: Optional[type] = None,
):
    """Constroi PnLTracker FASE 29 com fetches read-only."""
    if client is None:
        raise ProductionWiringError("client required")
    if tracker_class is None:
        from crypto_trading_bot.demo_endurance.pnl_tracker import (
            PnLTracker as _PnLT,
        )
        cls = _PnLT
    else:
        cls = tracker_class

    def _exec_list(*, symbol, start_ms, end_ms):
        try:
            return client.get_execution_list(
                symbol=symbol, start_ms=start_ms, end_ms=end_ms,
            )
        except Exception:  # noqa: BLE001
            return None

    def _closed_pnl(*, symbol, start_ms, end_ms):
        try:
            return client.get_closed_pnl(
                symbol=symbol, start_ms=start_ms, end_ms=end_ms,
            )
        except Exception:  # noqa: BLE001
            return None

    return cls(
        execution_list_fetch=_exec_list,
        closed_pnl_fetch=_closed_pnl,
    )


def build_close_executor_wrapper(
    *,
    executor: Any,
    wrapper_class: Optional[type] = None,
):
    """Constroi CloseExecutorWrapper FASE 29."""
    if executor is None:
        raise ProductionWiringError("executor required")
    if wrapper_class is None:
        from crypto_trading_bot.demo_endurance.close_executor_wrapper \
            import CloseExecutorWrapper as _CEW
        cls = _CEW
    else:
        cls = wrapper_class
    return cls(executor=executor)


__all__ = [
    "EXPECTED_DEMO_ENDPOINT",
    "EXPECTED_PROVIDER_ID",
    "ProductionWiringError",
    "build_live_demo_client",
    "build_live_demo_executor",
    "build_live_preflight_factory",
    "build_live_blueprint_provider",
    "build_provider_registry_with_opt_in",
    "build_session_plan_factory",
    "_resolve_demo_endpoint_safely",  # exposto para teste isolado
    # FASE 29
    "build_phase29_exit_resolver",
    "build_position_monitor",
    "build_pnl_tracker",
    "build_close_executor_wrapper",
]
