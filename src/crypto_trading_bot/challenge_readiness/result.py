"""
ChallengeEnduranceResult (FASE 23 - Bloco 5)
================================================
Relatorio imutavel de uma sessao de endurance. JSON-serializavel.
SEM secrets. SEM ordens externas registradas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from crypto_trading_bot.challenge_readiness.stages import (
    ChallengeEnduranceStage,
)


_VALID_VERDICTS = ("passed", "failed", "not_executable")
_VALID_MODES = ("preview_no_strategy", "operational_paper_run")
_VALID_FEED_TYPES = (
    "mock_random_walk",
    "synthetic_trending",
    "synthetic_ranging",
    "cache",
)


@dataclass(frozen=True)
class ChallengeEnduranceResult:
    """Resultado consolidado da sessao de endurance.

    Frozen. JSON-serializavel via to_dict().

    Campos obrigatorios refletem o briefing FASE 23 Bloco 5.
    Sem max_profit_usd. challenge_target_progress_pct eh KPI apenas
    quando challenge_target_usd estava configurado.
    """
    stage: ChallengeEnduranceStage
    profile_name: str
    account_size_usd: float
    symbol: str
    duration_planned_minutes: int
    cycles_completed: int
    trades_opened: int
    trades_closed: int
    open_positions_end: int
    pnl_realized: float
    pnl_unrealized: float
    max_drawdown_observed: float
    max_daily_loss_observed: float
    risk_violations_count: int
    safety_events_count: int
    blockers: Tuple[str, ...]
    warnings: Tuple[str, ...]
    verdict: str                          # "passed" | "failed" | "not_executable"
    next_recommended_stage: Optional[ChallengeEnduranceStage]
    challenge_target_progress_pct: Optional[float] = None
    final_safety_state: str = "normal"
    stopped_reason: str = "max_cycles"
    # FASE 24 — distinguir preview vs operacional real.
    mode: str = "preview_no_strategy"
    strategy_name: Optional[str] = None
    # FASE 25 — identificacao do feed paper. Defaults preservam
    # comportamento legado (PAPER_30_MIN/60_MIN/1_DAY ja aprovados sem
    # feed explicito = mock_random_walk + signal_exercise=False).
    feed_type: str = "mock_random_walk"
    signal_exercise: bool = False
    feed_source_description: str = ""
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ended_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ChallengeEnduranceStage):
            raise TypeError(
                "stage deve ser ChallengeEnduranceStage; "
                f"recebido {type(self.stage).__name__}"
            )
        if self.verdict not in _VALID_VERDICTS:
            raise ValueError(
                f"verdict invalido: {self.verdict!r}; "
                f"aceitos: {list(_VALID_VERDICTS)}"
            )
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode invalido: {self.mode!r}; "
                f"aceitos: {list(_VALID_MODES)}"
            )
        if self.feed_type not in _VALID_FEED_TYPES:
            raise ValueError(
                f"feed_type invalido: {self.feed_type!r}; "
                f"aceitos: {list(_VALID_FEED_TYPES)}"
            )
        if not isinstance(self.signal_exercise, bool):
            raise TypeError("signal_exercise deve ser bool")
        # Coerencia: signal_exercise=True so faz sentido com feed != legado.
        if self.signal_exercise and self.feed_type == "mock_random_walk":
            raise ValueError(
                "signal_exercise=True nao eh compativel com "
                "feed_type='mock_random_walk'. Use synthetic_trending, "
                "synthetic_ranging ou cache."
            )
        # Coerencia: operacional exige strategy_name; preview pode nao ter.
        if self.mode == "operational_paper_run":
            if not isinstance(self.strategy_name, str) or not \
                    self.strategy_name.strip():
                raise ValueError(
                    "operational_paper_run exige strategy_name nao-vazio"
                )
        # Coerencia: preview_no_strategy NUNCA pode ter verdict=passed
        # como validacao operacional. Pode marcar "passed" apenas se
        # for explicitamente um preview vazio (cycles_completed=0).
        if (
            self.mode == "preview_no_strategy"
            and self.verdict == "passed"
            and self.cycles_completed > 0
        ):
            raise ValueError(
                "preview_no_strategy nao pode ter verdict=passed com "
                "cycles_completed>0 — use mode=operational_paper_run"
            )
        if not isinstance(self.blockers, tuple):
            object.__setattr__(self, "blockers", tuple(self.blockers))
        if not isinstance(self.warnings, tuple):
            object.__setattr__(self, "warnings", tuple(self.warnings))
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )
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

    @property
    def passed(self) -> bool:
        return self.verdict == "passed"

    def to_ui_snapshot(self) -> dict:
        """FASE 23 UI snapshot: contrato estavel para front futuro.

        Subset orientado a operador humano com chaves estaveis para
        powering CLI/dashboard/HTML. SEM secrets. Distincao explicita
        entre dados acionaveis e metadata.

        Categorias:
            stage_info: estagio + duracao planejada + next_recommended.
            execution: cycles + trades + P&L observado.
            risk_health: drawdown, daily_loss, violacoes.
            safety: estado final + eventos.
            verdict: passed/failed/not_executable + blockers + warnings.
            kpi: challenge_target_progress_pct (apenas informativo).
            timing: started_at / ended_at iso8601.
        """
        return {
            "stage_info": {
                "stage": self.stage.value,
                "duration_planned_minutes": self.duration_planned_minutes,
                "next_recommended_stage": (
                    self.next_recommended_stage.value
                    if self.next_recommended_stage is not None else None
                ),
                "profile_name": self.profile_name,
                "symbol": self.symbol,
                "account_size_usd": self.account_size_usd,
                "mode": self.mode,
                "strategy_name": self.strategy_name,
                "feed_type": self.feed_type,
                "signal_exercise": self.signal_exercise,
                "feed_source_description": self.feed_source_description,
            },
            "execution": {
                "cycles_completed": self.cycles_completed,
                "trades_opened": self.trades_opened,
                "trades_closed": self.trades_closed,
                "open_positions_end": self.open_positions_end,
                "pnl_realized": self.pnl_realized,
                "pnl_unrealized": self.pnl_unrealized,
            },
            "risk_health": {
                "max_drawdown_observed": self.max_drawdown_observed,
                "max_daily_loss_observed": self.max_daily_loss_observed,
                "risk_violations_count": self.risk_violations_count,
            },
            "safety": {
                "final_safety_state": self.final_safety_state,
                "safety_events_count": self.safety_events_count,
                "stopped_reason": self.stopped_reason,
            },
            "verdict": {
                "verdict": self.verdict,
                "passed": self.passed,
                "blockers": list(self.blockers),
                "warnings": list(self.warnings),
            },
            "kpi": {
                "challenge_target_progress_pct": (
                    self.challenge_target_progress_pct
                ),
                "is_kpi_only": True,
            },
            "timing": {
                "started_at": self.started_at.isoformat(),
                "ended_at": self.ended_at.isoformat(),
            },
        }

    def to_dict(self) -> dict:
        return {
            "stage": self.stage.value,
            "mode": self.mode,
            "strategy_name": self.strategy_name,
            "feed_type": self.feed_type,
            "signal_exercise": self.signal_exercise,
            "feed_source_description": self.feed_source_description,
            "profile_name": self.profile_name,
            "account_size_usd": self.account_size_usd,
            "symbol": self.symbol,
            "duration_planned_minutes": self.duration_planned_minutes,
            "cycles_completed": self.cycles_completed,
            "trades_opened": self.trades_opened,
            "trades_closed": self.trades_closed,
            "open_positions_end": self.open_positions_end,
            "pnl_realized": self.pnl_realized,
            "pnl_unrealized": self.pnl_unrealized,
            "max_drawdown_observed": self.max_drawdown_observed,
            "max_daily_loss_observed": self.max_daily_loss_observed,
            "risk_violations_count": self.risk_violations_count,
            "safety_events_count": self.safety_events_count,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "verdict": self.verdict,
            "next_recommended_stage": (
                self.next_recommended_stage.value
                if self.next_recommended_stage is not None else None
            ),
            "challenge_target_progress_pct": (
                self.challenge_target_progress_pct
            ),
            "final_safety_state": self.final_safety_state,
            "stopped_reason": self.stopped_reason,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "metadata": dict(self.metadata),
        }
