"""
DemoEnduranceRunner (FASE 30) - demo real-time curta/longa, wired dry-run
==========================================================================
Runner multi-order-ready com prazo definido (DurationSpec) e espera
REAL entre ciclos quando real_time=True.

⚠️  FASE 30 = WIRED DRY-RUN:
    - gate SEMPRE dry_run=True;
    - orders_submitted = 0 SEMPRE;
    - would_orders >= 0 (contabilizacao de ordem possivel);
    - NENHUMA ordem real.

⚠️  SLEEP (causa-raiz da FASE anterior corrigida):
    - real_time=True  -> sleep REAL (time.sleep) injetado por default;
    - real_time=False -> no-op INTENCIONAL (time-compressed explicito);
    - testes injetam fake sleep + mock clock (nunca sleep real).
    O modo fica registrado em real_time_mode/time_compressed no outcome.

⚠️  FLUXO OFICIAL POR CICLO (prediction ANTES da IA):
    market data -> prediction context (opt) -> features -> strategy ->
    signal -> RiskEngine -> AI support (opt) -> gates independentes ->
    gate dry_run=True -> would-order -> telemetry -> sleep.

⚠️  GATES INDEPENDENTES (nenhum implica outro):
    - short:        DEMO_30_MIN_ALLOW_SHORT_PHASE29_ENABLED (FASE 29.x)
    - multi-order:  DEMO_ALLOW_MULTI_ORDER_PER_SESSION
    - AI man.rev.:  DEMO_ALLOW_AI_MANUAL_REVIEW (decision_support)
    - prediction:   ENABLE_PREDICTION_MARKET_CONTEXT
    Perfil permite; gate ENV habilita; ambos necessarios.

⚠️  RiskEngine permanece soberano. Limites do EnduranceLimits sao
    tetos ADICIONAIS. Perfil NUNCA eh ignorado (nada hardcoded).
"""

from __future__ import annotations

