"""
Demo30MinRealRunner (FASE 27)
=================================
Runner controlado para uma sessao demo real de ate 30 minutos com
NO MAXIMO 1 ORDEM. Orquestra:

    1. LiveDemoBlueprintProvider.preflight()        (read-only)
    2. Strategy real avalia sinais via market_data_callable injetavel
    3. RiskEngine.validate_signal aprova/bloqueia
    4. Se aprovado:
         a. ensure_fresh() do provider (re-preflight se TTL stale);
         b. monta SignalBlueprint + DemoSessionPlan (FASE 22);
         c. chama execute_demo_session_gated() NO MAXIMO 1x;
         d. encadeia post_session_check(stage="after_entry").
    5. Ao final: post_session_check(stage="flat_check") quando seguro.
    6. Producao de Demo30MinOutcome com novos campos FASE 27.

⚠️  RESTRICOES OBRIGATORIAS:
    - NAO chama BybitDemoExecutor.execute diretamente; usa apenas
      execute_demo_session_gated.
    - NAO chama close_position / cancel_order / reduceOnly.
    - NAO faz retry de ordem.
    - NAO abre segunda ordem.
    - NAO chama rede em testes (todos os colaboradores sao injetaveis).
    - Posicao aberta no fim => recommended_next_action conservador.

Dependencias INJETAVEIS para teste 100% offline:
    - provider:                LiveDemoBlueprintProvider (mock OK).
    - market_data_callable:    callable(symbol, timeframe, limit) -> List[Candle].
    - feature_engine_factory:  callable() -> FeatureEngine; default lazy real.
    - strategy_factory:        callable() -> strategy (BaseStrategy compativel).
    - risk_engine:             RiskEngine real ou fake.
    - safety_machine:          SafetyStateMachine.
    - mode_guard:              ModeGuard.
    - provider_registry:       ProviderRegistry.
    - demo_executor_factory:   callable() -> DemoExecutorProtocol (mock OK).
    - gate_callable:           callable(...) -> DemoSessionOutcome
                               (default execute_demo_session_gated).
    - post_session_check_callable: callable(executor, **kw) -> result.
    - effective_risk_config:   RiskConfig.
    - profile:                 OperationalProfile.
    - clock:                   callable() -> datetime.
    - sleep:                   callable(seconds) -> None.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

from crypto_trading_bot.demo_endurance.live_blueprint_provider import (
    LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS,
    LiveBlueprintSnapshot,
    LiveDemoBlueprintError,
    LiveDemoBlueprintProvider,
)
from crypto_trading_bot.demo_endurance.outcome import (
    default_recommended_next_action,
    Demo30MinOutcome,
    Demo30MinVerdict,
)
from crypto_trading_bot.demo_endurance.plan import Demo30MinPlan
from crypto_trading_bot.demo_endurance.stage import DemoEnduranceStage
from crypto_trading_bot.demo_session_execution.outcome import (
    RecommendedNextAction,
)


DEFAULT_CYCLE_INTERVAL_SECONDS = 60.0
MIN_TTL_SECONDS_BEFORE_ORDER = 15
API_FAILURE_STRIKES_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Demo30MinRealRunner
# ---------------------------------------------------------------------------

@dataclass
class _RunnerState:
    elapsed_minutes: int = 0
    cycles_completed: int = 0
    orders_submitted: int = 0
    orders_filled: int = 0
    open_positions_count: int = 0
    open_orders_count: int = 0
    conditional_orders_count: int = 0
    current_position_qty: float = 0.0
    sl_attached: Optional[bool] = None
    tp_attached: Optional[bool] = None
    safety_state: str = "normal"
    risk_violations_count: int = 0
    safety_events_count: int = 0
    manual_review_required: bool = False
    safety_halt_recommended: bool = False
    api_failure_strikes: int = 0
    notes: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []


class Demo30MinRealRunner:
    """Runner real (gated) para demo endurance 30 min FASE 27.

    apply_demo_real=True instrui o runner a passar dry_run=False ao
    execute_demo_session_gated quando uma ordem for aprovada. Default
    apply_demo_real=False mantem todo o pipeline em dry-run gated.
    """

    def __init__(
        self,
        *,
        plan: Demo30MinPlan,
        provider: LiveDemoBlueprintProvider,
        risk_engine,
        safety_machine,
        mode_guard,
        provider_registry,
        effective_risk_config,
        profile,
        operator_token: str,
        market_data_callable: Callable[..., List[Any]],
        feature_engine_factory: Optional[Callable[[], Any]] = None,
        strategy_factory: Optional[Callable[[], Any]] = None,
        demo_executor_factory: Optional[Callable[[], Any]] = None,
        gate_callable: Optional[Callable[..., Any]] = None,
        post_session_check_callable: Optional[
            Callable[..., Any]
        ] = None,
        session_plan_factory: Optional[
            Callable[..., Any]
        ] = None,
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        cycle_interval_seconds: float = DEFAULT_CYCLE_INTERVAL_SECONDS,
        apply_demo_real: bool = False,
        allow_short: bool = False,
        notes: str = "",
        telemetry_recorder: Optional[Any] = None,
    ) -> None:
        if not isinstance(plan, Demo30MinPlan):
            raise TypeError("plan deve ser Demo30MinPlan")
        if not isinstance(provider, LiveDemoBlueprintProvider):
            raise TypeError("provider deve ser LiveDemoBlueprintProvider")
        if plan.max_orders != 1:
            raise ValueError(
                "FASE 27 exige plan.max_orders == 1; "
                f"recebido {plan.max_orders}"
            )
        if not callable(market_data_callable):
            raise TypeError("market_data_callable deve ser callable")
        if not isinstance(operator_token, str) or not operator_token.strip():
            raise ValueError("operator_token deve ser nao-vazio")

        self._plan = plan
        self._provider = provider
        self._risk_engine = risk_engine
        self._safety_machine = safety_machine
        self._mode_guard = mode_guard
        self._provider_registry = provider_registry
        self._effective_risk_config = effective_risk_config
        self._profile = profile
        self._operator_token = operator_token
        self._market_data_callable = market_data_callable
        self._feature_engine_factory = feature_engine_factory
        self._strategy_factory = strategy_factory
        self._demo_executor_factory = demo_executor_factory
        self._gate_callable = gate_callable
        self._post_session_check_callable = post_session_check_callable
        self._session_plan_factory = session_plan_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or (lambda s: None)
        self._cycle_interval_seconds = float(cycle_interval_seconds)
        self._apply_demo_real = bool(apply_demo_real)
        # FASE 29.x - aprovacao explicita do operador para SELL/SHORT
        # real. Default False = long-only (mesmo com advisor pesquisando
        # short). O envvar ENV_ALLOW_SHORT eh checado em conjunto.
        self._allow_short = bool(allow_short)
        self._notes = notes
        # FASE 28 - telemetria opcional. Default None preserva FASE 27.
        self._telemetry = telemetry_recorder

    # ------------------------------------------------------------------ run

    def run_real(self) -> Demo30MinOutcome:
        """Executa o loop FASE 27.

        Retorna Demo30MinOutcome (mode='real_endurance'). Em condicoes
        de erro/early-abort, retorna outcome com verdict apropriado em
        vez de lancar excecao para fora.
        """
        started_at = self._tznow()
        state = _RunnerState()
        latest_snapshot: Optional[LiveBlueprintSnapshot] = None

        self._emit(
            "session_start",
            session_id=self._plan.session_id,
            stage=self._plan.stage.value,
            mode="real_endurance",
            provider=self._plan.provider_id,
            environment=self._plan.environment,
            endpoint_type=self._plan.endpoint_type,
            symbol=self._plan.symbol,
            strategy_name=self._plan.strategy_name,
            max_orders=int(self._plan.max_orders),
            max_session_minutes=int(self._plan.max_session_minutes),
            apply_demo_real=bool(self._apply_demo_real),
            started_at=started_at.isoformat(),
        )

        # 1. Preflight inicial - se falhar, NOT_EXECUTABLE.
        try:
            latest_snapshot = self._provider.preflight()
        except LiveDemoBlueprintError as e:
            return self._build_outcome(
                started_at=started_at,
                ended_at=self._tznow(),
                state=state,
                verdict=Demo30MinVerdict.NOT_EXECUTABLE,
                outcome_reason=(
                    "live preflight failed: " + str(e)[:160]
                ),
                blockers=("live_preflight_failed",),
                latest_snapshot=None,
                demo_session_snapshot=None,
                post_check_snapshot=None,
            )

        # Atualiza state inicial a partir do snapshot.
        bp = latest_snapshot.blueprint
        state.open_positions_count = int(bp.open_positions_count)
        state.open_orders_count = int(bp.open_orders_count)
        state.conditional_orders_count = int(bp.conditional_orders_count)
        state.notes.append(
            f"initial_preflight_id={latest_snapshot.blueprint_id}"
        )
        self._emit(
            "preflight_done",
            blueprint_id=latest_snapshot.blueprint_id,
            ttl_seconds=int(latest_snapshot.ttl_seconds),
            open_positions_count=int(bp.open_positions_count),
            open_orders_count=int(bp.open_orders_count),
            conditional_orders_count=int(bp.conditional_orders_count),
            wallet_balance_usd=float(bp.wallet_balance_usd),
            side=bp.side,
        )

        # 2. Loop principal limitado a max_session_minutes.
        max_minutes = int(self._plan.max_session_minutes)
        cycle_secs = max(1.0, self._cycle_interval_seconds)
        max_cycles = max(1, int((max_minutes * 60.0) / cycle_secs))

        demo_session_snapshot = None
        post_check_snapshot = None
        verdict_after_order: Optional[Demo30MinVerdict] = None
        order_outcome_reason = ""

        for cycle_idx in range(max_cycles):
            state.cycles_completed = cycle_idx + 1
            self._emit(
                "cycle_start", cycle_idx=cycle_idx,
                elapsed_cycles=int(state.cycles_completed),
                open_positions_count=int(state.open_positions_count),
                open_orders_count=int(state.open_orders_count),
                safety_state=state.safety_state,
            )

            # 2a. Safety gates por ciclo.
            if self._safety_machine is not None and \
                    getattr(self._safety_machine,
                            "requires_operator_ack", False):
                state.safety_halt_recommended = True
                state.safety_events_count += 1
                state.notes.append("safety_halt_during_session")
                self._emit(
                    "safety_event", cycle_idx=cycle_idx,
                    new_safety_state=state.safety_state,
                    halt_recommended=True,
                )
                return self._build_outcome(
                    started_at=started_at,
                    ended_at=self._tznow(),
                    state=state,
                    verdict=Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED,
                    outcome_reason=(
                        "safety machine requires operator ack mid-session"
                    ),
                    blockers=("safety_halt",),
                    latest_snapshot=latest_snapshot,
                    demo_session_snapshot=demo_session_snapshot,
                    post_check_snapshot=post_check_snapshot,
                )

            # 2b. Limite de ordem ja atingido -> sai do loop sem nova ordem.
            if state.orders_submitted >= self._plan.max_orders:
                break

            # 2c. Market data + strategy + risk.
            signal, signal_error = self._fetch_signal()
            if signal_error is not None:
                state.api_failure_strikes += 1
                state.notes.append(f"api_failure[{state.api_failure_strikes}]")
                self._emit(
                    "api_failure", cycle_idx=cycle_idx,
                    strike_count=int(state.api_failure_strikes),
                    error_type=type(signal_error).__name__,
                    error_message=str(signal_error),
                )
                if state.api_failure_strikes >= API_FAILURE_STRIKES_THRESHOLD:
                    state.manual_review_required = True
                    return self._build_outcome(
                        started_at=started_at,
                        ended_at=self._tznow(),
                        state=state,
                        verdict=Demo30MinVerdict.MANUAL_REVIEW_REQUIRED,
                        outcome_reason=(
                            f"api read-only failed {state.api_failure_strikes}"
                            " times consecutively"
                        ),
                        blockers=("api_failures_consecutive",),
                        latest_snapshot=latest_snapshot,
                        demo_session_snapshot=demo_session_snapshot,
                        post_check_snapshot=post_check_snapshot,
                    )
                self._sleep(cycle_secs)
                continue
            # Reset strikes apos sucesso.
            state.api_failure_strikes = 0

            if signal is None or not getattr(signal, "is_actionable", False):
                # HOLD ou sinal nao-acionavel - emite snapshot RICO
                # (FASE 29.x): explica POR QUE ficou em HOLD.
                self._emit(
                    "signal_evaluated", cycle_idx=cycle_idx,
                    signal_action="hold", actionable=False,
                    **_signal_snapshot_fields(signal),
                )
                self._sleep(cycle_secs)
                continue
            self._emit(
                "signal_evaluated", cycle_idx=cycle_idx,
                signal_action=str(getattr(
                    getattr(signal, "action", None), "value",
                    "actionable",
                )),
                actionable=True,
                **_signal_snapshot_fields(signal),
            )

            # 2c-bis. FASE 29.x - gate ADICIONAL SELL/SHORT (long-only
            # por default). BUY passa trivialmente; SELL exige
            # ENV_ALLOW_SHORT=true + aprovacao explicita do operador.
            signal_side = str(getattr(
                getattr(signal, "action", None), "value", "",
            )).strip().lower()
            from crypto_trading_bot.demo_endurance.gates_phase29 import (
                validate_phase29_short_gate,
            )
            short_gate = validate_phase29_short_gate(
                signal_side=signal_side,
                operator_confirmed_short=self._allow_short,
                operator_token=self._operator_token,
            )
            self._emit(
                "phase29_short_gate_checked", cycle_idx=cycle_idx,
                signal_side=signal_side,
                approved=bool(short_gate.approved),
                blockers=list(short_gate.blockers),
            )
            if not short_gate.approved:
                # Bloqueia SELL real; mantem sessao long-only sem abortar.
                state.notes.append("short_blocked_long_only")
                self._sleep(cycle_secs)
                continue

            # 2d. RiskEngine valida.
            trading_signal = signal.to_trading_signal()
            risk_result = self._risk_engine.validate_signal(trading_signal)
            if not getattr(risk_result, "approved", False):
                state.risk_violations_count += 1
                state.notes.append("risk_blocked")
                self._emit(
                    "risk_validated", cycle_idx=cycle_idx,
                    approved=False,
                    reason=str(getattr(risk_result, "reason", ""))[:160],
                )
                self._sleep(cycle_secs)
                continue
            self._emit(
                "risk_validated", cycle_idx=cycle_idx, approved=True,
            )

            # 2e. Garante TTL fresco antes da ordem (ajuste obrigatorio 1).
            previous_bp_id = latest_snapshot.blueprint_id if \
                latest_snapshot else None
            try:
                latest_snapshot = self._provider.ensure_fresh(
                    threshold_seconds=max(
                        MIN_TTL_SECONDS_BEFORE_ORDER,
                        LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS,
                    ),
                    now=self._tznow(),
                )
            except LiveDemoBlueprintError as e:
                state.manual_review_required = True
                return self._build_outcome(
                    started_at=started_at,
                    ended_at=self._tznow(),
                    state=state,
                    verdict=Demo30MinVerdict.FAILED,
                    outcome_reason=(
                        "ensure_fresh failed before order: " + str(e)[:160]
                    ),
                    blockers=("ensure_fresh_failed",),
                    latest_snapshot=latest_snapshot,
                    demo_session_snapshot=demo_session_snapshot,
                    post_check_snapshot=post_check_snapshot,
                )

            self._emit(
                "ensure_fresh_called", cycle_idx=cycle_idx,
                was_stale=(
                    previous_bp_id != latest_snapshot.blueprint_id
                ),
                new_blueprint_id=latest_snapshot.blueprint_id,
                new_ttl_seconds=int(latest_snapshot.ttl_seconds),
            )

            # 2f. Re-checa flat start (defesa em profundidade).
            bp_fresh = latest_snapshot.blueprint
            if bp_fresh.open_positions_count > 0 \
                    or bp_fresh.open_orders_count > 0:
                state.manual_review_required = True
                state.notes.append("non_flat_state_after_refresh")
                return self._build_outcome(
                    started_at=started_at,
                    ended_at=self._tznow(),
                    state=state,
                    verdict=Demo30MinVerdict.MANUAL_REVIEW_REQUIRED,
                    outcome_reason=(
                        "non-flat state after refresh; "
                        f"positions={bp_fresh.open_positions_count} "
                        f"orders={bp_fresh.open_orders_count}"
                    ),
                    blockers=("non_flat_after_refresh",),
                    latest_snapshot=latest_snapshot,
                    demo_session_snapshot=demo_session_snapshot,
                    post_check_snapshot=post_check_snapshot,
                )

            # 2g. Chama gate (no maximo 1 vez).
            self._emit(
                "gate_invoked", cycle_idx=cycle_idx,
                dry_run=(not self._apply_demo_real),
                confirm_demo_session=True,
                blueprint_id=latest_snapshot.blueprint_id,
            )
            try:
                demo_outcome = self._invoke_gate(
                    trading_signal=trading_signal,
                    latest_snapshot=latest_snapshot,
                )
            except Exception as e:  # noqa: BLE001
                state.notes.append(
                    f"gate_exception:{type(e).__name__}"
                )
                return self._build_outcome(
                    started_at=started_at,
                    ended_at=self._tznow(),
                    state=state,
                    verdict=Demo30MinVerdict.FAILED,
                    outcome_reason=(
                        f"gate exception: {type(e).__name__}: "
                        f"{str(e)[:120]}"
                    ),
                    blockers=("gate_exception",),
                    latest_snapshot=latest_snapshot,
                    demo_session_snapshot=demo_session_snapshot,
                    post_check_snapshot=post_check_snapshot,
                )

            state.orders_submitted = 1
            demo_session_snapshot = _safe_to_dict(demo_outcome)

            # 2h. Atualiza state com outcome do gate.
            self._absorb_gate_outcome(state, demo_outcome)

            # 2i. post_session_check stage='after_entry' obrigatorio.
            post_check_snapshot = self._maybe_post_check(
                stage="after_entry",
                expected_qty=float(bp_fresh.qty),
            )
            self._absorb_post_check(state, post_check_snapshot)
            if post_check_snapshot is not None:
                self._emit(
                    "post_check_done", cycle_idx=cycle_idx,
                    stage="after_entry",
                    success=bool(post_check_snapshot.get("success", False)),
                    sl_attached=post_check_snapshot.get("sl_attached"),
                    tp_attached=post_check_snapshot.get("tp_attached"),
                    requires_manual_review=bool(
                        post_check_snapshot.get(
                            "requires_manual_review", False,
                        )
                    ),
                )

            # 2j. Determina verdict baseado em demo_outcome + post_check.
            verdict_after_order = self._resolve_verdict_after_order(
                state, demo_outcome, post_check_snapshot,
            )
            order_outcome_reason = self._build_order_reason(
                state, demo_outcome, post_check_snapshot,
            )
            # Sai do loop apos ordem (1 ordem por sessao).
            break

        # 3. Fim da janela / fim do loop.
        ended_at = self._tznow()

        # Caso A: nenhuma ordem foi submetida -> PASSED_ZERO_TRADES seguro.
        if state.orders_submitted == 0:
            return self._build_outcome(
                started_at=started_at,
                ended_at=ended_at,
                state=state,
                verdict=Demo30MinVerdict.PASSED_ZERO_TRADES,
                outcome_reason=(
                    f"no signal approved in {state.cycles_completed} cycles "
                    f"({max_minutes} min window); zero trades is valid"
                ),
                blockers=(),
                latest_snapshot=latest_snapshot,
                demo_session_snapshot=demo_session_snapshot,
                post_check_snapshot=post_check_snapshot,
            )

        # Caso B: ordem foi submetida, verdict_after_order ja resolvido.
        # Roda flat_check se posicao parece flat. Se ainda aberta,
        # mantem verdict + recommended_next_action conservador.
        final_post_check = post_check_snapshot
        if state.open_positions_count == 0:
            flat_check = self._maybe_post_check(
                stage="flat_check", expected_qty=0.0,
            )
            if flat_check is not None:
                final_post_check = flat_check
                self._absorb_post_check(state, flat_check)
                # Se flat_check apontar residual, downgrade para review.
                if state.manual_review_required and \
                        verdict_after_order != \
                        Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED:
                    verdict_after_order = (
                        Demo30MinVerdict.MANUAL_REVIEW_REQUIRED
                    )

        return self._build_outcome(
            started_at=started_at,
            ended_at=ended_at,
            state=state,
            verdict=verdict_after_order or Demo30MinVerdict.FAILED,
            outcome_reason=order_outcome_reason or "order processed",
            blockers=(),
            latest_snapshot=latest_snapshot,
            demo_session_snapshot=demo_session_snapshot,
            post_check_snapshot=final_post_check,
        )

    # ------------------------------------------------------------- helpers

    def _tznow(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now

    def _emit(self, event_type: str, *, cycle_idx=None, **snapshot):
        """FASE 28 - emite telemetria se recorder injetado.

        NUNCA propaga excecao do recorder ao caller. Se recorder
        falhar, ignora silenciosamente (telemetria nao pode mascarar
        ou interromper safety/execucao do runner).
        """
        if self._telemetry is None:
            return
        try:
            self._telemetry.record(
                event_type, cycle_idx=cycle_idx, snapshot=snapshot,
            )
        except Exception:  # noqa: BLE001
            pass

    def _fetch_signal(self):
        """Roda market_data + features + strategy. Retorna (signal, err)."""
        try:
            candles = self._market_data_callable(
                symbol=self._plan.symbol,
                timeframe="15",
                limit=200,
            )
        except Exception as e:  # noqa: BLE001
            return None, e
        if not candles:
            return None, RuntimeError("empty candles")
        # Lazy default factories
        if self._feature_engine_factory is None:
            from crypto_trading_bot.data.feature_engine import FeatureEngine
            feature_engine = FeatureEngine()
        else:
            feature_engine = self._feature_engine_factory()
        if self._strategy_factory is None:
            from crypto_trading_bot.challenge_readiness.strategy_factory \
                import build_strategy_spec
            spec = build_strategy_spec(self._plan.strategy_name)
            strategy = spec.factory(dict(spec.default_config))
            if hasattr(strategy, "set_running"):
                strategy.set_running()
        else:
            strategy = self._strategy_factory()
        try:
            features = feature_engine.compute(candles)
            features["symbol"] = self._plan.symbol
            signal = strategy.evaluate(features)
        except Exception as e:  # noqa: BLE001
            return None, e
        return signal, None

    def _invoke_gate(self, *, trading_signal, latest_snapshot):
        """Constroi DemoSessionPlan + chama execute_demo_session_gated 1x.

        session_plan_factory eh INJETAVEL para testes. Default:
        constroi via FASE 22 SignalBlueprint + DemoSessionPlan reais.
        """
        plan_id = "DEMO30M-R-" + uuid.uuid4().hex[:12].upper()
        if self._session_plan_factory is not None:
            session_plan = self._session_plan_factory(
                plan_id=plan_id,
                live_snapshot=latest_snapshot,
                trading_signal=trading_signal,
                runner_plan=self._plan,
                profile=self._profile,
                effective_risk_config=self._effective_risk_config,
                now=self._tznow(),
            )
        else:
            session_plan = self._default_build_session_plan(
                plan_id=plan_id,
                latest_snapshot=latest_snapshot,
            )

        # Lazy import do gate default (substituido em testes via
        # self._gate_callable injetado pela CLI ou pelo teste).
        if self._gate_callable is None:
            from crypto_trading_bot.demo_session_execution.gate import (
                execute_demo_session_gated as _default_gate,
            )
            gate = _default_gate
        else:
            gate = self._gate_callable

        executor = self._instantiate_executor()
        post_check_fn = self._build_post_check_callable(executor)

        outcome = gate(
            session_plan,
            risk_engine=self._risk_engine,
            demo_executor=executor,
            safety_machine=self._safety_machine,
            mode_guard=self._mode_guard,
            provider_registry=self._provider_registry,
            operator_token=self._operator_token,
            confirm_demo_session=True,
            dry_run=(not self._apply_demo_real),
            notes=self._notes[:200],
            post_session_check_fn=post_check_fn,
            now=self._tznow(),
        )
        return outcome

    def _default_build_session_plan(self, *, plan_id, latest_snapshot):
        """Default: constroi DemoSessionPlan FASE 22 via builders reais.

        Lazy imports. Usado em producao via CLI quando wiring real eh
        habilitado explicitamente. Testes podem injetar
        session_plan_factory para evitar dependencia em
        DemoSessionReadinessCheck real.
        """
        from crypto_trading_bot.demo_session_execution.plan import (
            BlueprintSide, SignalBlueprint, build_demo_session_plan,
        )
        from crypto_trading_bot.demo_session_readiness.readiness_check \
            import DemoSessionReadinessCheck

        bp_fresh = latest_snapshot.blueprint
        side_enum = (
            BlueprintSide.BUY if bp_fresh.side == "buy"
            else BlueprintSide.SELL
        )
        sig_blueprint = SignalBlueprint(
            symbol=self._plan.symbol,
            side=side_enum,
            entry_price=float(bp_fresh.entry_price),
            stop_loss=float(bp_fresh.stop_loss),
            take_profit=float(bp_fresh.take_profit),
            position_size_usd=float(bp_fresh.notional_usd),
            strategy_name=self._plan.strategy_name,
            leverage=1.0,
        )
        readiness_check = DemoSessionReadinessCheck(
            profile=self._profile,
            effective_risk_config=self._effective_risk_config,
            provider_id="bybit_demo_linear",
            now=self._tznow(),
        )
        readiness_report = readiness_check.evaluate()
        return build_demo_session_plan(
            plan_id=plan_id,
            readiness_report=readiness_report,
            profile=self._profile,
            blueprint=sig_blueprint,
            effective_risk_config=self._effective_risk_config,
            risk_snapshot=None,
            now=self._tznow(),
        )

    def _instantiate_executor(self):
        if self._demo_executor_factory is not None:
            return self._demo_executor_factory()
        # Sem factory injetada: producao usaria BybitDemoExecutor real.
        # Para esta FASE 27, exigir factory injetada quando apply_demo_real
        # eh True simplifica os testes (forca operador/teste a fornecer
        # explicitamente). Em producao real, CLI injeta executor real.
        raise RuntimeError(
            "demo_executor_factory eh obrigatorio quando gate eh invocado; "
            "CLI deve fornecer factory que instancia BybitDemoExecutor "
            "real (apenas com triple-lock + flags)."
        )

    def _build_post_check_callable(self, executor):
        """Wrapper que chama post_session_check(stage='after_entry'...)."""
        if self._post_session_check_callable is not None:
            return lambda: self._post_session_check_callable(
                executor, stage="after_entry",
            )
        if executor is None or not hasattr(executor, "post_session_check"):
            return None
        plan = self._plan

        def _call():
            try:
                return executor.post_session_check(
                    symbol=plan.symbol,
                    dry_run=(not self._apply_demo_real),
                    stage="after_entry",
                    expected_qty=float(
                        plan.planned_blueprint.qty
                    ),
                    require_sl=True,
                    require_tp=True,
                )
            except Exception as e:  # noqa: BLE001
                return {
                    "operation": "post_session_check",
                    "stage": "after_entry",
                    "success": False,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:160],
                }

        return _call

    def _maybe_post_check(self, *, stage: str, expected_qty: float):
        """Roda post_session_check standalone (after_entry/flat_check)."""
        if self._post_session_check_callable is not None:
            try:
                result = self._post_session_check_callable(
                    None, stage=stage,
                )
                return _safe_to_dict(result)
            except Exception as e:  # noqa: BLE001
                return {
                    "operation": "post_session_check",
                    "stage": stage, "success": False,
                    "error_type": type(e).__name__,
                    "error_message": str(e)[:160],
                }
        # Sem callable injetado: skip (a chamada via gate ja fez a
        # invocacao da execucao). Retorna None para clareza.
        return None

    def _absorb_gate_outcome(self, state: _RunnerState, outcome) -> None:
        if outcome is None:
            return
        if getattr(outcome, "executor_success", False):
            state.orders_filled = 1
        if getattr(outcome, "requires_manual_review", False):
            state.manual_review_required = True
        if getattr(outcome, "safety_halt_recommended", False):
            state.safety_halt_recommended = True
        final_safety = str(
            getattr(outcome, "final_safety_state", "normal") or "normal"
        )
        state.safety_state = final_safety
        if final_safety != "normal":
            state.safety_events_count += 1

    def _absorb_post_check(self, state: _RunnerState, snapshot) -> None:
        if snapshot is None or not isinstance(snapshot, dict):
            return
        if snapshot.get("success") is False:
            state.manual_review_required = True
        # Counters do executor (se publicados via to_dict do
        # DemoExecutionResult).
        positions = snapshot.get("position_snapshot") \
            or snapshot.get("positions") or []
        # Heuristica defensiva: se result reportar non-flat, manual review.
        if isinstance(positions, list) and positions:
            state.open_positions_count = max(
                state.open_positions_count, len(positions),
            )
        sl_attached = snapshot.get("sl_attached")
        tp_attached = snapshot.get("tp_attached")
        if sl_attached is not None:
            state.sl_attached = bool(sl_attached)
        if tp_attached is not None:
            state.tp_attached = bool(tp_attached)
        if snapshot.get("requires_manual_review") is True:
            state.manual_review_required = True

    def _resolve_verdict_after_order(
        self, state: _RunnerState, demo_outcome, post_check_snapshot,
    ) -> Demo30MinVerdict:
        if state.safety_halt_recommended:
            return Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED
        if state.manual_review_required:
            return Demo30MinVerdict.MANUAL_REVIEW_REQUIRED
        # Sucesso canonical da FASE 22.
        is_canonical = bool(
            getattr(demo_outcome, "is_filled_canonical", False)
        )
        if is_canonical and state.orders_filled == 1:
            return Demo30MinVerdict.PASSED_ONE_TRADE
        if getattr(demo_outcome, "executor_called", False) and not \
                getattr(demo_outcome, "executor_success", False):
            return Demo30MinVerdict.FAILED
        # Caso defensivo: gate chamou mas resultado ambíguo.
        return Demo30MinVerdict.MANUAL_REVIEW_REQUIRED

    def _build_order_reason(
        self, state: _RunnerState, demo_outcome, post_check_snapshot,
    ) -> str:
        reason = getattr(demo_outcome, "outcome_reason", "") or ""
        filled = state.orders_filled
        positions = state.open_positions_count
        return (
            f"order_submitted=1 filled={filled} open_positions={positions}; "
            f"gate_reason={reason[:120]}"
        )

    def _build_outcome(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
        state: _RunnerState,
        verdict: Demo30MinVerdict,
        outcome_reason: str,
        blockers: tuple,
        latest_snapshot: Optional[LiveBlueprintSnapshot],
        demo_session_snapshot: Optional[dict],
        post_check_snapshot: Optional[dict],
    ) -> Demo30MinOutcome:
        bp = self._plan.planned_blueprint
        rec = default_recommended_next_action(verdict)
        # AJUSTE OBRIGATORIO 3: posicao aberta no fim NUNCA permite
        # READY_FOR_NEXT_DEMO_SESSION. Sobre escreve o mapping default.
        if state.open_positions_count > 0:
            rec = RecommendedNextAction.MANUAL_REVIEW_REQUIRED
        elapsed_seconds = max(
            0.0, (ended_at - started_at).total_seconds(),
        )
        elapsed_minutes = int(elapsed_seconds / 60.0)
        live_bp_id = (
            latest_snapshot.blueprint_id if latest_snapshot else None
        )
        self._emit(
            "session_end",
            verdict=verdict.value,
            recommended_next_action=rec.value,
            orders_submitted=int(state.orders_submitted),
            orders_filled=int(state.orders_filled),
            open_positions_count=int(state.open_positions_count),
            ended_at=ended_at.isoformat(),
            duration_seconds=float(elapsed_seconds),
            apply_demo_real_invoked=bool(self._apply_demo_real),
            live_blueprint_id=live_bp_id,
        )
        return Demo30MinOutcome(
            stage=DemoEnduranceStage.DEMO_30_MIN,
            mode="real_endurance",
            session_id=self._plan.session_id,
            provider_id=self._plan.provider_id,
            environment=self._plan.environment,
            symbol=self._plan.symbol,
            strategy_name=self._plan.strategy_name,
            max_session_minutes=int(self._plan.max_session_minutes),
            elapsed_minutes=elapsed_minutes,
            cycles_completed=int(state.cycles_completed),
            max_orders=int(self._plan.max_orders),
            orders_planned=1,
            orders_submitted=int(state.orders_submitted),
            orders_filled=int(state.orders_filled),
            open_positions_count=int(state.open_positions_count),
            open_orders_count=int(state.open_orders_count),
            conditional_orders_count=int(state.conditional_orders_count),
            current_position_qty=float(state.current_position_qty),
            sl_attached=state.sl_attached,
            tp_attached=state.tp_attached,
            risk_pct_planned=float(bp.risk_pct),
            notional_usd_planned=float(bp.notional_usd),
            wallet_balance_usd=float(bp.wallet_balance_usd),
            safety_state=state.safety_state,
            risk_violations_count=int(state.risk_violations_count),
            safety_events_count=int(state.safety_events_count),
            manual_review_required=bool(state.manual_review_required),
            safety_halt_recommended=bool(state.safety_halt_recommended),
            verdict=verdict,
            recommended_next_action=rec,
            outcome_reason=outcome_reason[:200],
            blockers=tuple(blockers),
            warnings=(),
            notes=("; ".join(state.notes))[:200],
            started_at=started_at,
            ended_at=ended_at,
            live_blueprint_id=live_bp_id,
            apply_demo_real_invoked=bool(self._apply_demo_real),
            demo_session_outcome_snapshot=demo_session_snapshot,
            post_session_check_summary=post_check_snapshot,
        )


def _safe_to_dict(obj: Any) -> Optional[dict]:
    """Converte obj em dict sanitizado se possivel; senao None."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return dict(obj)
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            if isinstance(d, dict):
                return d
        except Exception:
            return None
    return None


