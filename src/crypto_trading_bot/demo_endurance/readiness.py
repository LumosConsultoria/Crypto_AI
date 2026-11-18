"""
Demo30MinReadiness (FASE 26)
================================
Validacao OFFLINE de pre-requisitos para uma futura sessao demo 30 min.

⚠️  100% PURO. ZERO importacao de:
    - BybitClient / BybitDemoExecutor / BybitDemoPreflight
    - httpx / requests / urllib
    - .env / load_dotenv / Settings real (que poderia ler env)
    - DemoSessionReadinessCheck real (que pode tocar settings/env)

Validacoes feitas via SNAPSHOT INJETAVEL: o caller (CLI, teste, futuro
LiveDemoBlueprintProvider) fornece um EnvironmentSnapshot/LastFlags
imutavel; readiness eh funcao pura sobre esses snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.demo_endurance.plan import PlannedDemoBlueprint
from crypto_trading_bot.demo_endurance.safety_thresholds import (
    DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
    DEMO_30_MIN_MAX_SESSION_MINUTES,
    DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
    DEMO_30_MIN_PLANNED_ENVIRONMENT,
    DEMO_30_MIN_PLANNED_PROVIDER_ID,
)
from crypto_trading_bot.demo_endurance.stage import DemoEnduranceStage


# ---------------------------------------------------------------------------
# Status / Severity
# ---------------------------------------------------------------------------

class Demo30MinReadinessStatus(str, Enum):
    READY = "ready"
    WARNING = "warning"
    NOT_READY = "not_ready"


class Demo30MinReadinessSeverity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Demo30MinReadinessIssue:
    gate: str
    severity: Demo30MinReadinessSeverity
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.gate, str) or not self.gate.strip():
            raise ValueError("gate deve ser string nao-vazia")
        if not isinstance(self.severity, Demo30MinReadinessSeverity):
            raise TypeError("severity deve ser Demo30MinReadinessSeverity")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message deve ser string nao-vazia")

    def to_dict(self) -> dict:
        return {
            "gate": self.gate,
            "severity": self.severity.value,
            "message": self.message,
        }

    @property
    def is_blocking(self) -> bool:
        return self.severity == Demo30MinReadinessSeverity.BLOCKER


# ---------------------------------------------------------------------------
# Snapshots injetaveis (substituem .env / Settings real)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Snapshot OFFLINE do environment relevante para readiness.

    Substitui leitura de Settings/.env. Caller (CLI/teste) prepara
    explicitamente.
    """
    enable_live_trading: bool = False
    enable_demo_execution: bool = False  # FASE 26 nao usa demo real
    trading_mode: str = "paper"          # "paper" | "demo" | "live"
    provider_id: str = DEMO_30_MIN_PLANNED_PROVIDER_ID
    provider_status: str = "opt_in"
    endpoint_type: str = DEMO_30_MIN_PLANNED_ENDPOINT_TYPE
    credentials_present: bool = False    # FASE 26 dry-run nao exige
    environment: str = DEMO_30_MIN_PLANNED_ENVIRONMENT


@dataclass(frozen=True)
class LastSafetyFlags:
    """Snapshot da ultima sessao demo / safety. Tudo False = limpo."""
    manual_review_required: bool = False
    safety_halt_recommended: bool = False
    safety_state: str = "normal"
    kill_switch_enabled: bool = False


# ---------------------------------------------------------------------------
# Config + Report
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Demo30MinReadinessConfig:
    """Config injetavel para readiness demo 30 min.

    Atributos:
        symbol:                ex "BTCUSDT".
        strategy_name:         em SUPPORTED_STRATEGIES.
        capital_usd:           account_size do operador (FASE 24 microfix).
        max_orders:            >= 1 e <= hard_cap=1.
        max_session_minutes:   > 0 e <= 30.
        max_trades_per_day:    do RiskConfig (snapshot injetado).
        operator_token:        nao vazio.
        environment_snapshot:  injetado.
        last_safety_flags:     injetado (default limpo).
        planned_blueprint:     opcional (se nao fornecido, readiness
                               valida demais campos; CLI gera fixture).
        forbid_paper_feed:     True - sempre rejeita feed/signal_exercise.
        forbid_signal_exercise: True - idem.
    """
    symbol: str
    strategy_name: str
    capital_usd: float
    max_orders: int
    max_session_minutes: int
    max_trades_per_day: int
    operator_token: str
    environment_snapshot: EnvironmentSnapshot = field(
        default_factory=EnvironmentSnapshot
    )
    last_safety_flags: LastSafetyFlags = field(
        default_factory=LastSafetyFlags
    )
    planned_blueprint: Optional[PlannedDemoBlueprint] = None
    forbid_paper_feed: bool = True
    forbid_signal_exercise: bool = True


