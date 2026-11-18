"""
DemoSessionPlan + SignalBlueprint + build_demo_session_plan (FASE 20)
======================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - DOES NOT EXECUTE. Plan é apenas estrutura imutável; nenhum método
      envia ordem, chama rede, instancia BybitClient ou promove provider.
    - Provider-agnostic. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, httpx, requests, SessionRunner.
    - Consome DemoSessionReadinessReport (FASE 19) — NÃO reavalia os 6
      gates internamente. Apenas valida invariantes do report.
    - Não chama apply_profile_overrides_with_gate. Caller passa snapshot
      pronto da FASE 18 quando aplicável.
    - Funções puras: sem I/O, sem rede, sem mutação de globals.

ARQUITETURA:
    SignalBlueprint           — parâmetros do trade demo (frozen, SL/TP
                                obrigatórios, BUY/SELL com regras).
    DemoSessionPlan           — frozen; congela readiness + profile +
                                blueprint + effective_risk_config.
                                is_planned_for_execution=False por default.
    DemoSessionPlanRejected   — RuntimeError levantado por build em
                                qualquer invariante quebrada.
    build_demo_session_plan() — função pura; valida invariantes do
                                report (ready/blocks/provider/freshness/
                                symbol/capital) + snapshot quando há
                                overrides; produz DemoSessionPlan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.demo_session_readiness import (
    DemoSessionReadinessReport,
)
from crypto_trading_bot.operational_profile import (
    AppliedRiskConfigSnapshot,
)
from crypto_trading_bot.operational_profile.profile import OperationalProfile


_DEMO_PROVIDER_ID = "bybit_demo_linear"
_DEFAULT_FRESHNESS_SECONDS = 300  # 5 minutos
_MAX_ORDERS_ALLOWED = 1


# ---------------------------------------------------------------------------
# Exceções
# ---------------------------------------------------------------------------

class DemoSessionPlanRejected(RuntimeError):
    """
    build_demo_session_plan rejeitou construção.

    Causas: readiness não pronta, total_blocks>0, provider divergente,
    report stale, symbol/capital divergente, snapshot exigido ausente
    ou preview. Não silencia — caller deve tratar.
    """


# ---------------------------------------------------------------------------
# SignalBlueprint
# ---------------------------------------------------------------------------

class BlueprintSide(str, Enum):
    """Lado do trade no blueprint. Valores estáveis (contrato)."""
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class SignalBlueprint:
    """
    Parâmetros completos de uma única ordem demo.

    Frozen. SL e TP OBRIGATÓRIOS (defesa em profundidade ao
    RiskEngine). BUY exige stop_loss < entry < take_profit;
    SELL exige take_profit < entry < stop_loss.
    """
    symbol: str
    side: BlueprintSide
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_usd: float
    strategy_name: str = "demo_session_v1"
    leverage: float = 1.0
    metadata: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol deve ser string não-vazia")
        if not isinstance(self.side, BlueprintSide):
            raise TypeError(
                "side deve ser BlueprintSide; "
                f"recebido {type(self.side).__name__}"
            )
        if not isinstance(self.entry_price, (int, float)) or self.entry_price <= 0:
            raise ValueError(f"entry_price deve ser > 0; recebido {self.entry_price}")
        if not isinstance(self.stop_loss, (int, float)) or self.stop_loss <= 0:
            raise ValueError(
                f"stop_loss obrigatório e > 0; recebido {self.stop_loss}"
            )
        if not isinstance(self.take_profit, (int, float)) or self.take_profit <= 0:
            raise ValueError(
                f"take_profit obrigatório e > 0; recebido {self.take_profit}"
            )
        if (
            not isinstance(self.position_size_usd, (int, float))
            or self.position_size_usd <= 0
        ):
            raise ValueError(
                f"position_size_usd deve ser > 0; recebido {self.position_size_usd}"
            )
        if self.leverage <= 0:
            raise ValueError(f"leverage deve ser > 0; recebido {self.leverage}")

        # Ordenação preço entry x SL/TP
        if self.side is BlueprintSide.BUY:
            if not (self.stop_loss < self.entry_price < self.take_profit):
                raise ValueError(
                    "BUY exige stop_loss < entry_price < take_profit "
                    f"(sl={self.stop_loss}, entry={self.entry_price}, "
                    f"tp={self.take_profit})"
                )
        else:  # SELL
            if not (self.take_profit < self.entry_price < self.stop_loss):
                raise ValueError(
                    "SELL exige take_profit < entry_price < stop_loss "
                    f"(tp={self.take_profit}, entry={self.entry_price}, "
                    f"sl={self.stop_loss})"
                )

        # metadata imutável
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(
                self, "metadata", MappingProxyType(dict(self.metadata))
            )

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size_usd": self.position_size_usd,
            "strategy_name": self.strategy_name,
            "leverage": self.leverage,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# DemoSessionPlan
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DemoSessionPlan:
    """
    Plano imutável de uma sessão demo curta.

    Frozen. is_planned_for_execution=False por default — execução só
    ocorre via execute_demo_session_gated(...) com triple-lock humano.
    """
    plan_id: str                                     # correlation id sanitizado
    readiness_report: DemoSessionReadinessReport
    profile: OperationalProfile
    blueprint: SignalBlueprint
    effective_risk_config: RiskConfig
    risk_snapshot: Optional[AppliedRiskConfigSnapshot]
    max_orders: int = 1
    readiness_max_age_seconds: int = _DEFAULT_FRESHNESS_SECONDS
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_planned_for_execution: bool = False           # default seguro

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValueError("plan_id deve ser string não-vazia")
        if self.max_orders != _MAX_ORDERS_ALLOWED:
            raise ValueError(
                f"max_orders deve ser {_MAX_ORDERS_ALLOWED} nesta fase; "
                f"recebido {self.max_orders}"
            )
        if (
            not isinstance(self.readiness_max_age_seconds, int)
            or self.readiness_max_age_seconds <= 0
        ):
            raise ValueError(
                "readiness_max_age_seconds deve ser int > 0; "
                f"recebido {self.readiness_max_age_seconds}"
            )
        if not isinstance(self.readiness_report, DemoSessionReadinessReport):
            raise TypeError(
                "readiness_report deve ser DemoSessionReadinessReport; "
                f"recebido {type(self.readiness_report).__name__}"
            )
        if not isinstance(self.profile, OperationalProfile):
            raise TypeError(
                "profile deve ser OperationalProfile; "
                f"recebido {type(self.profile).__name__}"
            )
        if not isinstance(self.blueprint, SignalBlueprint):
            raise TypeError(
                "blueprint deve ser SignalBlueprint; "
                f"recebido {type(self.blueprint).__name__}"
            )
        if not isinstance(self.effective_risk_config, RiskConfig):
            raise TypeError(
                "effective_risk_config deve ser RiskConfig; "
                f"recebido {type(self.effective_risk_config).__name__}"
            )
        if self.risk_snapshot is not None and not isinstance(
            self.risk_snapshot, AppliedRiskConfigSnapshot
        ):
            raise TypeError(
                "risk_snapshot deve ser AppliedRiskConfigSnapshot ou None"
            )
        # tz-aware
        if self.created_at.tzinfo is None:
            object.__setattr__(
                self,
                "created_at",
                self.created_at.replace(tzinfo=timezone.utc),
            )

    def to_dict(self) -> dict:
        """Serialização JSON-friendly (sem secrets)."""
        return {
            "plan_id": self.plan_id,
            "max_orders": self.max_orders,
            "readiness_max_age_seconds": self.readiness_max_age_seconds,
            "created_at": self.created_at.isoformat(),
            "is_planned_for_execution": self.is_planned_for_execution,
            "profile_name": self.profile.name,
            "provider_id": self.readiness_report.provider_id,
            "readiness_report": self.readiness_report.to_dict(),
            "blueprint": self.blueprint.to_dict(),
            "risk_snapshot": (
                self.risk_snapshot.to_dict()
                if self.risk_snapshot is not None
                else None
            ),
        }


# ---------------------------------------------------------------------------
# Sanitização (mesma defesa em profundidade das FASEs 16/18/19)
# ---------------------------------------------------------------------------

_SUSPICIOUS_LOG_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def _sanitize_plan_id(plan_id: str) -> str:
    """plan_id é correlation id — truncado e redactado se suspeito."""
    if not isinstance(plan_id, str) or not plan_id.strip():
        return "<empty>"
    lower = plan_id.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        return "<redacted_suspicious>"
    return plan_id[:64] + ("..." if len(plan_id) > 64 else "")


# ---------------------------------------------------------------------------
# build_demo_session_plan
# ---------------------------------------------------------------------------

def build_demo_session_plan(
    *,
    plan_id: str,
    readiness_report: DemoSessionReadinessReport,
    profile: OperationalProfile,
    blueprint: SignalBlueprint,
    effective_risk_config: RiskConfig,
    risk_snapshot: Optional[AppliedRiskConfigSnapshot] = None,
    readiness_max_age_seconds: int = _DEFAULT_FRESHNESS_SECONDS,
    now: Optional[datetime] = None,
) -> DemoSessionPlan:
    """
    Constrói um DemoSessionPlan validando invariantes do readiness report.

    NÃO reavalia os 6 gates da FASE 19 — apenas consome o report.
    NÃO aplica risk_config_overrides — caller usa FASE 18 separadamente.

    Args:
        plan_id: correlation id (sanitizado internamente).
        readiness_report: produzido por DemoSessionReadinessCheck (FASE 19).
        profile: OperationalProfile correspondente.
        blueprint: parâmetros do trade demo (SL/TP obrigatórios).
        effective_risk_config: RiskConfig efetivo (do .env OU produzido
                               via apply_profile_overrides_with_gate).
        risk_snapshot: AppliedRiskConfigSnapshot quando profile possui
                       risk_config_overrides não-vazios. Caso contrário,
                       opcional.
        readiness_max_age_seconds: janela de freshness (default 300s).
        now: relógio injetável (default datetime.now(timezone.utc)).

    Returns:
        DemoSessionPlan frozen, is_planned_for_execution=False.

    Raises:
        DemoSessionPlanRejected: qualquer invariante quebrada.
    """
    safe_plan_id = _sanitize_plan_id(plan_id)
    if safe_plan_id == "<empty>":
        raise DemoSessionPlanRejected(
            "plan_id deve ser string não-vazia"
        )
    if safe_plan_id == "<redacted_suspicious>":
        raise DemoSessionPlanRejected(
            "plan_id contém substring suspeita — rejeitado por segurança"
        )

    if not isinstance(readiness_report, DemoSessionReadinessReport):
        raise DemoSessionPlanRejected(
            "readiness_report deve ser DemoSessionReadinessReport; "
            f"recebido {type(readiness_report).__name__}"
        )

    # Invariante 1: readiness=True
    if not readiness_report.is_ready_for_gated_demo:
        raise DemoSessionPlanRejected(
            "readiness_report.is_ready_for_gated_demo=False — "
            "FASE 19 indicou que NÃO está pronto."
        )
    # Invariante 2: zero blocks
    if readiness_report.total_blocks != 0:
        raise DemoSessionPlanRejected(
            f"readiness_report.total_blocks={readiness_report.total_blocks} "
            "(esperado 0)"
        )
    # Invariante 3: provider correto
    if readiness_report.provider_id != _DEMO_PROVIDER_ID:
        raise DemoSessionPlanRejected(
            f"readiness_report.provider_id={readiness_report.provider_id!r} "
            f"(esperado {_DEMO_PROVIDER_ID!r})"
        )
    # Invariante 4: symbol consistente
    if readiness_report.symbol != blueprint.symbol:
        raise DemoSessionPlanRejected(
            f"symbol divergente: readiness={readiness_report.symbol!r} "
            f"vs blueprint={blueprint.symbol!r}"
        )
    # Invariante 5: capital consistente vs profile
    if profile.account_size_usd is not None:
        # tolerância 0.5% (mesma da FASE 18)
        ref = float(profile.account_size_usd)
        delta = abs(readiness_report.capital - ref)
        tol = max(1.0, ref * 0.005)
        if delta > tol:
            raise DemoSessionPlanRejected(
                f"capital divergente entre readiness ({readiness_report.capital}) "
                f"e profile.account_size_usd ({profile.account_size_usd})"
            )
    # Invariante 6: freshness
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    if readiness_report.evaluated_at.tzinfo is None:
        evaluated_at = readiness_report.evaluated_at.replace(tzinfo=timezone.utc)
    else:
        evaluated_at = readiness_report.evaluated_at
    age = (clock - evaluated_at).total_seconds()
    if age < 0:
        raise DemoSessionPlanRejected(
            "readiness_report.evaluated_at no futuro — relógio inconsistente"
        )
    if age > readiness_max_age_seconds:
        raise DemoSessionPlanRejected(
            f"readiness_report stale: idade={age:.0f}s > limite="
            f"{readiness_max_age_seconds}s"
        )

    # Invariante 7: snapshot obrigatório se profile tem overrides não-vazios
    has_overrides = bool(dict(profile.risk_config_overrides))
    if has_overrides:
        if risk_snapshot is None:
            raise DemoSessionPlanRejected(
                "profile possui risk_config_overrides não-vazios mas "
                "AppliedRiskConfigSnapshot não foi fornecido. Use "
                "apply_profile_overrides_with_gate (FASE 18) primeiro."
            )
        if not risk_snapshot.was_applied:
            raise DemoSessionPlanRejected(
                "AppliedRiskConfigSnapshot.was_applied=False (preview); "
                "execução demo exige snapshot APLICADO via FASE 18."
            )
        # snapshot com error → bloqueia
        snap_errs = [
            i for i in risk_snapshot.issues_at_apply if i.severity == "error"
        ]
        if snap_errs:
            raise DemoSessionPlanRejected(
                f"AppliedRiskConfigSnapshot contém {len(snap_errs)} issue(s) "
                "de severidade 'error'."
            )

    return DemoSessionPlan(
        plan_id=safe_plan_id,
        readiness_report=readiness_report,
        profile=profile,
        blueprint=blueprint,
        effective_risk_config=effective_risk_config,
        risk_snapshot=risk_snapshot,
        max_orders=_MAX_ORDERS_ALLOWED,
        readiness_max_age_seconds=readiness_max_age_seconds,
        created_at=clock,
        is_planned_for_execution=False,
    )