# Campos ricos extraidos de signal.metadata para telemetria
# signal_evaluated (FASE 29.x - observabilidade BUY/SELL/HOLD).
# Sao SUBSET seguro: apenas valores tecnicos/decisao, nunca secrets.
_SIGNAL_SNAPSHOT_KEYS = (
    "strategy_name", "strategy_id", "symbol",
    "ema_fast_period", "ema_slow_period",
    "ema_fast_value", "ema_slow_value",
    "rsi_period", "rsi_value",
    "rsi_long_overbought", "rsi_short_oversold", "rsi_overbought",
    "atr_period", "atr_value",
    "last_close", "last_high", "last_low", "last_volume",
    "min_candles_required", "candles_available",
    "has_open_position",
    "uptrend", "downtrend",
    "pullback_zone", "pullback_zone_long", "pullback_zone_short",
    "rsi_ok", "rsi_ok_long", "rsi_ok_short",
    "no_position", "data_quality_ok",
    "direction", "signal_side", "selected_direction",
    "rejected_direction_reason",
    "hold_reason",
    # FASE 36 pos-demo 3 - diagnostico SL x piso de risco (aditivo).
    "planned_sl_pct", "min_sl_pct_required", "sl_gap_to_min_pct",
    "risk_rejection_category",
    "failed_conditions", "failed_conditions_long",
    "failed_conditions_short",
    "long_conditions", "short_conditions",
)


def _signal_snapshot_fields(signal: Any) -> dict:
    """Extrai campos ricos de signal.metadata para signal_evaluated.

    Funciona com QUALQUER estrategia: as que populam metadata (ex.
    trend_pullback_bidirectional) fornecem o quadro completo; as que
    nao populam resultam em snapshot parcial (sem erro). Sanitizacao
    final eh feita pelo SessionTelemetryRecorder.
    """
    meta = getattr(signal, "metadata", None)
    if not isinstance(meta, dict):
        # Fallback minimo: reason do HOLD se existir.
        reason = getattr(signal, "reason", None)
        return {"hold_reason": reason} if reason else {}
    out = {}
    for key in _SIGNAL_SNAPSHOT_KEYS:
        if key in meta:
            out[key] = meta[key]
    # Garante hold_reason via reason do signal se metadata nao trouxe.
    if "hold_reason" not in out:
        reason = getattr(signal, "reason", None)
        if reason:
            out["hold_reason"] = reason
    return out