@dataclass(frozen=True)
class Demo30MinReadinessReport:
    status: Demo30MinReadinessStatus
    stage: DemoEnduranceStage
    issues: Tuple[Demo30MinReadinessIssue, ...]
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))
        if self.evaluated_at.tzinfo is None:
            object.__setattr__(
                self, "evaluated_at",
                self.evaluated_at.replace(tzinfo=timezone.utc),
            )

    @property
    def is_ready(self) -> bool:
        return self.status == Demo30MinReadinessStatus.READY

    @property
    def blockers(self) -> Tuple[Demo30MinReadinessIssue, ...]:
        return tuple(i for i in self.issues if i.is_blocking)

    @property
    def warnings(self) -> Tuple[Demo30MinReadinessIssue, ...]:
        return tuple(
            i for i in self.issues
            if i.severity == Demo30MinReadinessSeverity.WARNING
        )

    @property
    def info(self) -> Tuple[Demo30MinReadinessIssue, ...]:
        return tuple(
            i for i in self.issues
            if i.severity == Demo30MinReadinessSeverity.INFO
        )

    @property
    def total_blockers(self) -> int:
        return len(self.blockers)

    @property
    def total_warnings(self) -> int:
        return len(self.warnings)

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "stage": self.stage.value,
            "total_blockers": self.total_blockers,
            "total_warnings": self.total_warnings,
            "blockers": [i.to_dict() for i in self.blockers],
            "warnings": [i.to_dict() for i in self.warnings],
            "info": [i.to_dict() for i in self.info],
            "evaluated_at": self.evaluated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# build_demo_30_min_readiness_report
# ---------------------------------------------------------------------------

def _is_supported_strategy(name: str) -> bool:
    # Lazy import para nao puxar nada que toque rede.
    from crypto_trading_bot.challenge_readiness.strategy_factory import (
        SUPPORTED_STRATEGIES,
    )
    return isinstance(name, str) and name.lower().strip() in SUPPORTED_STRATEGIES