import os
import time as _time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from crypto_trading_bot.decision_trace import (
    FinalDecision,
    build_trace_entry,
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


ENV_ALLOW_MULTI_ORDER = "DEMO_ALLOW_MULTI_ORDER_PER_SESSION"
ENV_PREDICTION_CONTEXT = "ENABLE_PREDICTION_MARKET_CONTEXT"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("true", "1", "yes")


class DemoEnduranceRunner:
    """Runner de demo endurance com prazo definido (FASE 30).

    Tudo injetavel para testes offline (fake clock/sleep, mocks de
    market data, strategy, risk, gate, prediction, IA).

    Args principais:
        profile: OperationalProfile resolvido (FASE 31). Fonte de
            permissoes; nada hardcoded.
        duration: DurationSpec (minutos XOR dias).
        limits: EnduranceLimits (tetos adicionais).
        symbol/strategy_name: validados contra o perfil.
        market_data_callable(symbol, timeframe, limit) -> candles.
        feature_engine: objeto com compute(candles) -> features.
        strategy: objeto com evaluate(features) -> StrategySignal.
        risk_engine: RiskEngine real (soberano).
        gate_callable(**kw) -> outcome dry-run (SEMPRE dry_run=True
            nesta fase). None = contabiliza would-order sem gate
            (simulacao offline pura).
        flat_check_callable() -> dict com is_flat/positions... (opt).
        prediction_context_provider() -> PredictionMarketContext (opt).
        ai_decision_support: AIDecisionSupport (opt).
        real_time: True -> sleep real entre ciclos (default
            time.sleep); False -> time-compressed (no-op intencional).
        clock/sleep: injecao para testes (fake clock + fake sleep).
    """

    def __init__(
        self,
        *,
        profile: Any,
        duration: DurationSpec,
        limits: EnduranceLimits,
        symbol: str,
        strategy_name: str,
        operator_token: str,
        market_data_callable: Callable[..., Any],
        feature_engine: Any,
        strategy: Any,
        risk_engine: Any,
        gate_callable: Optional[Callable[..., Any]] = None,
        flat_check_callable: Optional[Callable[[], dict]] = None,
        prediction_context_provider: Optional[
            Callable[[], Any]
        ] = None,
        ai_decision_support: Optional[Any] = None,
        telemetry_recorder: Optional[Any] = None,
        real_time: bool = False,
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        session_id: Optional[str] = None,
        notes: str = "",
        continue_after_would_order: bool = False,
        max_would_orders: Optional[int] = None,
        timeframe: str = "15",
        execute_real_multi: bool = False,
        max_real_orders: Optional[int] = None,
        real_trade_lifecycle: Optional[Any] = None,
        require_flat_before_next_order: bool = True,
    ) -> None:
        if not isinstance(duration, DurationSpec):
            raise TypeError("duration deve ser DurationSpec")
        if not isinstance(limits, EnduranceLimits):
            raise TypeError("limits deve ser EnduranceLimits")
        if not isinstance(operator_token, str) or \
                not operator_token.strip():
            raise ValueError("operator_token deve ser nao-vazio")
        if not callable(market_data_callable):
            raise TypeError("market_data_callable deve ser callable")

        # Perfil eh soberano sobre simbolo/estrategia (FASE 31).
        from crypto_trading_bot.operational_profile.profile_resolver \
            import is_strategy_allowed, is_symbol_allowed
        if not is_symbol_allowed(profile, symbol):
            raise ValueError(
                f"symbol {symbol!r} nao permitido pelo perfil "
                f"{getattr(profile, 'name', '?')!r} "
                f"(allowed={list(getattr(profile, 'allowed_symbols', ()))})"
            )
        if not is_strategy_allowed(profile, strategy_name):
            raise ValueError(
                f"strategy {strategy_name!r} nao permitida pelo perfil "
                f"{getattr(profile, 'name', '?')!r}"
            )

        self._profile = profile
        self._duration = duration
        self._limits = limits
        self._symbol = symbol
        self._strategy_name = strategy_name
        self._operator_token = operator_token
        self._market_data = market_data_callable
        self._feature_engine = feature_engine
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._gate_callable = gate_callable
        self._flat_check_callable = flat_check_callable
        self._prediction_provider = prediction_context_provider
        self._ai_support = ai_decision_support
        self._telemetry = telemetry_recorder
        self._real_time = bool(real_time)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # SLEEP: correcao da causa-raiz. real_time -> time.sleep REAL;
        # time-compressed -> no-op INTENCIONAL e explicito.
        if sleep is not None:
            self._sleep = sleep
        elif self._real_time:
            self._sleep = _time.sleep
        else:
            self._sleep = lambda _s: None  # time-compressed intencional
        self._session_id = session_id or f"endur-{uuid.uuid4().hex[:12]}"
        self._notes = notes
        # MODO OBSERVACAO (dry-run APENAS): continua apos would-order,
        # registrando multiplas oportunidades possiveis SEM abrir
        # posicao, SEM simular execucao e SEM tocar gates reais
        # (nao exige DEMO_ALLOW_MULTI_ORDER_PER_SESSION; nao habilita
        # multi-order real). Este runner FASE 30 opera SEMPRE com gate
        # dry_run=True e orders_submitted=0 por construcao.
        if max_would_orders is not None:
            if not continue_after_would_order:
                raise ValueError(
                    "max_would_orders exige "
                    "continue_after_would_order=True (modo observacao)"
                )
            if int(max_would_orders) < 1:
                raise ValueError(
                    f"max_would_orders deve ser >= 1: {max_would_orders}"
                )
        self._continue_after_would_order = bool(
            continue_after_would_order,
        )
        self._max_would_orders = (
            int(max_would_orders) if max_would_orders is not None
            else None
        )
        self._timeframe = str(timeframe)

        # ===============================================================
        # FASE 30.2 - MODO REAL MULTI-ORDEM SEQUENCIAL.
        # Mutuamente exclusivo com observacao (regras 11-12). Exige
        # real_time, lifecycle injetado, max_real_orders em [1,3] e
        # perfil com allow_multi_order_demo=True. Gates ENV sao
        # validados pela CLI (validate_phase30_2_real_multi_gate);
        # aqui ficam as travas estruturais do runner.
        # ===============================================================
        self._execute_real_multi = bool(execute_real_multi)
        self._max_real_orders = (
            int(max_real_orders) if max_real_orders is not None
            else None
        )
        self._real_trade_lifecycle = real_trade_lifecycle
        self._require_flat_before_next_order = bool(
            require_flat_before_next_order,
        )
        if self._execute_real_multi:
            if self._continue_after_would_order:
                raise ValueError(
                    "execute_real_multi e incompativel com "
                    "continue_after_would_order (observation_mode "
                    "proibido em execucao real - FASE 30.2 regras 11-12)"
                )
            if not self._real_time:
                raise ValueError(
                    "execute_real_multi exige real_time=True"
                )
            if self._max_real_orders is None or not (
                1 <= self._max_real_orders <= 3
            ):
                raise ValueError(
                    "execute_real_multi exige max_real_orders em "
                    f"[1, 3]; recebido {max_real_orders!r}"
                )
            if self._real_trade_lifecycle is None:
                raise ValueError(
                    "execute_real_multi exige real_trade_lifecycle "
                    "injetado (build_real_trade_lifecycle na CLI)"
                )
            if not getattr(profile, "allow_multi_order_demo", False):
                raise ValueError(
                    "perfil "
                    f"{getattr(profile, 'name', '?')!r} nao permite "
                    "multi-order demo (allow_multi_order_demo=False)"
                )

    # ------------------------------------------------------------------

    def _tznow(self) -> datetime:
        now = self._clock()
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)

    def _emit(self, event_type: str, *, cycle_idx=None, **snapshot):
        """Telemetria fail-safe (nunca propaga excecao)."""
        if self._telemetry is None:
            return
        try:
            self._telemetry.record(
                event_type, cycle_idx=cycle_idx, snapshot=snapshot,
            )
        except Exception:  # noqa: BLE001
            pass

    def _effective_max_orders_session(self) -> int:
        """Single-order default; multi-order exige perfil E gate ENV."""
        if (
            getattr(self._profile, "allow_multi_order_demo", False)
            and _env_truthy(ENV_ALLOW_MULTI_ORDER)
        ):
            return int(self._limits.max_orders_per_session)
        return 1

    def _prediction_enabled(self) -> bool:
        """Prediction exige perfil E gate ENV E provider injetado."""
        return (
            self._prediction_provider is not None
            and getattr(
                self._profile, "allow_prediction_market_context", False,
            )
            and getattr(
                self._profile, "prediction_context_mode", "disabled",
            ) != "disabled"
            and _env_truthy(ENV_PREDICTION_CONTEXT)
        )

    # ------------------------------------------------------------------

    def run(self) -> DemoEnduranceOutcome:
        """Executa a demo endurance ate o prazo OU condicao de parada.

        Retorna DemoEnduranceOutcome; nunca propaga excecao de ciclo
        (KeyboardInterrupt vira operator_interrupted).
        """
        started_at = self._tznow()
        deadline = started_at + timedelta(
            seconds=self._duration.total_wall_clock_seconds,
        )
        expected_cycles = self._duration.expected_cycles

        cycles = 0
        signals_evaluated = 0
        would_orders = 0
        api_failures = 0
        api_failure_strikes = 0
        safety_events = 0
        manual_review = False
        ended_reason: Optional[EnduranceEndedReason] = None
        warnings: List[str] = []
        per_trade_records: List[dict] = []
        hourly_snapshots: List[dict] = []
        daily_summaries: List[dict] = []
        last_hour_idx = 0
        last_day_idx = 0
        last_flat_check_elapsed = 0.0
        ai_report_fields: Dict[str, Any] = {"ai_enabled": False}
        prediction_report: Dict[str, Any] = {"enabled": False}

        def _mi_from_prediction(pred):
            """Converte prediction context (FASE 34) em snapshot MI."""
            if not pred:
                return None
            return {
                "sources_used": ["polymarket"],
                "sources_stale": (
                    ["polymarket"] if pred.get("stale") else []
                ),
                "sources_unavailable": [],
                "risk_flags": list(pred.get("risk_flags") or []),
                "inconclusive": False,
            }

        # FASE 36 Bloco A - Decision Trace por decisao.
        decision_traces: List[dict] = []

        def _record_trace(
            *, cycle_idx, final_decision, final_reason,
            signal_snapshot=None, trading_signal=None,
            risk_summary=None, ai_fields=None, mi_snapshot=None,
            gates_approved=(), gates_blocked=(),
            realized_pnl=None, trade_idx=None,
        ):
            try:
                entry = build_trace_entry(
                    cycle_idx=cycle_idx,
                    session_id=self._session_id,
                    final_decision=final_decision,
                    final_reason=final_reason,
                    now=self._tznow(),
                    profile=self._profile,
                    symbol=self._symbol,
                    timeframe=self._timeframe,
                    signal_snapshot=signal_snapshot,
                    trading_signal=trading_signal,
                    risk_summary=risk_summary,
                    ai_report_fields=ai_fields,
                    ai_not_used_reason=(
                        None if ai_fields else (
                            "ai_disabled_by_profile"
                            if not getattr(
                                self._profile,
                                "allow_ai_assistance", False,
                            ) else "ai_not_invoked_this_cycle"
                        )
                    ),
                    mi_snapshot=mi_snapshot,
                    mi_not_used_reason=(
                        None if mi_snapshot
                        else "prediction_context_disabled"
                    ),
                    gates_approved=gates_approved,
                    gates_blocked=gates_blocked,
                    realized_pnl=realized_pnl,
                    trade_idx=trade_idx,
                )
                d = entry.to_dict()
                decision_traces.append(d)
                self._emit(
                    "decision_trace_recorded", cycle_idx=cycle_idx,
                    trace_id=d["trace_id"],
                    final_decision=d["final_decision"],
                    final_reason=d["final_reason"][:160],
                )
            except Exception:  # noqa: BLE001
                # Trace NUNCA derruba o pipeline.
                pass

        # FASE 30.2 - contadores de execucao real sequencial.
        orders_submitted_real = 0
        orders_filled_real = 0
        trades_completed = 0
        trades_closed_by_tp = 0
        trades_closed_by_sl = 0
        trades_closed_by_reduce_only = 0
        trades_manual_review = 0
        total_realized_pnl: Optional[float] = None
        last_flat_passed: Optional[bool] = None

        self._emit(
            "session_start",
            session_id=self._session_id,
            profile_name=getattr(self._profile, "name", "?"),
            symbol=self._symbol,
            strategy_name=self._strategy_name,
            real_time_mode=self._real_time,
            time_compressed=(not self._real_time),
            dry_run=True,
            observation_mode=self._continue_after_would_order,
            max_would_orders=self._max_would_orders,
            duration=self._duration.to_dict(),
            limits=self._limits.to_dict(),
            started_at=started_at.isoformat(),
        )

        try:
            while True:
                now = self._tznow()
                elapsed = (now - started_at).total_seconds()
                if now >= deadline or cycles >= expected_cycles:
                    if self._execute_real_multi:
                        # Posicao aberta mid-trade ja encerrou via
                        # manual_review no lifecycle; chegar aqui = flat.
                        ended_reason = (
                            EnduranceEndedReason.DURATION_COMPLETED_FLAT
                            if orders_submitted_real > 0
                            else EnduranceEndedReason.PASSED_ZERO_TRADES
                        )
                    else:
                        ended_reason = (
                            EnduranceEndedReason.DURATION_COMPLETED
                            if would_orders > 0
                            else EnduranceEndedReason.PASSED_ZERO_TRADES
                        )
                    break

                cycle_idx = cycles
                cycles += 1
                self._emit(
                    "cycle_start", cycle_idx=cycle_idx,
                    elapsed_seconds=elapsed,
                    would_orders=would_orders,
                )

                # --- snapshots horario/diario (wall-clock) ---
                hour_idx = int(elapsed // 3600)
                if hour_idx > last_hour_idx:
                    last_hour_idx = hour_idx
                    snap = self._build_periodic_snapshot(
                        kind="hourly", idx=hour_idx,
                        cycles=cycles, would_orders=would_orders,
                        signals=signals_evaluated, elapsed=elapsed,
                    )
                    hourly_snapshots.append(snap)
                    self._emit(
                        "hourly_snapshot", cycle_idx=cycle_idx, **snap,
                    )
                day_idx = int(elapsed // 86400)
                if day_idx > last_day_idx:
                    last_day_idx = day_idx
                    summary = self._build_periodic_snapshot(
                        kind="daily", idx=day_idx,
                        cycles=cycles, would_orders=would_orders,
                        signals=signals_evaluated, elapsed=elapsed,
                    )
                    daily_summaries.append(summary)
                    self._emit(
                        "daily_summary", cycle_idx=cycle_idx, **summary,
                    )

                # --- flat-check periodico (reconciliacao continua) ---
                if self._flat_check_callable is not None and (
                    elapsed - last_flat_check_elapsed
                    >= self._limits.flat_check_interval_minutes * 60.0
                ):
                    last_flat_check_elapsed = elapsed
                    try:
                        flat = dict(self._flat_check_callable() or {})
                    except Exception as e:  # noqa: BLE001
                        flat = {"is_flat": None,
                                "error": type(e).__name__}
                    self._emit(
                        "flat_check_done", cycle_idx=cycle_idx, **flat,
                    )
                    # Reflete o resultado do flat-check periodico no
                    # report mesmo quando NAO houve trade (FASE 36
                    # hotfix: final_flat_check_passed nao fica null em
                    # sessao limpa sem ordem).
                    if flat.get("is_flat") is not None:
                        last_flat_passed = bool(flat.get("is_flat"))
                    if flat.get("is_flat") is False:
                        manual_review = True
                        ended_reason = (
                            EnduranceEndedReason.MANUAL_REVIEW_REQUIRED
                        )
                        warnings.append("flat_check_not_flat")
                        break

                # --- 1. market data ---
                try:
                    candles = self._market_data(
                        symbol=self._symbol,
                        timeframe=self._timeframe, limit=200,
                    )
                except Exception as e:  # noqa: BLE001
                    api_failures += 1
                    api_failure_strikes += 1
                    self._emit(
                        "api_failure", cycle_idx=cycle_idx,
                        strike_count=api_failure_strikes,
                        error_type=type(e).__name__,
                    )
                    if api_failure_strikes >= \
                            self._limits.max_api_failures:
                        ended_reason = EnduranceEndedReason.API_FAILURE
                        manual_review = True
                        break
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue
                if not candles:
                    api_failures += 1
                    api_failure_strikes += 1
                    self._emit(
                        "api_failure", cycle_idx=cycle_idx,
                        strike_count=api_failure_strikes,
                        error_type="EmptyCandles",
                    )
                    if api_failure_strikes >= \
                            self._limits.max_api_failures:
                        ended_reason = EnduranceEndedReason.API_FAILURE
                        manual_review = True
                        break
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue
                api_failure_strikes = 0

                # Stale data check (teto do perfil/limites).
                stale = self._is_stale(candles, now)
                if stale:
                    warnings.append("stale_market_data")
                    self._emit(
                        "stale_market_data", cycle_idx=cycle_idx,
                        max_stale_seconds=(
                            self._limits.max_stale_data_seconds
                        ),
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue

                # --- 2. prediction context (ANTES da IA; fluxo oficial) ---
                prediction_dict = None
                if self._prediction_enabled():
                    prediction_dict = self._load_prediction_context(
                        cycle_idx,
                    )
                    if prediction_dict is not None:
                        prediction_report = dict(prediction_dict)

                # --- 3/4. features + strategy -> signal ---
                try:
                    features = self._feature_engine.compute(candles)
                    signal = self._strategy.evaluate(features)
                except Exception as e:  # noqa: BLE001
                    warnings.append(
                        f"strategy_error:{type(e).__name__}"
                    )
                    self._emit(
                        "api_failure", cycle_idx=cycle_idx,
                        error_type=type(e).__name__,
                        stage="features_or_strategy",
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue

                signals_evaluated += 1
                from crypto_trading_bot.demo_endurance.real_runner \
                    import _signal_snapshot_fields
                snapshot_fields = _signal_snapshot_fields(signal)
                actionable = bool(
                    getattr(signal, "is_actionable", False)
                )
                self._emit(
                    "signal_evaluated", cycle_idx=cycle_idx,
                    actionable=actionable,
                    signal_action=str(getattr(
                        getattr(signal, "action", None), "value", "hold",
                    )),
                    **snapshot_fields,
                )
                if not actionable:
                    _record_trace(
                        cycle_idx=cycle_idx,
                        final_decision=FinalDecision.HOLD,
                        final_reason=str(
                            snapshot_fields.get("hold_reason")
                            or "no_actionable_signal",
                        ),
                        signal_snapshot=snapshot_fields,
                        mi_snapshot=_mi_from_prediction(
                            prediction_dict,
                        ),
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue

                # --- lado permitido pelo perfil + gate SHORT (FASE 29.x) ---
                side = str(getattr(
                    getattr(signal, "action", None), "value", "",
                )).lower()
                from crypto_trading_bot.operational_profile \
                    .profile_resolver import is_side_allowed
                if not is_side_allowed(self._profile, side):
                    self._emit(
                        "side_blocked_by_profile", cycle_idx=cycle_idx,
                        side=side,
                        allowed_sides=getattr(
                            self._profile, "allowed_sides", "?",
                        ),
                    )
                    _record_trace(
                        cycle_idx=cycle_idx,
                        final_decision=FinalDecision.BLOCK,
                        final_reason=(
                            f"side {side} nao permitido pelo perfil "
                            f"(allowed_sides="
                            f"{getattr(self._profile, 'allowed_sides', '?')})"
                        ),
                        signal_snapshot=snapshot_fields,
                        mi_snapshot=_mi_from_prediction(
                            prediction_dict,
                        ),
                        gates_blocked=("profile_allowed_sides",),
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue
                from crypto_trading_bot.demo_endurance.gates_phase29 \
                    import validate_phase29_short_gate
                short_gate = validate_phase29_short_gate(
                    signal_side=side,
                    operator_confirmed_short=getattr(
                        self._profile, "allow_short_demo", False,
                    ),
                    operator_token=self._operator_token,
                )
                self._emit(
                    "phase29_short_gate_checked", cycle_idx=cycle_idx,
                    signal_side=side,
                    approved=bool(short_gate.approved),
                    blockers=list(short_gate.blockers),
                )
                if not short_gate.approved:
                    _record_trace(
                        cycle_idx=cycle_idx,
                        final_decision=FinalDecision.BLOCK,
                        final_reason=(
                            "short gate bloqueou: "
                            + "; ".join(short_gate.blockers)[:160]
                        ),
                        signal_snapshot=snapshot_fields,
                        mi_snapshot=_mi_from_prediction(
                            prediction_dict,
                        ),
                        gates_blocked=("phase29_short_gate",),
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue

                # --- 5. RiskEngine (soberano) ---
                try:
                    trading_signal = signal.to_trading_signal()
                    risk_result = self._risk_engine.validate_signal(
                        trading_signal,
                    )
                except Exception as e:  # noqa: BLE001
                    warnings.append(f"risk_error:{type(e).__name__}")
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue
                risk_approved = bool(
                    getattr(risk_result, "approved", False)
                )
                risk_summary = {
                    "approved": risk_approved,
                    "reason": str(
                        getattr(risk_result, "reason", "")
                    )[:160],
                }
                # Piso de SL do RiskEngine (read-only, defensivo) p/ o
                # Decision Trace diagnosticar SL abaixo do minimo.
                _rcfg = getattr(self._risk_engine, "_config", None)
                _min_sl = getattr(_rcfg, "min_stop_loss_pct", None)
                if _min_sl is not None:
                    risk_summary["min_stop_loss_pct"] = float(_min_sl)
                self._emit(
                    "risk_validated", cycle_idx=cycle_idx,
                    **risk_summary,
                )
                if not risk_approved:
                    _record_trace(
                        cycle_idx=cycle_idx,
                        final_decision=FinalDecision.SKIP,
                        final_reason=(
                            "RiskEngine reprovou: "
                            + str(risk_summary.get("reason", ""))[:160]
                        ),
                        signal_snapshot=snapshot_fields,
                        trading_signal=trading_signal,
                        risk_summary=risk_summary,
                        mi_snapshot=_mi_from_prediction(
                            prediction_dict,
                        ),
                        gates_approved=("phase29_short_gate",),
                    )
                    self._sleep(self._duration.cycle_interval_seconds)
                    continue

                # --- 6. AI support (opt; APOS risco; consultivo) ---
                if self._ai_support is not None and getattr(
                    self._profile, "allow_ai_assistance", False,
                ):
                    ctx = TradeCycleContext(
                        cycle_idx=cycle_idx,
                        wall_clock=now,
                        symbol=self._symbol,
                        profile_name=getattr(
                            self._profile, "name", "?",
                        ),
                        signal_snapshot=snapshot_fields,
                        risk_summary=risk_summary,
                        prediction_context_dict=prediction_dict,
                    )
                    ai_outcome = self._ai_support.evaluate_cycle(
                        profile=self._profile,
                        ai_context=ctx.to_ai_context(),
                        cycle_idx=cycle_idx,
                    )
                    ai_report_fields = ai_outcome.to_report_fields()
                    if ai_outcome.manual_review_required:
                        manual_review = True
                        ended_reason = (
                            EnduranceEndedReason.MANUAL_REVIEW_REQUIRED
                        )
                        _record_trace(
                            cycle_idx=cycle_idx,
                            final_decision=FinalDecision.REVIEW,
                            final_reason=(
                                "IA pediu manual review: "
                                + str(ai_report_fields.get(
                                    "ai_reason", "",
                                ))[:160]
                            ),
                            signal_snapshot=snapshot_fields,
                            trading_signal=trading_signal,
                            risk_summary=risk_summary,
                            ai_fields=ai_report_fields,
                            mi_snapshot=_mi_from_prediction(
                                prediction_dict,
                            ),
                        )
                        break
                    if ai_outcome.cycle_blocked:
                        # IA reduziu permissao: sem would-order no ciclo.
                        _record_trace(
                            cycle_idx=cycle_idx,
                            final_decision=FinalDecision.BLOCK,
                            final_reason=(
                                "IA vetou (consultivo bloqueante): "
                                + str(ai_report_fields.get(
                                    "ai_reason", "",
                                ))[:160]
                            ),
                            signal_snapshot=snapshot_fields,
                            trading_signal=trading_signal,
                            risk_summary=risk_summary,
                            ai_fields=ai_report_fields,
                            mi_snapshot=_mi_from_prediction(
                                prediction_dict,
                            ),
                            gates_blocked=("ai_veto",),
                        )
                        self._sleep(
                            self._duration.cycle_interval_seconds,
                        )
                        continue

                # --- 7-REAL (FASE 30.2): trade real demo SEQUENCIAL ---
                if self._execute_real_multi:
                    # Regras 13-15: residual inesperado bloqueia entrada.
                    if self._flat_check_callable is not None:
                        try:
                            flat_pre = dict(
                                self._flat_check_callable() or {},
                            )
                        except Exception as e:  # noqa: BLE001
                            flat_pre = {
                                "is_flat": None,
                                "error": type(e).__name__,
                            }
                        if flat_pre.get("is_flat") is False:
                            manual_review = True
                            ended_reason = (
                                EnduranceEndedReason
                                .MANUAL_REVIEW_REQUIRED
                            )
                            warnings.append(
                                "unexpected_residual_before_entry",
                            )
                            _record_trace(
                                cycle_idx=cycle_idx,
                                final_decision=FinalDecision.BLOCK,
                                final_reason=(
                                    "residual inesperado antes da "
                                    "entrada (posicao/ordem/"
                                    "conditional) — manual review"
                                ),
                                signal_snapshot=snapshot_fields,
                                trading_signal=trading_signal,
                                risk_summary=risk_summary,
                                gates_blocked=(
                                    "pre_entry_flat_check",
                                ),
                            )
                            break

                    trade_idx = (
                        trades_completed + trades_manual_review
                    )
                    record = (
                        self._real_trade_lifecycle.execute_trade(
                            trade_idx=trade_idx,
                            trading_signal=trading_signal,
                            latest_snapshot=None,
                            deadline=deadline,
                        )
                    )
                    rec_d = record.to_dict()
                    per_trade_records.append(rec_d)
                    if rec_d.get("opened_at"):
                        orders_submitted_real += 1
                        orders_filled_real += 1
                    last_flat_passed = rec_d.get(
                        "flat_check_after_trade",
                    )
                    _record_trace(
                        cycle_idx=cycle_idx,
                        final_decision=(
                            FinalDecision.CLOSE
                            if rec_d["status"] == "completed"
                            else FinalDecision.REVIEW
                        ),
                        final_reason=(
                            f"trade real #{trade_idx}: "
                            f"status={rec_d['status']} "
                            f"close_reason={rec_d['close_reason']}"
                        ),
                        signal_snapshot=snapshot_fields,
                        trading_signal=trading_signal,
                        risk_summary=risk_summary,
                        ai_fields=(
                            ai_report_fields
                            if ai_report_fields.get("ai_enabled")
                            else None
                        ),
                        mi_snapshot=_mi_from_prediction(
                            prediction_dict,
                        ),
                        gates_approved=(
                            "phase29_short_gate",
                            "phase30_2_real_multi",
                        ),
                        realized_pnl=rec_d.get("realized_pnl"),
                        trade_idx=trade_idx,
                    )
                    if rec_d["status"] == "completed":
                        trades_completed += 1
                        reason = rec_d.get("close_reason")
                        if reason == "tp":
                            trades_closed_by_tp += 1
                        elif reason == "sl":
                            trades_closed_by_sl += 1
                        elif reason == "reduce_only":
                            trades_closed_by_reduce_only += 1
                        pnl = rec_d.get("realized_pnl")
                        if pnl is not None:
                            total_realized_pnl = (
                                (total_realized_pnl or 0.0)
                                + float(pnl)
                            )
                        if orders_submitted_real >= int(
                            self._max_real_orders,
                        ):
                            ended_reason = (
                                EnduranceEndedReason
                                .MAX_REAL_ORDERS_COMPLETED
                            )
                            break
                        # Volta a waiting_signal; proxima entrada SO
                        # com flat limpo (checado acima por ciclo).
                        self._sleep(
                            self._duration.cycle_interval_seconds,
                        )
                        continue
                    # manual_review_required | unresolved: NAO repete.
                    trades_manual_review += 1
                    manual_review = True
                    ended_reason = (
                        EnduranceEndedReason.MANUAL_REVIEW_REQUIRED
                    )
                    break

                # --- 7. gate dry_run=True (wired) + would-order ---
                gate_snapshot = None
                if self._gate_callable is not None:
                    self._emit(
                        "gate_invoked", cycle_idx=cycle_idx,
                        dry_run=True,
                    )
                    try:
                        gate_outcome = self._gate_callable(
                            trading_signal=trading_signal,
                            dry_run=True,
                        )
                        to_dict = getattr(
                            gate_outcome, "to_dict", None,
                        )
                        gate_snapshot = (
                            to_dict() if callable(to_dict)
                            else (dict(gate_outcome)
                                  if isinstance(gate_outcome, dict)
                                  else None)
                        )
                    except Exception as e:  # noqa: BLE001
                        warnings.append(
                            f"gate_error:{type(e).__name__}"
                        )
                        manual_review = True
                        ended_reason = (
                            EnduranceEndedReason.MANUAL_REVIEW_REQUIRED
                        )
                        break

                would_orders += 1
                trade_record = {
                    "kind": "would_order",
                    "dry_run": True,
                    "cycle_idx": cycle_idx,
                    "side": side,
                    "symbol": self._symbol,
                    "entry_price": float(getattr(
                        trading_signal, "entry_price", 0.0,
                    )),
                    "stop_loss_price": float(getattr(
                        trading_signal, "stop_loss_price", 0.0,
                    )),
                    "take_profit_price": getattr(
                        trading_signal, "take_profit_price", None,
                    ),
                    "position_size_usd": float(getattr(
                        trading_signal, "position_size_usd", 0.0,
                    )),
                    "wall_clock": now.isoformat(),
                    "gate_snapshot": gate_snapshot,
                }
                per_trade_records.append(trade_record)
                self._emit(
                    "would_order_recorded", cycle_idx=cycle_idx,
                    would_orders=would_orders,
                    side=side,
                )
                _record_trace(
                    cycle_idx=cycle_idx,
                    final_decision=FinalDecision.ENTER,
                    final_reason=(
                        "would-order registrada (wired dry-run; "
                        "nenhuma ordem real)"
                    ),
                    signal_snapshot=snapshot_fields,
                    trading_signal=trading_signal,
                    risk_summary=risk_summary,
                    ai_fields=(
                        ai_report_fields
                        if ai_report_fields.get("ai_enabled")
                        else None
                    ),
                    mi_snapshot=_mi_from_prediction(prediction_dict),
                    gates_approved=("phase29_short_gate",),
                )

                # --- 8. encerramento pos-would-order ---
                if self._continue_after_would_order:
                    # MODO OBSERVACAO (dry-run): segue registrando
                    # oportunidades ate duration OU max_would_orders.
                    # Caps de sessao/dia sao tetos de ordem REAL e nao
                    # se aplicam a observacao pura (zero ordem).
                    if (
                        self._max_would_orders is not None
                        and would_orders >= self._max_would_orders
                    ):
                        ended_reason = (
                            EnduranceEndedReason
                            .MAX_WOULD_ORDERS_REACHED
                        )
                        break
                else:
                    # Default: single-order (multi exige perfil + gate).
                    if would_orders >= \
                            self._effective_max_orders_session():
                        ended_reason = (
                            EnduranceEndedReason
                            .DRY_RUN_WOULD_ORDER_COMPLETED
                        )
                        break
                    if would_orders >= self._limits.max_orders_per_day:
                        ended_reason = (
                            EnduranceEndedReason
                            .DRY_RUN_WOULD_ORDER_COMPLETED
                        )
                        warnings.append("max_orders_per_day_reached")
                        break

                self._sleep(self._duration.cycle_interval_seconds)

        except KeyboardInterrupt:
            ended_reason = EnduranceEndedReason.OPERATOR_INTERRUPTED

        ended_at = self._tznow()
        elapsed_total = (ended_at - started_at).total_seconds()
        if ended_reason is None:
            ended_reason = EnduranceEndedReason.GRACEFUL_SHUTDOWN

        # Daily summary final SEMPRE (obrigatorio em demo longa; em
        # demo curta documenta a janela unica).
        final_summary = self._build_periodic_snapshot(
            kind="daily_final", idx=last_day_idx,
            cycles=cycles, would_orders=would_orders,
            signals=signals_evaluated, elapsed=elapsed_total,
        )
        daily_summaries.append(final_summary)
        self._emit("daily_summary", **final_summary)

        is_real = self._execute_real_multi
        execution_mode = (
            "real_demo_multi_order" if is_real else "wired_dry_run"
        )
        final_orders_submitted = orders_submitted_real if is_real else 0
        final_orders_filled = orders_filled_real if is_real else 0
        session_summary = {
            "session_id": self._session_id,
            "profile_name": getattr(self._profile, "name", "?"),
            "dry_run": (not is_real),
            "gate_dry_run": (not is_real),
            "execution_mode": execution_mode,
            "real_time_mode": self._real_time,
            "time_compressed": (not self._real_time),
            "observation_mode": self._continue_after_would_order,
            "max_would_orders": self._max_would_orders,
            "max_real_orders": self._max_real_orders,
            "would_orders": would_orders,
            "orders_submitted": final_orders_submitted,
            "trades_completed": trades_completed,
            "total_realized_pnl": total_realized_pnl,
            "signals_evaluated": signals_evaluated,
            "ended_reason": ended_reason.value,
            **ai_report_fields,
            "prediction_market_context": prediction_report,
            # FASE 36 Bloco A - Decision Trace (cap p/ report; a
            # telemetria JSONL carrega TODOS via
            # decision_trace_recorded).
            "decision_traces_count": len(decision_traces),
            "decision_traces_truncated": len(decision_traces) > 500,
            "decision_traces": decision_traces[-500:],
        }
        self._emit(
            "session_end",
            ended_reason=ended_reason.value,
            cycles_completed=cycles,
            would_orders=would_orders,
            orders_submitted=final_orders_submitted,
            trades_completed=trades_completed,
            execution_mode=execution_mode,
            elapsed_wall_clock_seconds=elapsed_total,
        )

        return DemoEnduranceOutcome(
            session_id=self._session_id,
            profile_name=getattr(self._profile, "name", "?"),
            symbol=self._symbol,
            strategy_name=self._strategy_name,
            real_time_mode=self._real_time,
            time_compressed=(not self._real_time),
            dry_run=(not is_real),
            started_at=started_at,
            ended_at=ended_at,
            elapsed_wall_clock_seconds=elapsed_total,
            cycle_interval_seconds=(
                self._duration.cycle_interval_seconds
            ),
            configured_duration_minutes=(
                self._duration.duration_minutes
            ),
            configured_duration_days=self._duration.duration_days,
            cycles_completed=cycles,
            expected_cycles=expected_cycles,
            ended_reason=ended_reason,
            signals_evaluated=signals_evaluated,
            would_orders=would_orders,
            orders_submitted=final_orders_submitted,
            orders_filled=final_orders_filled,
            safety_events=safety_events,
            api_failures=api_failures,
            daily_summaries=tuple(daily_summaries),
            hourly_snapshots=tuple(hourly_snapshots),
            per_trade_records=tuple(per_trade_records),
            session_summary=session_summary,
            warnings=tuple(warnings),
            notes=self._notes,
            # FASE 30.2 - campos de execucao real
            execution_mode=execution_mode,
            real_orders_enabled=is_real,
            max_real_orders=self._max_real_orders,
            trades_completed=trades_completed,
            trades_open=0,
            trades_closed_by_tp=trades_closed_by_tp,
            trades_closed_by_sl=trades_closed_by_sl,
            trades_closed_by_reduce_only=trades_closed_by_reduce_only,
            trades_manual_review=trades_manual_review,
            total_realized_pnl=total_realized_pnl,
            final_flat_check_passed=last_flat_passed,
            multi_order_gate_enabled=_env_truthy(
                ENV_ALLOW_MULTI_ORDER,
            ),
            profile_multi_order_allowed=bool(getattr(
                self._profile, "allow_multi_order_demo", False,
            )),
        )

    # ------------------------------------------------------------------

    def _is_stale(self, candles: Any, now: datetime) -> bool:
        """True se o ultimo candle excede timeframe + max_stale.

        PRE-FIX FASE 30.2 (sessao real 002): o timestamp do candle eh
        a ABERTURA da barra; com timeframe 15m, um candle saudavel
        chega a 15 min de idade. Comparar contra apenas
        max_stale_data_seconds (300s) marcava ~2/3 dos ciclos como
        stale em dados saudaveis. Threshold correto:
        timeframe_seconds + max_stale_data_seconds.
        """
        try:
            last = candles[-1]
            ts = getattr(last, "timestamp", None)
            if ts is None:
                return False
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age = (now - ts).total_seconds()
            threshold = (
                self._timeframe_seconds()
                + self._limits.max_stale_data_seconds
            )
            return age > threshold
        except Exception:  # noqa: BLE001
            return False

    def _timeframe_seconds(self) -> float:
        """Converte o timeframe do runner em segundos (default 15m)."""
        tf = str(self._timeframe).strip().lower()
        try:
            if tf.endswith("m"):
                return float(tf[:-1]) * 60.0
            if tf.endswith("h"):
                return float(tf[:-1]) * 3600.0
            return float(tf) * 60.0  # numerico = minutos (Bybit "15")
        except (TypeError, ValueError):
            return 900.0

    def _load_prediction_context(
        self, cycle_idx: int,
    ) -> Optional[dict]:
        """Carrega + adapta prediction context (read-only, fail-safe)."""
        try:
            raw_ctx = self._prediction_provider()
        except Exception as e:  # noqa: BLE001
            self._emit(
                "prediction_context_unavailable",
                cycle_idx=cycle_idx, error=type(e).__name__,
            )
            return None
        if raw_ctx is None:
            self._emit(
                "prediction_context_unavailable", cycle_idx=cycle_idx,
            )
            return None
        from crypto_trading_bot.ai_assistant \
            .prediction_context_adapter import (
                adapt_prediction_context_for_ai,
            )
        adapted = adapt_prediction_context_for_ai(raw_ctx)
        if adapted is None:
            self._emit(
                "prediction_context_unavailable", cycle_idx=cycle_idx,
            )
            return None
        self._emit(
            "prediction_context_loaded", cycle_idx=cycle_idx,
            stale=bool(adapted.get("stale")),
            risk_flags=list(adapted.get("risk_flags") or []),
            events_considered=adapted.get("events_considered", 0),
        )
        if adapted.get("stale"):
            self._emit(
                "prediction_context_stale", cycle_idx=cycle_idx,
            )
        if adapted.get("risk_flags"):
            self._emit(
                "prediction_market_risk_flagged",
                cycle_idx=cycle_idx,
                risk_flags=list(adapted.get("risk_flags") or []),
            )
        return adapted

    def _build_periodic_snapshot(
        self, *, kind: str, idx: int, cycles: int,
        would_orders: int, signals: int, elapsed: float,
    ) -> dict:
        return {
            "kind": kind,
            "index": int(idx),
            "cycles_completed": int(cycles),
            "signals_evaluated": int(signals),
            "would_orders": int(would_orders),
            "orders_submitted": 0,
            "elapsed_wall_clock_seconds": float(elapsed),
        }


__all__ = [
    "DemoEnduranceRunner",
    "ENV_ALLOW_MULTI_ORDER",
    "ENV_PREDICTION_CONTEXT",
]
