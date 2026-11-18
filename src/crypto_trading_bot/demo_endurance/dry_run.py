"""
Demo30MinDryRunSimulator (FASE 26)
======================================
Simulador offline de uma sessao demo 30 min.

⚠️  ZERO importacao de:
    - BybitClient / BybitDemoExecutor / BybitDemoPreflight
    - execute_demo_session_gated
    - build_demo_api_blueprint
    - httpx / requests / urllib
    - .env / load_dotenv

⚠️  NUNCA envia ordem.
⚠️  NUNCA chama rede.
⚠️  NUNCA instancia executor real.

O simulador:
    - Avanca clock virtual ate max_session_minutes (ou interrompe se
      atingir max_orders simulados).
    - Conta ciclos virtuais (1 por unidade de virtual_cycle_seconds).
    - Marca orders_planned conforme blueprint (no max 1 nesta fase).
    - orders_submitted = 0 e orders_filled = 0 SEMPRE em dry-run.
    - Produz Demo30MinOutcome com verdict PLANNED_DRY_RUN_OK.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from crypto_trading_bot.demo_endurance.outcome import (
    default_recommended_next_action,
    Demo30MinOutcome,
    Demo30MinVerdict,
)
from crypto_trading_bot.demo_endurance.plan import Demo30MinPlan
from crypto_trading_bot.demo_endurance.stage import DemoEnduranceStage


# Default: 1 ciclo virtual = 60 segundos. Para sessao de 30 min → 30 ciclos.
DEFAULT_VIRTUAL_CYCLE_SECONDS = 60.0


class Demo30MinDryRunSimulator:
    """Simulador OFFLINE de sessao demo 30 min.

    Args:
        plan:                     Demo30MinPlan (mode=dry_run_planned).
        clock:                    callable() -> datetime; default
                                  datetime.now(timezone.utc).
        sleep:                    callable(seconds) -> None; default
                                  lambda s: None (sem sleep real).
        virtual_cycle_seconds:    segundos virtuais por ciclo.

    Garantias:
        - Nao importa nem instancia BybitClient/BybitDemoExecutor.
        - Nao envia ordem.
        - Nao chama rede.
        - Producao deterministica dado clock/sleep injetados.
    """

    def __init__(
        self,
        plan: Demo30MinPlan,
        *,
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        virtual_cycle_seconds: float = DEFAULT_VIRTUAL_CYCLE_SECONDS,
    ) -> None:
        if not isinstance(plan, Demo30MinPlan):
            raise TypeError("plan deve ser Demo30MinPlan")
        if plan.apply_demo_real:
            raise ValueError(
                "apply_demo_real=True nao eh permitido na FASE 26"
            )
        if plan.mode != "dry_run_planned":
            raise ValueError(
                f"mode={plan.mode!r} != 'dry_run_planned' (FASE 26)"
            )
        if not callable(clock or (lambda: datetime.now(timezone.utc))):
            raise TypeError("clock deve ser callable() -> datetime")
        if virtual_cycle_seconds <= 0:
            raise ValueError(
                f"virtual_cycle_seconds deve ser > 0: {virtual_cycle_seconds}"
            )
        self._plan = plan
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or (lambda s: None)
        self._virtual_cycle_seconds = float(virtual_cycle_seconds)

    @property
    def plan(self) -> Demo30MinPlan:
        return self._plan

    def simulate(self) -> Demo30MinOutcome:
        """Executa simulacao OFFLINE e devolve Demo30MinOutcome.

        Sem rede. Sem ordem. Sem executor.
        """
        # Defensive: garante que nao houve drift do mode/apply real.
        if self._plan.apply_demo_real:
            return self._build_outcome_not_executable(
                "apply_demo_real=True bloqueado na FASE 26"
            )
        if self._plan.mode != "dry_run_planned":
            return self._build_outcome_not_executable(
                f"mode={self._plan.mode!r} != 'dry_run_planned'"
            )

        started_at = self._clock()
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        # Calculo deterministico do numero de ciclos virtuais.
        total_seconds = self._plan.max_session_minutes * 60.0
        virtual_cycles = max(1, int(total_seconds / self._virtual_cycle_seconds))

        # Loop virtual: nao chama rede, nao envia ordem; sleep
        # injetavel (default no-op). Existe apenas para preservar a
        # invariante "simulator avancou ate o fim do tempo".
        for _ in range(virtual_cycles):
            self._sleep(0.0)

        ended_at = started_at + timedelta(
            seconds=virtual_cycles * self._virtual_cycle_seconds
        )

        # Em dry-run, orders_planned reflete o que SERIA submetido,
        # mas orders_submitted/filled permanecem 0 (sem rede).
        orders_planned = 1 if self._plan.max_orders >= 1 else 0
        orders_submitted = 0
        orders_filled = 0

        bp = self._plan.planned_blueprint
        verdict = Demo30MinVerdict.PLANNED_DRY_RUN_OK
        recommended = default_recommended_next_action(verdict)

        outcome_reason = (
            f"dry-run completed; virtual_cycles={virtual_cycles}; "
            f"no real demo order placed; no network call"
        )

        return Demo30MinOutcome(
            stage=self._plan.stage,
            mode=self._plan.mode,
            session_id=self._plan.session_id,
            provider_id=self._plan.provider_id,
            environment=self._plan.environment,
            symbol=self._plan.symbol,
            strategy_name=self._plan.strategy_name,
            max_session_minutes=self._plan.max_session_minutes,
            elapsed_minutes=self._plan.max_session_minutes,
            cycles_completed=virtual_cycles,
            max_orders=self._plan.max_orders,
            orders_planned=orders_planned,
            orders_submitted=orders_submitted,
            orders_filled=orders_filled,
            open_positions_count=0,
            open_orders_count=0,
            conditional_orders_count=0,
            current_position_qty=0.0,
            sl_attached=None,
            tp_attached=None,
            risk_pct_planned=float(bp.risk_pct),
            notional_usd_planned=float(bp.notional_usd),
            wallet_balance_usd=float(bp.wallet_balance_usd),
            safety_state="normal",
            risk_violations_count=0,
            safety_events_count=0,
            manual_review_required=False,
            safety_halt_recommended=False,
            verdict=verdict,
            recommended_next_action=recommended,
            outcome_reason=outcome_reason,
            blockers=(),
            warnings=(),
            notes="planned dry-run; no real order placed; offline only",
            started_at=started_at,
            ended_at=ended_at,
        )

    def _build_outcome_not_executable(self, reason: str) -> Demo30MinOutcome:
        """Outcome 'not_executable' sanitizado."""
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        bp = self._plan.planned_blueprint
        verdict = Demo30MinVerdict.NOT_EXECUTABLE
        return Demo30MinOutcome(
            stage=DemoEnduranceStage.DEMO_30_MIN,
            mode=self._plan.mode,
            session_id=self._plan.session_id,
            provider_id=self._plan.provider_id,
            environment=self._plan.environment,
            symbol=self._plan.symbol,
            strategy_name=self._plan.strategy_name,
            max_session_minutes=self._plan.max_session_minutes,
            elapsed_minutes=0,
            cycles_completed=0,
            max_orders=self._plan.max_orders,
            orders_planned=0,
            orders_submitted=0,
            orders_filled=0,
            open_positions_count=0,
            open_orders_count=0,
            conditional_orders_count=0,
            current_position_qty=0.0,
            sl_attached=None,
            tp_attached=None,
            risk_pct_planned=float(bp.risk_pct),
            notional_usd_planned=float(bp.notional_usd),
            wallet_balance_usd=float(bp.wallet_balance_usd),
            safety_state="normal",
            risk_violations_count=0,
            safety_events_count=0,
            manual_review_required=False,
            safety_halt_recommended=False,
            verdict=verdict,
            recommended_next_action=default_recommended_next_action(verdict),
            outcome_reason=reason[:200],
            blockers=(reason[:200],),
            warnings=(),
            notes="not executable in FASE 26",
            started_at=now,
            ended_at=now,
        )
