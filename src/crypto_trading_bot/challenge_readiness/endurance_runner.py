"""
ChallengeEnduranceRunner (FASE 23 - Bloco 3)
=================================================
Camada acima do SessionRunner paper-only existente. Aceita
OperationalProfile + ChallengeEnduranceStage, valida readiness,
roda SessionRunner em paper, coleta SessionRunResult, retorna
ChallengeEnduranceResult.

⚠️  NUNCA importa BybitClient, BybitDemoExecutor, BybitTestnetExecutor,
    DemoExecutionResult, httpx, requests. PROVIDER-AGNOSTIC.
⚠️  Apenas estagios PAPER sao executaveis nesta fase. DEMO_* eh
    rejeitado com NotExecutableInThisPhase.
⚠️  100% testavel offline via clock/sleep injetaveis do SessionRunner.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List, Optional

from crypto_trading_bot.challenge_readiness.readiness import (
    ChallengeReadinessConfig,
    ChallengeReadinessReport,
    ChallengeReadinessStatus,
    build_challenge_readiness_report,
)
from crypto_trading_bot.challenge_readiness.result import (
    ChallengeEnduranceResult,
)
from crypto_trading_bot.challenge_readiness.stages import (
    ChallengeEnduranceStage,
    get_stage_definition,
    is_demo_planned_stage,
    is_paper_stage,
    next_recommended_stage,
)
from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.paper_feed import PaperFeedAdapter, PaperFeedType


class StageNotExecutableInThisPhase(RuntimeError):
    """Stage eh PLANNED-ONLY (demo) na FASE 23 e nao pode ser executado."""


class EnduranceReadinessRejected(RuntimeError):
    """Readiness retornou NOT_READY; endurance nao roda."""


class ChallengeEnduranceRunner:
    """Orquestrador de uma sessao de endurance paper-only.

    Reusa SessionRunner sem alterar nada. SessionRunner eh construido
    APENAS quando paper stage; runner_factory permite injetar fake nos
    testes (default = SessionRunner real).
    """

    def __init__(
        self,
        profile: OperationalProfile,
        risk_config: RiskConfig,
        readiness_config: ChallengeReadinessConfig,
        *,
        # Injetaveis para teste deterministico
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        runner_factory: Optional[Callable[..., object]] = None,
        strategy_spec=None,
        cycle_interval_seconds: float = 0.0,
        virtual_cycle_seconds: float = 60.0,
        # FASE 25 — feed paper opcional + signal_exercise opt-in.
        feed_adapter: Optional[PaperFeedAdapter] = None,
        signal_exercise: bool = False,
    ) -> None:
        if not isinstance(profile, OperationalProfile):
            raise TypeError("profile deve ser OperationalProfile")
        if not isinstance(risk_config, RiskConfig):
            raise TypeError("risk_config deve ser RiskConfig")
        if not isinstance(readiness_config, ChallengeReadinessConfig):
            raise TypeError(
                "readiness_config deve ser ChallengeReadinessConfig"
            )
        self._profile = profile
        self._risk_config = risk_config
        self._readiness_config = readiness_config
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or (lambda s: None)
        self._runner_factory = runner_factory
        self._strategy_spec = strategy_spec
        self._cycle_interval_seconds = float(cycle_interval_seconds)
        self._virtual_cycle_seconds = float(virtual_cycle_seconds)
        # FASE 25 — feed paper opcional + signal_exercise opt-in.
        if feed_adapter is not None and not isinstance(
                feed_adapter, PaperFeedAdapter):
            raise TypeError("feed_adapter deve ser PaperFeedAdapter ou None")
        if not isinstance(signal_exercise, bool):
            raise TypeError("signal_exercise deve ser bool")
        # Validacoes cruzadas: signal_exercise=True exige feed paper real.
        if signal_exercise and feed_adapter is None:
            raise ValueError(
                "signal_exercise=True exige feed_adapter explicito "
                "(synthetic_trending, synthetic_ranging ou cache)."
            )
        if (feed_adapter is not None
                and feed_adapter.feed_type != PaperFeedType.MOCK_RANDOM_WALK
                and not signal_exercise):
            raise ValueError(
                f"feed_adapter.feed_type={feed_adapter.feed_type.value} "
                "exige signal_exercise=True."
            )
        # Symbol/timeframe coerentes
        if feed_adapter is not None:
            if feed_adapter.symbol != readiness_config.symbol:
                raise ValueError(
                    f"feed_adapter.symbol={feed_adapter.symbol!r} != "
                    f"readiness_config.symbol={readiness_config.symbol!r}"
                )
        self._feed_adapter = feed_adapter
        self._signal_exercise = signal_exercise

    def evaluate_readiness(self) -> ChallengeReadinessReport:
        """Funcao pura: retorna report sem rodar SessionRunner."""
        return build_challenge_readiness_report(
            self._profile, self._risk_config, self._readiness_config,
            now=self._clock(),
        )

    def run(self) -> ChallengeEnduranceResult:
        """Executa sessao de endurance.

        Raises:
            StageNotExecutableInThisPhase: stage DEMO_*.
            EnduranceReadinessRejected: readiness NOT_READY.
            ValueError: SessionRunner config invalido.
        """
        stage = self._readiness_config.target_stage
        stage_def = get_stage_definition(stage)

        # Bloqueio 1: stage DEMO_* nao executavel
        if is_demo_planned_stage(stage):
            raise StageNotExecutableInThisPhase(
                f"stage {stage.value} eh PLANNED-ONLY; FASE 23 nao executa "
                "demo. Use scripts/run_bybit_demo_session_gated.py "
                "(Comando A + B) apos paper progression aprovada."
            )

        if not is_paper_stage(stage):
            raise StageNotExecutableInThisPhase(
                f"stage {stage.value} nao eh paper-executavel nesta fase"
            )

        # Bloqueio 2: readiness NOT_READY
        readiness = self.evaluate_readiness()
        if readiness.status is ChallengeReadinessStatus.NOT_READY:
            raise EnduranceReadinessRejected(
                f"readiness NOT_READY: {readiness.error_count} blocker(s)"
            )

        # Tudo OK -> roda SessionRunner em paper.
        started_at = self._clock()
        session_result = self._run_session(stage_def.duration_minutes)
        ended_at = self._clock()

        # Avalia veredito
        blockers: List[str] = []
        warnings: List[str] = []

        # max_daily_loss_observed: aproximado por pior dia ~= |pnl negativo|.
        # Para sessoes < 1 dia, eh equivalente a pnl negativo.
        pnl_realized = float(getattr(session_result, "pnl_paper", 0.0))
        drawdown_observed = float(
            abs(getattr(session_result, "drawdown_paper", 0.0))
        )
        max_daily_loss_observed = max(0.0, -pnl_realized)

        # account_size para % checks
        account_size = (
            self._profile.account_size_usd
            or self._risk_config.account_size_usd
            or 0.0
        )

        max_dl_pct = float(
            getattr(self._risk_config, "max_daily_loss_pct", 0) or 0
        )
        max_total_pct = float(
            getattr(self._risk_config, "max_total_loss_pct", 0) or 0
        )

        # Violacao de perda diaria
        if (
            account_size > 0 and max_dl_pct > 0
            and max_daily_loss_observed > account_size * max_dl_pct
        ):
            blockers.append(
                f"max_daily_loss_pct violated: observed_loss_usd="
                f"{max_daily_loss_observed:.2f} > limit="
                f"{(account_size * max_dl_pct):.2f}"
            )

        # Violacao de drawdown total
        if (
            account_size > 0 and max_total_pct > 0
            and drawdown_observed > account_size * max_total_pct
        ):
            blockers.append(
                f"max_total_loss_pct violated: drawdown_usd="
                f"{drawdown_observed:.2f} > limit="
                f"{(account_size * max_total_pct):.2f}"
            )

        # Violacao max_trades_per_day
        max_trades = int(
            getattr(self._risk_config, "max_trades_per_day", 0) or 0
        )
        trades_opened = int(
            getattr(session_result, "trades_opened", 0) or 0
        )
        if max_trades > 0 and trades_opened > max_trades:
            blockers.append(
                f"max_trades_per_day violated: opened={trades_opened} > "
                f"limit={max_trades}"
            )

        # safety halt / final state
        final_safety_state = str(
            getattr(session_result, "final_safety_state", "normal")
        )
        if final_safety_state != "normal":
            blockers.append(
                f"safety_state ended at {final_safety_state} (expected normal)"
            )

        # Posicao residual ao final
        trades_closed = int(
            getattr(session_result, "trades_closed", 0) or 0
        )
        open_positions_end = max(0, trades_opened - trades_closed)
        if open_positions_end > 0:
            blockers.append(
                f"residual open positions at session end: "
                f"{open_positions_end}"
            )

        # blocks_by_risk = violacoes do RiskEngine durante a sessao
        risk_violations = int(
            getattr(session_result, "blocks_by_risk", 0) or 0
        )
        # Eventos safety (transicoes nao-normais)
        safety_events = int(
            getattr(session_result, "blocks_by_safety", 0) or 0
        )

        verdict = "passed" if not blockers else "failed"

        # Challenge target eh KPI
        target_kpi: Optional[float] = None
        if (
            self._readiness_config.challenge_target_usd is not None
            and self._readiness_config.challenge_target_usd > 0
        ):
            target_kpi = (
                100.0 * pnl_realized
                / float(self._readiness_config.challenge_target_usd)
            )

        next_stage = (
            next_recommended_stage(stage) if verdict == "passed" else None
        )

        # Heuristica: stage definition recommend > 1 day NAO progride para
        # demo aqui (operador deve seguir runbook FASE 22 manualmente).
        # FASE 24 — determinar modo:
        #   operational_paper_run quando ha strategy_spec real OU
        #   quando ha runner_factory injetado (testes ou wiring externo
        #   que ja prove execucao do pipeline real do SessionRunner).
        #   preview_no_strategy apenas quando NAO ha nada wirado (CLI
        #   default sem --strategy).
        if self._strategy_spec is not None:
            mode = "operational_paper_run"
            strategy_name = getattr(self._strategy_spec, "name", None)
        elif self._runner_factory is not None:
            mode = "operational_paper_run"
            strategy_name = "injected_via_runner_factory"
        else:
            mode = "preview_no_strategy"
            strategy_name = None

        # FASE 25 — extrai feed_type / source_description.
        if self._feed_adapter is not None:
            feed_type_str = self._feed_adapter.feed_type.value
            feed_source = self._feed_adapter.source_description
        else:
            feed_type_str = "mock_random_walk"
            feed_source = ""

        return ChallengeEnduranceResult(
            stage=stage,
            mode=mode,
            strategy_name=strategy_name,
            feed_type=feed_type_str,
            signal_exercise=self._signal_exercise,
            feed_source_description=feed_source,
            profile_name=self._profile.name,
            account_size_usd=float(account_size),
            symbol=self._readiness_config.symbol,
            duration_planned_minutes=stage_def.duration_minutes,
            cycles_completed=int(
                getattr(session_result, "total_cycles_completed", 0) or 0
            ),
            trades_opened=trades_opened,
            trades_closed=trades_closed,
            open_positions_end=open_positions_end,
            pnl_realized=pnl_realized,
            pnl_unrealized=0.0,  # paper fechado por SL/TP sintetico
            max_drawdown_observed=drawdown_observed,
            max_daily_loss_observed=max_daily_loss_observed,
            risk_violations_count=risk_violations,
            safety_events_count=safety_events,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            verdict=verdict,
            next_recommended_stage=next_stage,
            challenge_target_progress_pct=target_kpi,
            final_safety_state=final_safety_state,
            stopped_reason=str(
                getattr(
                    getattr(session_result, "stopped_reason", "max_cycles"),
                    "value",
                    getattr(session_result, "stopped_reason", "max_cycles"),
                )
            ),
            started_at=started_at,
            ended_at=ended_at,
        )

    def _run_session(self, duration_minutes: int):
        """Constroi e roda SessionRunner com clock/sleep injetaveis.

        Calculo de max_cycles = duration_minutes * 60 / virtual_cycle_seconds.
        Default virtual_cycle = 60s -> 1 ciclo por minuto.
        """
        max_cycles = max(
            1, int(duration_minutes * 60 / max(1.0, self._virtual_cycle_seconds))
        )

        if self._runner_factory is not None:
            # Test path: factory recebe profile + symbol + max_cycles + clock/sleep.
            # FASE 25: feed_adapter/signal_exercise tambem propagados;
            # factory deve aceitar **kwargs ou estes parametros.
            runner = self._runner_factory(
                profile=self._profile,
                symbol=self._readiness_config.symbol,
                max_cycles=max_cycles,
                clock=self._clock,
                sleep=self._sleep,
                cycle_interval_seconds=self._cycle_interval_seconds,
                virtual_cycle_seconds=self._virtual_cycle_seconds,
                strategy_spec=self._strategy_spec,
                feed_adapter=self._feed_adapter,
                signal_exercise=self._signal_exercise,
            )
            return runner.run()

        # Real path: usa SessionRunner real. Requer strategy_spec injetado.
        if self._strategy_spec is None:
            raise ValueError(
                "strategy_spec eh obrigatorio para runner real; passe pelo "
                "construtor ou injete runner_factory para testes."
            )
        # Lazy import para nao tocar SessionRunner em paths que nao executam.
        from crypto_trading_bot.session_runner import (
            SessionRunner, SessionRunnerConfig,
        )
        from crypto_trading_bot.operational_safety.safety_state_machine import (
            SafetyStateMachine,
        )

        # FASE 24 microfix: sem fallback chumbado de capital. Profile ou
        # risk_config DEVEM fornecer account_size_usd > 0; caso contrario,
        # erro claro — operador deve passar capital explicitamente em
        # profile/RiskConfig (RiskConfig sempre tem default validado
        # pydantic; profile geralmente carrega do builder com capital
        # injetado).
        account_size = (
            self._profile.account_size_usd
            or self._risk_config.account_size_usd
        )
        if account_size is None or account_size <= 0:
            raise ValueError(
                "account_size_usd ausente ou invalido em profile e "
                "risk_config. Forneca capital explicitamente via "
                "build_personal_profile(account_size_usd=...) ou "
                "RiskConfig(account_size_usd=...)."
            )
        cfg = SessionRunnerConfig(
            profile=self._profile,
            spec=self._strategy_spec,
            capital=float(account_size),
            symbol=self._readiness_config.symbol,
            max_cycles=max_cycles,
            cycle_interval_seconds=self._cycle_interval_seconds,
            safety_state_machine=SafetyStateMachine(),
            clock=self._clock,
            sleep=self._sleep,
            virtual_cycle_seconds=self._virtual_cycle_seconds,
            # FASE 25 — feed paper + signal exercise.
            feed_adapter=self._feed_adapter,
            signal_exercise=self._signal_exercise,
        )
        runner = SessionRunner(cfg)
        return runner.run()
