"""
Challenge Readiness Model (FASE 23 - Bloco 1 + Bloco 4)
==========================================================
Estruturas imutaveis e funcao pura para avaliar prontidao para um
estagio de endurance, dado um OperationalProfile + RiskConfig.

NUNCA muta profile ou risk_config. NUNCA chama rede. NUNCA importa
SessionRunner, BybitClient, executores, providers.

Challenge target eh KPI informativo. NAO bloqueia por lucro
insuficiente, NAO cria max_profit_usd obrigatorio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.challenge_readiness.stages import (
    ChallengeEnduranceStage,
    get_stage_definition,
    is_paper_stage,
)
from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile.profile import OperationalProfile


_VALID_SEVERITIES = ("error", "warning", "info")
_VALID_STATUSES = ("ready", "ready_with_warnings", "not_ready")


# ---------------------------------------------------------------------------
# Tipos imutaveis
# ---------------------------------------------------------------------------


class ChallengeReadinessStatus(str, Enum):
    """Resultado consolidado da avaliacao de readiness."""
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class ChallengeReadinessBlocker:
    """Item individual identificado durante avaliacao.

    severity:
        "error"   -> bloqueia readiness (status=NOT_READY).
        "warning" -> nao bloqueia mas registra atencao.
        "info"    -> informativo, nao bloqueia.
    """
    field_name: str
    severity: str
    message: str

    def __post_init__(self) -> None:
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity invalida: {self.severity!r}; "
                f"aceitas: {list(_VALID_SEVERITIES)}"
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message deve ser string nao-vazia")

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> dict:
        return {
            "field_name": self.field_name,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ChallengeReadinessConfig:
    """Configuracao da avaliacao de readiness.

    Frozen. Tudo opcional com defaults conservadores. challenge target
    eh sempre KPI; nunca limite obrigatorio.
    """
    target_stage: ChallengeEnduranceStage
    symbol: str
    # Apenas KPI: pode ser None. NUNCA usado como bloqueio.
    challenge_target_usd: Optional[float] = None
    # Tolerancia opcional: max_total_drawdown_pct deve ser >=
    # max_daily_loss_pct * this_ratio. Default conservador.
    drawdown_to_daily_ratio_min: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.target_stage, ChallengeEnduranceStage):
            raise TypeError(
                "target_stage deve ser ChallengeEnduranceStage; "
                f"recebido {type(self.target_stage).__name__}"
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol deve ser string nao-vazia")
        if self.challenge_target_usd is not None:
            if not isinstance(self.challenge_target_usd, (int, float)):
                raise TypeError("challenge_target_usd deve ser numerico ou None")
            # KPI: aceita qualquer valor; nao validamos faixa.
        if not isinstance(self.drawdown_to_daily_ratio_min, (int, float)):
            raise TypeError("drawdown_to_daily_ratio_min deve ser numerico")
        if self.drawdown_to_daily_ratio_min <= 0:
            raise ValueError(
                "drawdown_to_daily_ratio_min deve ser > 0; recebido "
                f"{self.drawdown_to_daily_ratio_min}"
            )

    def to_dict(self) -> dict:
        return {
            "target_stage": self.target_stage.value,
            "symbol": self.symbol,
            "challenge_target_usd": self.challenge_target_usd,
            "drawdown_to_daily_ratio_min": self.drawdown_to_daily_ratio_min,
        }


@dataclass(frozen=True)
class ChallengeReadinessReport:
    """Relatorio imutavel da avaliacao de readiness.

    Frozen. JSON-serializavel via to_dict(). SEM secrets.
    """
    config: ChallengeReadinessConfig
    profile_name: str
    target_stage: ChallengeEnduranceStage
    status: ChallengeReadinessStatus
    blockers: Tuple[ChallengeReadinessBlocker, ...]
    snapshot: Mapping[str, Any]
    challenge_target_kpi_only: bool   # sempre True nesta fase
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        if not isinstance(self.blockers, tuple):
            object.__setattr__(self, "blockers", tuple(self.blockers))
        if not isinstance(self.snapshot, MappingProxyType):
            object.__setattr__(
                self, "snapshot",
                MappingProxyType(dict(self.snapshot)),
            )
        if self.evaluated_at.tzinfo is None:
            object.__setattr__(
                self, "evaluated_at",
                self.evaluated_at.replace(tzinfo=timezone.utc),
            )
        # Consistencia: status NOT_READY requer pelo menos 1 error.
        has_error = any(b.severity == "error" for b in self.blockers)
        if self.status is ChallengeReadinessStatus.NOT_READY and not has_error:
            raise ValueError(
                "status=NOT_READY exige pelo menos 1 blocker error"
            )
        if (
            self.status is ChallengeReadinessStatus.READY
            and any(b.severity == "warning" for b in self.blockers)
        ):
            raise ValueError(
                "status=READY incompativel com blockers de severity=warning"
            )

    @property
    def is_ready(self) -> bool:
        return self.status is not ChallengeReadinessStatus.NOT_READY

    @property
    def error_count(self) -> int:
        return sum(1 for b in self.blockers if b.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for b in self.blockers if b.severity == "warning")

    def to_ui_snapshot(self) -> dict:
        """FASE 23 UI snapshot: contrato estavel para front futuro.

        Subset orientado a operador humano. SEM secrets.
        """
        return {
            "summary": {
                "profile_name": self.profile_name,
                "target_stage": self.target_stage.value,
                "symbol": self.config.symbol,
                "status": self.status.value,
                "is_ready": self.is_ready,
            },
            "counts": {
                "error_count": self.error_count,
                "warning_count": self.warning_count,
                "info_count": sum(
                    1 for b in self.blockers if b.severity == "info"
                ),
            },
            "blockers": [b.to_dict() for b in self.blockers],
            "snapshot_metrics": {
                k: v for k, v in self.snapshot.items()
                if k in (
                    "account_size_usd", "max_daily_loss_pct",
                    "max_total_loss_pct", "max_trades_per_day",
                    "max_leverage", "max_position_size_pct",
                    "is_paper_stage_executable",
                )
            },
            "kpi": {
                "challenge_target_kpi_only": self.challenge_target_kpi_only,
            },
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    def to_dict(self) -> dict:
        return {
            "config": self.config.to_dict(),
            "profile_name": self.profile_name,
            "target_stage": self.target_stage.value,
            "status": self.status.value,
            "blockers": [b.to_dict() for b in self.blockers],
            "snapshot": dict(self.snapshot),
            "challenge_target_kpi_only": self.challenge_target_kpi_only,
            "evaluated_at": self.evaluated_at.isoformat(),
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


# ---------------------------------------------------------------------------
# Builder: Profile-to-Endurance Gate (Bloco 4)
# ---------------------------------------------------------------------------


def build_challenge_readiness_report(
    profile: OperationalProfile,
    risk_config: RiskConfig,
    config: ChallengeReadinessConfig,
    *,
    now: Optional[datetime] = None,
) -> ChallengeReadinessReport:
    """Funcao pura: avalia readiness sem chamar rede, sem mutar inputs.

    Validacoes:
        - account_size_usd > 0 (profile ou risk_config).
        - max_daily_loss_pct > 0.
        - max_total_loss_pct > 0.
        - max_total_loss_pct >= max_daily_loss_pct * drawdown_to_daily_ratio_min
          (default 1.0).
        - max_trades_per_day > 0.
        - allowed_symbols contem symbol testado (quando restritivo).
        - max_leverage > 0.
        - max_position_size_pct compativel com max_daily_loss_pct.
        - profile.kill_switch_enabled coerente com is_prop_firm.
        - DEMO_* stage nao executavel: emite blocker INFO (nao bloqueia
          readiness — eh apenas planned).
    """
    if not isinstance(profile, OperationalProfile):
        raise TypeError("profile deve ser OperationalProfile")
    if not isinstance(risk_config, RiskConfig):
        raise TypeError("risk_config deve ser RiskConfig")
    if not isinstance(config, ChallengeReadinessConfig):
        raise TypeError("config deve ser ChallengeReadinessConfig")

    blockers: List[ChallengeReadinessBlocker] = []

    # account_size_usd
    account_size = profile.account_size_usd or risk_config.account_size_usd
    if account_size is None or account_size <= 0:
        blockers.append(ChallengeReadinessBlocker(
            "account_size_usd", "error",
            f"account_size_usd invalido (profile={profile.account_size_usd}, "
            f"risk_config={risk_config.account_size_usd})",
        ))

    # max_daily_loss_pct
    max_dl = float(getattr(risk_config, "max_daily_loss_pct", 0) or 0)
    if max_dl <= 0:
        blockers.append(ChallengeReadinessBlocker(
            "max_daily_loss_pct", "error",
            f"max_daily_loss_pct deve ser > 0; recebido {max_dl}",
        ))

    # max_total_loss_pct
    max_total = float(getattr(risk_config, "max_total_loss_pct", 0) or 0)
    if max_total <= 0:
        blockers.append(ChallengeReadinessBlocker(
            "max_total_loss_pct", "error",
            f"max_total_loss_pct deve ser > 0; recebido {max_total}",
        ))

    # Drawdown total >= daily loss (regra padrao)
    if max_dl > 0 and max_total > 0:
        min_total = max_dl * float(config.drawdown_to_daily_ratio_min)
        if max_total < min_total:
            blockers.append(ChallengeReadinessBlocker(
                "max_total_loss_pct", "error",
                f"max_total_loss_pct ({max_total}) deve ser >= "
                f"max_daily_loss_pct ({max_dl}) * ratio "
                f"({config.drawdown_to_daily_ratio_min})",
            ))

    # max_trades_per_day
    max_trades = int(getattr(risk_config, "max_trades_per_day", 0) or 0)
    if max_trades <= 0:
        blockers.append(ChallengeReadinessBlocker(
            "max_trades_per_day", "error",
            f"max_trades_per_day deve ser > 0; recebido {max_trades}",
        ))

    # allowed_symbols
    if profile.allowed_symbols and config.symbol not in profile.allowed_symbols:
        blockers.append(ChallengeReadinessBlocker(
            "allowed_symbols", "error",
            f"symbol {config.symbol!r} nao esta em profile.allowed_symbols="
            f"{list(profile.allowed_symbols)}",
        ))

    # max_leverage
    max_lev = float(getattr(risk_config, "max_leverage", 0) or 0)
    if max_lev <= 0:
        blockers.append(ChallengeReadinessBlocker(
            "max_leverage", "error",
            f"max_leverage deve ser > 0; recebido {max_lev}",
        ))

    # max_position_size_pct vs max_daily_loss_pct (sanity)
    max_pos_pct = float(
        getattr(risk_config, "max_position_size_pct", 0) or 0
    )
    if max_pos_pct > 0 and max_dl > 0:
        # WARNING se posicao > 50x daily loss (apenas heuristico)
        if max_pos_pct > max_dl * 50:
            blockers.append(ChallengeReadinessBlocker(
                "max_position_size_pct", "warning",
                f"max_position_size_pct ({max_pos_pct}) excede ~50x "
                f"max_daily_loss_pct ({max_dl}) — revise sizing",
            ))

    # kill_switch consistency
    if profile.is_prop_firm and not profile.kill_switch_enabled:
        blockers.append(ChallengeReadinessBlocker(
            "kill_switch_enabled", "warning",
            "profile.is_prop_firm=True mas kill_switch_enabled=False — "
            "prop firm geralmente exige kill switch",
        ))

    # DEMO_* nao executavel nesta fase
    stage_def = get_stage_definition(config.target_stage)
    if not is_paper_stage(config.target_stage):
        blockers.append(ChallengeReadinessBlocker(
            "target_stage", "info",
            f"target_stage {config.target_stage.value} eh PLANNED-ONLY na "
            "FASE 23; executar paper antes de progredir para demo real",
        ))

    # Challenge target eh KPI: emite info quando presente.
    if config.challenge_target_usd is not None:
        blockers.append(ChallengeReadinessBlocker(
            "challenge_target_usd", "info",
            f"challenge_target_usd={config.challenge_target_usd} eh apenas "
            "KPI informativo; NUNCA bloqueia readiness por lucro insuficiente",
        ))

    # Snapshot consolidado
    snapshot = {
        "account_size_usd": account_size,
        "max_daily_loss_pct": max_dl,
        "max_total_loss_pct": max_total,
        "max_trades_per_day": max_trades,
        "max_leverage": max_lev,
        "max_position_size_pct": max_pos_pct,
        "symbol": config.symbol,
        "target_stage": config.target_stage.value,
        "stage_definition": stage_def.to_dict(),
        "is_paper_stage_executable": is_paper_stage(config.target_stage),
        "profile_is_prop_firm": profile.is_prop_firm,
        "profile_kill_switch_enabled": profile.kill_switch_enabled,
        "profile_require_manual_ack_on_triangulation":
            profile.require_manual_ack_on_triangulation,
    }

    # Decisao do status
    error_count = sum(1 for b in blockers if b.severity == "error")
    warning_count = sum(1 for b in blockers if b.severity == "warning")
    if error_count > 0:
        status = ChallengeReadinessStatus.NOT_READY
    elif warning_count > 0:
        status = ChallengeReadinessStatus.READY_WITH_WARNINGS
    else:
        status = ChallengeReadinessStatus.READY

    return ChallengeReadinessReport(
        config=config,
        profile_name=profile.name,
        target_stage=config.target_stage,
        status=status,
        blockers=tuple(blockers),
        snapshot=snapshot,
        challenge_target_kpi_only=True,
        evaluated_at=(now or datetime.now(timezone.utc)),
    )
