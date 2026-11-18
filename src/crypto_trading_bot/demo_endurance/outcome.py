"""
Demo30MinOutcome (FASE 26)
==============================
Resultado consolidado de uma sessao demo 30 min PLANNED/DRY-RUN.
Frozen. JSON-serializavel. ZERO secrets.

⚠️  ZERO importacao de:
    - BybitClient / BybitDemoExecutor / BybitDemoPreflight
    - httpx / requests
    - .env / Settings real

Reuso seguro: RecommendedNextAction (FASE 22 demo_session_execution/
outcome.py) eh apenas um enum + dataclass; nao puxa rede. Importado
para preservar contrato estavel de proxima acao recomendada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from crypto_trading_bot.demo_endurance.stage import DemoEnduranceStage
from crypto_trading_bot.demo_session_execution.outcome import (
    RecommendedNextAction,
)


# ---------------------------------------------------------------------------
# Demo30MinVerdict
# ---------------------------------------------------------------------------

class Demo30MinVerdict(str, Enum):
    """Veredito de uma sessao demo 30 min.

    PLANNED_DRY_RUN_OK
        Dry-run da FASE 26 completou sem nenhum efeito real. Plano
        estruturalmente valido. Caminho default na FASE 26.

    PLANNED_DRY_RUN_BLOCKED
        Dry-run gerou plano mas readiness/plan rejeitou input
        operacional antes de simular.

    PASSED_ZERO_TRADES
        Sessao real demo (futura FASE 27) completou sem sinal valido
        durante 30 min. Resultado VALIDO. Nao eh falha.

    PASSED_ONE_TRADE
        Sessao real (FASE 27/28) abriu 1 ordem, recebeu fill, SL/TP
        server-side anexados, reconciliation canonical, sem residual
        no momento da reconciliacao de entrada. NAO implica que a
        gestao de saida da FASE 29 foi concluida. Usado pelo runner
        FASE 27/28 e como verdict INTERMEDIARIO de entrada na FASE 29
        antes da gestao de saida.

    DEMO_FULL_CYCLE_CLEAN
        FASE 29 - veredito CANONICO de Demo finalizada. Exige:
            - entry real demo enviada (apply_demo_real_invoked=True);
            - SL/TP server-side confirmados;
            - saida detectada por TP/SL OU reduceOnly close gated;
            - flat-check final limpo;
            - posicao final zerada (open_positions_count=0);
            - open_orders=0, conditional_orders=0;
            - manual_review_required=False;
            - safety_halt_recommended=False.
        APENAS este verdict finaliza a etapa Demo (cenario A_clean).

    FAILED
        Sessao real falhou por motivo operacional gravavel (ordem
        rejeitada, etc). Reservado.

    MANUAL_REVIEW_REQUIRED
        Triangulation ou flags manuais; operador revisa. Cenario
        C_manual: encerra sessao mas NAO finaliza Demo.

    SAFETY_HALT_ACK_NEEDED
        safety_halt_recommended; requer ack formal.

    NOT_EXECUTABLE
        Tentou-se executar com input invalido / mode incorreto / etc.
    """
    PLANNED_DRY_RUN_OK = "planned_dry_run_ok"
    PLANNED_DRY_RUN_BLOCKED = "planned_dry_run_blocked"
    PASSED_ZERO_TRADES = "passed_zero_trades"
    PASSED_ONE_TRADE = "passed_one_trade"
    DEMO_FULL_CYCLE_CLEAN = "demo_full_cycle_clean"
    FAILED = "failed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    SAFETY_HALT_ACK_NEEDED = "safety_halt_ack_needed"
    NOT_EXECUTABLE = "not_executable"


# Mapping verdict -> recommended_next_action default.
_VERDICT_TO_NEXT_ACTION = {
    Demo30MinVerdict.PLANNED_DRY_RUN_OK:
        RecommendedNextAction.RETURN_TO_PAPER,
    Demo30MinVerdict.PLANNED_DRY_RUN_BLOCKED:
        RecommendedNextAction.RETURN_TO_PAPER,
    Demo30MinVerdict.PASSED_ZERO_TRADES:
        RecommendedNextAction.RETURN_TO_PAPER,
    Demo30MinVerdict.PASSED_ONE_TRADE:
        RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION,
    Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN:
        RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION,
    Demo30MinVerdict.FAILED:
        RecommendedNextAction.MANUAL_REVIEW_REQUIRED,
    Demo30MinVerdict.MANUAL_REVIEW_REQUIRED:
        RecommendedNextAction.MANUAL_REVIEW_REQUIRED,
    Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED:
        RecommendedNextAction.SAFETY_HALT_ACK_NEEDED,
    Demo30MinVerdict.NOT_EXECUTABLE:
        RecommendedNextAction.RETURN_TO_PAPER,
}


def default_recommended_next_action(
    verdict: Demo30MinVerdict,
) -> RecommendedNextAction:
    """Mapping seguro verdict -> RecommendedNextAction."""
    if not isinstance(verdict, Demo30MinVerdict):
        raise TypeError("verdict deve ser Demo30MinVerdict")
    return _VERDICT_TO_NEXT_ACTION[verdict]


# ---------------------------------------------------------------------------
# Demo30MinOutcome
# ---------------------------------------------------------------------------

_VALID_MODES = ("dry_run_planned", "real_endurance")
_VALID_EXIT_PATHS = (
    "tp_sl_server_side", "reduce_only_close", "manual_fallback", "none",
)
_VALID_SCENARIOS = ("A_clean", "B_zero", "C_manual", "unknown")


@dataclass(frozen=True)
class Demo30MinOutcome:
    """Outcome de uma sessao demo 30 min. Frozen. JSON-serializavel.

    Nesta FASE 26, mode SEMPRE eh "dry_run_planned" e verdict eh
    PLANNED_DRY_RUN_OK ou PLANNED_DRY_RUN_BLOCKED. Demais verdicts
    sao definidos para FASE 27+, mas o schema ja contempla.
    """

    stage: DemoEnduranceStage
    mode: str
    session_id: str
    provider_id: str
    environment: str
    symbol: str
    strategy_name: str

    max_session_minutes: int
    elapsed_minutes: int
    cycles_completed: int
    max_orders: int

    orders_planned: int
    orders_submitted: int
    orders_filled: int

    open_positions_count: int
    open_orders_count: int
    conditional_orders_count: int

    current_position_qty: float
    sl_attached: Optional[bool]
    tp_attached: Optional[bool]

    risk_pct_planned: float
    notional_usd_planned: float
    wallet_balance_usd: float

    safety_state: str
    risk_violations_count: int
    safety_events_count: int
    manual_review_required: bool
    safety_halt_recommended: bool

    verdict: Demo30MinVerdict
    recommended_next_action: RecommendedNextAction
    outcome_reason: str
    blockers: Tuple[str, ...] = field(default_factory=tuple)
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""

    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ended_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # FASE 27 - campos opcionais retrocompativeis para caminho real.
    live_blueprint_id: Optional[str] = None
    apply_demo_real_invoked: bool = False
    demo_session_outcome_snapshot: Optional[Mapping[str, Any]] = None
    post_session_check_summary: Optional[Mapping[str, Any]] = None
    # FASE 29 - campos opcionais retrocompativeis para gestao de saida.
    # Defaults preservam comportamento FASE 26/27/28.
    exit_reason: Optional[str] = None
    exit_management_path: str = "none"  # tp_sl_server_side | reduce_only_close | manual_fallback | none
    close_orders_submitted: int = 0
    close_orders_filled: int = 0
    pnl_realized_usd: Optional[float] = None
    pnl_source: Optional[str] = None
    flat_check_result: Optional[Mapping[str, Any]] = None
    first_real_demo_order: bool = False
    phrase_confirmation: bool = False
    # FASE 29 Acceptance Polish - sinalizacao explicita e nao-ambigua
    # de Demo finalizada. demo_finalized=True APENAS no cenario A_clean
    # (verdict == DEMO_FULL_CYCLE_CLEAN). Ver demo_execution_closeout.md.
    demo_finalized: bool = False
    demo_finalization_scenario: str = "unknown"  # A_clean | B_zero | C_manual | unknown

    def __post_init__(self) -> None:
        if not isinstance(self.stage, DemoEnduranceStage):
            raise TypeError("stage deve ser DemoEnduranceStage")
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode invalido nesta fase: {self.mode!r}; "
                f"aceitos: {list(_VALID_MODES)}"
            )
        if not isinstance(self.verdict, Demo30MinVerdict):
            raise TypeError("verdict deve ser Demo30MinVerdict")
        if not isinstance(self.recommended_next_action, RecommendedNextAction):
            raise TypeError(
                "recommended_next_action deve ser RecommendedNextAction"
            )
        # Coerencia FASE 26: dry-run nao pode declarar verdicts reais.
        if self.mode == "dry_run_planned" and self.verdict in (
            Demo30MinVerdict.PASSED_ONE_TRADE,
            Demo30MinVerdict.PASSED_ZERO_TRADES,
            Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN,
            Demo30MinVerdict.FAILED,
        ):
            raise ValueError(
                f"mode={self.mode!r} incompativel com verdict="
                f"{self.verdict.value!r} (FASE 26 dry-run)"
            )
        # Coerencia FASE 27: real_endurance nao pode declarar
        # planned_dry_run_*.
        if self.mode == "real_endurance" and self.verdict in (
            Demo30MinVerdict.PLANNED_DRY_RUN_OK,
            Demo30MinVerdict.PLANNED_DRY_RUN_BLOCKED,
        ):
            raise ValueError(
                f"mode={self.mode!r} incompativel com verdict="
                f"{self.verdict.value!r} (FASE 27 real path)"
            )
        # FASE 27 ajuste obrigatorio: posicao aberta no fim NUNCA permite
        # READY_FOR_NEXT_DEMO_SESSION. Mesmo com SL/TP server-side
        # anexados, recommended_next_action deve ser
        # MANUAL_REVIEW_REQUIRED ate flat_check limpo.
        if (
            self.mode == "real_endurance"
            and self.open_positions_count > 0
            and self.recommended_next_action ==
                RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION
        ):
            raise ValueError(
                "real_endurance com open_positions_count > 0 nao pode "
                "recomendar READY_FOR_NEXT_DEMO_SESSION; use "
                "MANUAL_REVIEW_REQUIRED ate flat_check limpo"
            )
        # Tuples
        if not isinstance(self.blockers, tuple):
            object.__setattr__(self, "blockers", tuple(self.blockers))
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        # Mapping imutavel
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata)),
            )
        # FASE 27 - mappings opcionais imutaveis
        if self.demo_session_outcome_snapshot is not None and \
                not isinstance(
                    self.demo_session_outcome_snapshot, MappingProxyType
                ):
            object.__setattr__(
                self, "demo_session_outcome_snapshot",
                MappingProxyType(dict(self.demo_session_outcome_snapshot)),
            )
        if self.post_session_check_summary is not None and \
                not isinstance(
                    self.post_session_check_summary, MappingProxyType
                ):
            object.__setattr__(
                self, "post_session_check_summary",
                MappingProxyType(dict(self.post_session_check_summary)),
            )
        # FASE 29 - validacoes aditivas.
        if self.exit_management_path not in _VALID_EXIT_PATHS:
            raise ValueError(
                f"exit_management_path invalido: "
                f"{self.exit_management_path!r}"
            )
        if self.close_orders_submitted < 0:
            raise ValueError("close_orders_submitted < 0")
        if self.close_orders_filled < 0:
            raise ValueError("close_orders_filled < 0")
        if self.close_orders_filled > self.close_orders_submitted:
            raise ValueError(
                "close_orders_filled > close_orders_submitted"
            )
        if self.flat_check_result is not None and not isinstance(
            self.flat_check_result, MappingProxyType,
        ):
            object.__setattr__(
                self, "flat_check_result",
                MappingProxyType(dict(self.flat_check_result)),
            )
        # FASE 29 Acceptance Polish - coerencia demo_finalized.
        if self.demo_finalization_scenario not in _VALID_SCENARIOS:
            raise ValueError(
                f"demo_finalization_scenario invalido: "
                f"{self.demo_finalization_scenario!r}; "
                f"aceitos: {list(_VALID_SCENARIOS)}"
            )
        # demo_finalized=True EXIGE verdict canonico DEMO_FULL_CYCLE_CLEAN
        # e scenario A_clean. Sem ambiguidade.
        if self.demo_finalized:
            if self.verdict is not Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN:
                raise ValueError(
                    "demo_finalized=True exige verdict="
                    "DEMO_FULL_CYCLE_CLEAN; recebido "
                    f"{self.verdict.value!r}"
                )
            if self.demo_finalization_scenario != "A_clean":
                raise ValueError(
                    "demo_finalized=True exige "
                    "demo_finalization_scenario='A_clean'"
                )
        # Inversamente: verdict DEMO_FULL_CYCLE_CLEAN exige
        # demo_finalized=True + cenario A_clean + flat real.
        if self.verdict is Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN:
            if not self.demo_finalized:
                raise ValueError(
                    "verdict=DEMO_FULL_CYCLE_CLEAN exige "
                    "demo_finalized=True"
                )
            if self.open_positions_count != 0:
                raise ValueError(
                    "DEMO_FULL_CYCLE_CLEAN exige open_positions_count=0"
                )
            if self.exit_management_path == "none":
                raise ValueError(
                    "DEMO_FULL_CYCLE_CLEAN exige exit_management_path "
                    "!= 'none'"
                )
            if self.manual_review_required or \
                    self.safety_halt_recommended:
                raise ValueError(
                    "DEMO_FULL_CYCLE_CLEAN incompativel com "
                    "manual_review_required/safety_halt_recommended"
                )
        # tz-aware
        if self.started_at.tzinfo is None:
            object.__setattr__(
                self, "started_at",
                self.started_at.replace(tzinfo=timezone.utc),
            )
        if self.ended_at.tzinfo is None:
            object.__setattr__(
                self, "ended_at",
                self.ended_at.replace(tzinfo=timezone.utc),
            )
        # Sanitize notes (truncate 200, sem tokens)
        if not isinstance(self.notes, str):
            object.__setattr__(self, "notes", "")
        elif len(self.notes) > 200:
            object.__setattr__(self, "notes", self.notes[:200] + "...")

    @property
    def is_dry_run(self) -> bool:
        return self.mode == "dry_run_planned"

    @property
    def passed(self) -> bool:
        return self.verdict in (
            Demo30MinVerdict.PLANNED_DRY_RUN_OK,
            Demo30MinVerdict.PASSED_ZERO_TRADES,
            Demo30MinVerdict.PASSED_ONE_TRADE,
            Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN,
        )

    @property
    def is_demo_finalized(self) -> bool:
        """FASE 29 - True APENAS no cenario A_clean (verdict canonico)."""
        return (
            self.demo_finalized
            and self.verdict is Demo30MinVerdict.DEMO_FULL_CYCLE_CLEAN
        )

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "mode": self.mode,
            "session_id": self.session_id,
            "provider_id": self.provider_id,
            "environment": self.environment,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "max_session_minutes": int(self.max_session_minutes),
            "elapsed_minutes": int(self.elapsed_minutes),
            "cycles_completed": int(self.cycles_completed),
            "max_orders": int(self.max_orders),
            "orders_planned": int(self.orders_planned),
            "orders_submitted": int(self.orders_submitted),
            "orders_filled": int(self.orders_filled),
            "open_positions_count": int(self.open_positions_count),
            "open_orders_count": int(self.open_orders_count),
            "conditional_orders_count": int(self.conditional_orders_count),
            "current_position_qty": float(self.current_position_qty),
            "sl_attached": self.sl_attached,
            "tp_attached": self.tp_attached,
            "risk_pct_planned": float(self.risk_pct_planned),
            "notional_usd_planned": float(self.notional_usd_planned),
            "wallet_balance_usd": float(self.wallet_balance_usd),
            "safety_state": self.safety_state,
            "risk_violations_count": int(self.risk_violations_count),
            "safety_events_count": int(self.safety_events_count),
            "manual_review_required": bool(self.manual_review_required),
            "safety_halt_recommended": bool(self.safety_halt_recommended),
            "verdict": self.verdict.value,
            "recommended_next_action": self.recommended_next_action.value,
            "outcome_reason": self.outcome_reason,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "notes": self.notes,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "metadata": dict(self.metadata),
            "live_blueprint_id": self.live_blueprint_id,
            "apply_demo_real_invoked": bool(self.apply_demo_real_invoked),
            "demo_session_outcome_snapshot": (
                dict(self.demo_session_outcome_snapshot)
                if self.demo_session_outcome_snapshot is not None else None
            ),
            "post_session_check_summary": (
                dict(self.post_session_check_summary)
                if self.post_session_check_summary is not None else None
            ),
            # FASE 29 - exit/pnl/flat aditivos. Defaults garantem
            # retrocompat com FASE 26/27/28 JSON.
            "exit_reason": self.exit_reason,
            "exit_management_path": self.exit_management_path,
            "close_orders_submitted": int(self.close_orders_submitted),
            "close_orders_filled": int(self.close_orders_filled),
            "pnl_realized_usd": self.pnl_realized_usd,
            "pnl_source": self.pnl_source,
            "flat_check_result": (
                dict(self.flat_check_result)
                if self.flat_check_result is not None else None
            ),
            "first_real_demo_order": bool(self.first_real_demo_order),
            "phrase_confirmation": bool(self.phrase_confirmation),
            "demo_finalized": bool(self.demo_finalized),
            "demo_finalization_scenario": self.demo_finalization_scenario,
        }