def build_demo_30_min_readiness_report(
    config: Demo30MinReadinessConfig,
    *,
    now: Optional[datetime] = None,
) -> Demo30MinReadinessReport:
    """Funcao pura: valida config e produz report.

    ⚠️  NAO chama rede.
    ⚠️  NAO le .env.
    ⚠️  NAO instancia BybitClient/BybitDemoExecutor/BybitDemoPreflight.
    """
    if not isinstance(config, Demo30MinReadinessConfig):
        raise TypeError("config deve ser Demo30MinReadinessConfig")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    issues: List[Demo30MinReadinessIssue] = []

    def _b(gate: str, msg: str) -> None:
        issues.append(Demo30MinReadinessIssue(
            gate=gate,
            severity=Demo30MinReadinessSeverity.BLOCKER,
            message=msg,
        ))

    def _w(gate: str, msg: str) -> None:
        issues.append(Demo30MinReadinessIssue(
            gate=gate,
            severity=Demo30MinReadinessSeverity.WARNING,
            message=msg,
        ))

    # --- profile/capital ---
    if not isinstance(config.capital_usd, (int, float)) or \
            config.capital_usd <= 0:
        _b("capital", "capital_usd must be > 0")

    # --- symbol ---
    if not isinstance(config.symbol, str) or not config.symbol.strip():
        _b("symbol", "symbol must be non-empty")

    # --- strategy ---
    if not _is_supported_strategy(config.strategy_name):
        _b(
            "strategy",
            f"strategy {config.strategy_name!r} not in SUPPORTED_STRATEGIES",
        )

    # --- max_orders ---
    if not isinstance(config.max_orders, int) or config.max_orders < 1:
        _b("max_orders", "max_orders must be >= 1")
    elif config.max_orders > DEMO_30_MIN_MAX_ORDERS_HARD_CAP:
        _b(
            "max_orders",
            f"max_orders={config.max_orders} > hard_cap="
            f"{DEMO_30_MIN_MAX_ORDERS_HARD_CAP} (FASE 26 limit)",
        )
    # cross-check with profile/RiskConfig snapshot
    if isinstance(config.max_orders, int) and \
            isinstance(config.max_trades_per_day, int) and \
            config.max_orders > config.max_trades_per_day and \
            config.max_trades_per_day > 0:
        _b(
            "max_orders",
            f"max_orders={config.max_orders} > RiskConfig."
            f"max_trades_per_day={config.max_trades_per_day}",
        )

    # --- max_session_minutes ---
    if not isinstance(config.max_session_minutes, int) or \
            config.max_session_minutes < 1:
        _b("max_session_minutes", "max_session_minutes must be >= 1")
    elif config.max_session_minutes > DEMO_30_MIN_MAX_SESSION_MINUTES:
        _b(
            "max_session_minutes",
            f"max_session_minutes={config.max_session_minutes} > "
            f"hard_cap={DEMO_30_MIN_MAX_SESSION_MINUTES} (FASE 26 limit)",
        )

    # --- environment snapshot ---
    env = config.environment_snapshot
    if env.enable_live_trading:
        _b("env", "ENABLE_LIVE_TRADING=true is forbidden (mainnet blocked)")
    if env.trading_mode == "live":
        _b("env", f"trading_mode={env.trading_mode!r} is forbidden")
    if env.provider_id != DEMO_30_MIN_PLANNED_PROVIDER_ID:
        _b(
            "provider",
            f"provider_id={env.provider_id!r} != expected "
            f"{DEMO_30_MIN_PLANNED_PROVIDER_ID!r}",
        )
    if env.provider_status != "opt_in":
        _b(
            "provider",
            f"provider_status={env.provider_status!r} != 'opt_in' "
            "(FASE 26 requires OPT_IN; ACTIVE/UNCONFIRMED rejected)",
        )
    if env.endpoint_type != DEMO_30_MIN_PLANNED_ENDPOINT_TYPE:
        _b(
            "endpoint",
            f"endpoint_type={env.endpoint_type!r} != "
            f"{DEMO_30_MIN_PLANNED_ENDPOINT_TYPE!r} (non-demo endpoint)",
        )
    if env.environment != DEMO_30_MIN_PLANNED_ENVIRONMENT:
        _b(
            "env",
            f"environment={env.environment!r} != "
            f"{DEMO_30_MIN_PLANNED_ENVIRONMENT!r}",
        )

    # --- last safety flags ---
    flags = config.last_safety_flags
    if flags.manual_review_required:
        _b(
            "safety",
            "previous session has manual_review_required pending",
        )
    if flags.safety_halt_recommended:
        _b(
            "safety",
            "previous session has safety_halt_recommended pending",
        )
    if flags.safety_state != "normal":
        _b(
            "safety",
            f"safety_state={flags.safety_state!r} != 'normal'",
        )
    if flags.kill_switch_enabled and flags.safety_state != "normal":
        _b(
            "safety",
            "kill_switch_enabled while safety_state non-normal",
        )

    # --- operator token ---
    if not isinstance(config.operator_token, str) or \
            not config.operator_token.strip():
        _b("operator_token", "operator_token must be non-empty")

    # --- paper-only flags forbidden in demo ---
    if not config.forbid_paper_feed:
        _b(
            "demo_safety",
            "paper_feed must be forbidden in demo flow",
        )
    if not config.forbid_signal_exercise:
        _b(
            "demo_safety",
            "signal_exercise must be forbidden in demo flow",
        )

    # --- planned_blueprint (opcional) ---
    if config.planned_blueprint is not None:
        bp = config.planned_blueprint
        if bp.open_positions_count > 0:
            _b(
                "blueprint",
                f"open_positions_count={bp.open_positions_count} > 0 "
                "before session; demo30min requires flat start",
            )
        if bp.open_orders_count > 0:
            _b(
                "blueprint",
                f"open_orders_count={bp.open_orders_count} > 0 before "
                "session; orphan orders block",
            )
        if bp.conditional_orders_count > 0:
            _w(
                "blueprint",
                f"conditional_orders_count={bp.conditional_orders_count} "
                "> 0; ensure these are expected SL/TP only",
            )
        if bp.is_expired(now):
            _b(
                "blueprint",
                "planned_blueprint ttl expired before plan creation",
            )

    # --- status ---
    has_blocker = any(i.is_blocking for i in issues)
    has_warning = any(
        i.severity == Demo30MinReadinessSeverity.WARNING for i in issues
    )
    if has_blocker:
        status = Demo30MinReadinessStatus.NOT_READY
    elif has_warning:
        status = Demo30MinReadinessStatus.WARNING
    else:
        status = Demo30MinReadinessStatus.READY

    return Demo30MinReadinessReport(
        status=status,
        stage=DemoEnduranceStage.DEMO_30_MIN,
        issues=tuple(issues),
        evaluated_at=now,
    )
