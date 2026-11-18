"""
Demo30MinPlan + PlannedDemoBlueprint (FASE 26)
=================================================
Plano de uma futura sessao demo controlada de 30 min. Inteiramente
OFFLINE. ZERO importacao de:
    - BybitClient
    - BybitDemoExecutor
    - BybitDemoPreflight
    - build_demo_api_blueprint
    - httpx / requests
    - .env / load_dotenv

⚠️  PlannedDemoBlueprint eh um schema LOCAL/SINTETICO planned-only.
    NAO eh blueprint API-driven fresco; isso fica para FASE 27
    quando LiveDemoBlueprintProvider for implementado.

⚠️  Demo30MinPlan eh apenas DESCRICAO + DECLARACAO. Nao executa nada,
    nao envia ordem, nao chama rede. Apenas dry-run/planned.

Reutilizacao da FASE 22:
    - RecommendedNextAction (enum) eh reusado em outcome.py (import
      seguro; nao puxa rede).
    - DemoSessionPlan/build_demo_api_blueprint NAO sao importados aqui.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from crypto_trading_bot.demo_endurance.safety_thresholds import (
    DEMO_30_MIN_APPLY_DEMO_REAL_DEFAULT,
    DEMO_30_MIN_MAX_OPEN_POSITIONS,
    DEMO_30_MIN_MAX_ORDERS_HARD_CAP,
    DEMO_30_MIN_MAX_SESSION_MINUTES,
    DEMO_30_MIN_PLANNED_BLUEPRINT_TTL_SECONDS,
    DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
    DEMO_30_MIN_PLANNED_ENVIRONMENT,
    DEMO_30_MIN_PLANNED_PROVIDER_ID,
    DEMO_30_MIN_SCHEMA_VERSION,
)
from crypto_trading_bot.demo_endurance.stage import DemoEnduranceStage


# ---------------------------------------------------------------------------
# Sanitizacao auxiliar
# ---------------------------------------------------------------------------

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:", "origin_string",
)


def _sanitize_operator_token(token: str) -> str:
    """Token sanitizado a 8 chars + '...'. NUNCA aparece completo."""
    if not isinstance(token, str):
        return "<empty>"
    token = token.strip()
    if not token:
        return "<empty>"
    if len(token) <= 8:
        return token + "..."
    return token[:8] + "..."


def _sanitize_notes(notes: str, max_len: int = 200) -> str:
    """Trunca a 200 chars; remove tokens sensiveis."""
    if not isinstance(notes, str):
        return ""
    text = notes.strip()
    if not text:
        return ""
    lower = text.lower()
    for tok in _SECRET_TOKENS:
        if tok in lower:
            return "<redacted suspicious notes>"
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _sanitize_id(value: str, max_len: int = 64) -> str:
    """Sanitiza session_id / plan_id (apenas ASCII alfanumerico + '-_')."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("id deve ser string nao-vazia")
    text = value.strip()
    cleaned = "".join(
        c if (c.isalnum() or c in "-_") else "_" for c in text
    )
    return cleaned[:max_len]


# ---------------------------------------------------------------------------
# PlannedDemoBlueprint - schema local OFFLINE
# ---------------------------------------------------------------------------

class PlannedDemoBlueprintRejected(RuntimeError):
    """Blueprint planejado falhou validacao estrutural."""


@dataclass(frozen=True)
class PlannedDemoBlueprint:
    """Blueprint LOCAL/PLANNED. NAO eh fresco via API.

    ⚠️  Mensagem obrigatoria sempre que serializado/printado:
        "Blueprint used in FASE 26 is planned/offline and not
         execution-ready. Real fresh API blueprint remains FASE 22
         Comando A or future FASE 27."

    Campos:
        side:                    'buy' ou 'sell'.
        entry_price:             preco planejado de entrada (sintetico).
        stop_loss:               SL planejado.
        take_profit:             TP planejado.
        qty:                     qty planejada.
        notional_usd:            qty * entry_price (referencia).
        risk_pct:                % do account_size_usd em risco.
        wallet_balance_usd:      saldo planejado (referencia).
        open_positions_count:    snapshot planejado (esperado 0 antes).
        open_orders_count:       snapshot planejado (esperado 0 antes).
        conditional_orders_count: snapshot planejado.
        endpoint_type:           "api-demo.bybit.com" (planejado).
        provider_id:             "bybit_demo_linear" (planejado).
        environment:             "demo" (planejado).
        schema_version:          1 nesta fase.
        generated_at:            timestamp tz-aware UTC.
        ttl_seconds:             TTL declarado (default 300s).
    """

    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    qty: float
    notional_usd: float
    risk_pct: float
    wallet_balance_usd: float
    open_positions_count: int = 0
    open_orders_count: int = 0
    conditional_orders_count: int = 0
    endpoint_type: str = DEMO_30_MIN_PLANNED_ENDPOINT_TYPE
    provider_id: str = DEMO_30_MIN_PLANNED_PROVIDER_ID
    environment: str = DEMO_30_MIN_PLANNED_ENVIRONMENT
    schema_version: int = DEMO_30_MIN_SCHEMA_VERSION
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    ttl_seconds: int = DEMO_30_MIN_PLANNED_BLUEPRINT_TTL_SECONDS

    def __post_init__(self) -> None:
        side_norm = str(self.side).lower().strip()
        if side_norm not in ("buy", "sell"):
            raise PlannedDemoBlueprintRejected(
                f"side invalido: {self.side!r}. Aceitos: buy|sell"
            )
        object.__setattr__(self, "side", side_norm)
        for fname in (
            "entry_price", "stop_loss", "take_profit", "qty",
            "notional_usd", "wallet_balance_usd",
        ):
            val = getattr(self, fname)
            if not isinstance(val, (int, float)) or val <= 0:
                raise PlannedDemoBlueprintRejected(
                    f"{fname} deve ser numerico > 0: {val!r}"
                )
        # Invariante de SL/TP
        if side_norm == "buy":
            if not (self.stop_loss < self.entry_price < self.take_profit):
                raise PlannedDemoBlueprintRejected(
                    f"BUY invalido: stop={self.stop_loss} entry="
                    f"{self.entry_price} tp={self.take_profit}; "
                    "esperado stop < entry < tp"
                )
        else:  # sell
            if not (self.take_profit < self.entry_price < self.stop_loss):
                raise PlannedDemoBlueprintRejected(
                    f"SELL invalido: tp={self.take_profit} entry="
                    f"{self.entry_price} stop={self.stop_loss}; "
                    "esperado tp < entry < stop"
                )
        if not isinstance(self.risk_pct, (int, float)) or self.risk_pct < 0:
            raise PlannedDemoBlueprintRejected(
                f"risk_pct invalido: {self.risk_pct!r}"
            )
        for fname in (
            "open_positions_count", "open_orders_count",
            "conditional_orders_count",
        ):
            val = getattr(self, fname)
            if not isinstance(val, int) or val < 0:
                raise PlannedDemoBlueprintRejected(
                    f"{fname} deve ser int >= 0: {val!r}"
                )
        if self.endpoint_type not in (
            DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
            "api-demo.bybit.com",
        ):
            raise PlannedDemoBlueprintRejected(
                f"endpoint_type nao-demo nesta fase: {self.endpoint_type!r}"
            )
        if self.environment != DEMO_30_MIN_PLANNED_ENVIRONMENT:
            raise PlannedDemoBlueprintRejected(
                f"environment nao-demo nesta fase: {self.environment!r}"
            )
        if self.schema_version != DEMO_30_MIN_SCHEMA_VERSION:
            raise PlannedDemoBlueprintRejected(
                f"schema_version invalida nesta fase: "
                f"{self.schema_version!r} (esperado "
                f"{DEMO_30_MIN_SCHEMA_VERSION})"
            )
        if self.ttl_seconds <= 0:
            raise PlannedDemoBlueprintRejected(
                f"ttl_seconds deve ser > 0: {self.ttl_seconds}"
            )
        if self.generated_at.tzinfo is None:
            object.__setattr__(
                self, "generated_at",
                self.generated_at.replace(tzinfo=timezone.utc),
            )

    @property
    def expires_at(self) -> datetime:
        return self.generated_at + timedelta(seconds=int(self.ttl_seconds))

    def ttl_seconds_remaining(
        self, now: Optional[datetime] = None,
    ) -> int:
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = (self.expires_at - now).total_seconds()
        return max(0, int(delta))

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        return self.ttl_seconds_remaining(now) <= 0

    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "entry_price": float(self.entry_price),
            "stop_loss": float(self.stop_loss),
            "take_profit": float(self.take_profit),
            "qty": float(self.qty),
            "notional_usd": float(self.notional_usd),
            "risk_pct": float(self.risk_pct),
            "wallet_balance_usd": float(self.wallet_balance_usd),
            "open_positions_count": int(self.open_positions_count),
            "open_orders_count": int(self.open_orders_count),
            "conditional_orders_count": int(self.conditional_orders_count),
            "endpoint_type": self.endpoint_type,
            "provider_id": self.provider_id,
            "environment": self.environment,
            "schema_version": int(self.schema_version),
            "generated_at": self.generated_at.isoformat(),
            "ttl_seconds": int(self.ttl_seconds),
            "expires_at": self.expires_at.isoformat(),
            "_planned_only_warning": (
                "PlannedDemoBlueprint schema. NEVER bypasses the gate. "
                "In FASE 26 dry-run this is local/synthetic. In FASE 28 "
                "wired dry-run the same schema may carry data from a "
                "live read-only preflight (api-demo.bybit.com), but the "
                "gate FASE 22 still receives dry_run=True. For real "
                "single-shot demo order use run_bybit_demo_session_gated"
                ".py (Comando A + B). First real order via wired runner "
                "remains blocked until FASE 29 explicit approval."
            ),
        }


def build_default_planned_blueprint(
    *,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    entry_price: float = 65000.0,
    stop_loss: float = 64350.0,
    take_profit: float = 66300.0,
    qty: float = 0.003,
    wallet_balance_usd: float = 5000.0,
    risk_pct: float = 0.01,
    now: Optional[datetime] = None,
) -> PlannedDemoBlueprint:
    """Constroi PlannedDemoBlueprint fixture coerente para CLI/testes.

    ⚠️  TEMPLATE EDITAVEL, planned-only. Nao representa preco real de
    mercado. Para dados frescos, ver runbook FASE 22.
    """
    notional = float(qty) * float(entry_price)
    generated_at = now or datetime.now(timezone.utc)
    return PlannedDemoBlueprint(
        side=side,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        qty=float(qty),
        notional_usd=float(notional),
        risk_pct=float(risk_pct),
        wallet_balance_usd=float(wallet_balance_usd),
        open_positions_count=0,
        open_orders_count=0,
        conditional_orders_count=0,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# Demo30MinPlan
# ---------------------------------------------------------------------------

class Demo30MinPlanRejected(RuntimeError):
    """build_demo_30_min_plan rejeitou input invalido."""


_VALID_MODES = ("dry_run_planned",)


@dataclass(frozen=True)
class Demo30MinPlan:
    """Plano declarativo de uma futura sessao demo 30 min.

    Frozen. JSON-serializavel. SEM secrets. apply_demo_real SEMPRE
    False nesta fase. Nao instancia executor, nao envia ordem, nao
    chama rede.
    """

    session_id: str
    stage: DemoEnduranceStage
    mode: str  # "dry_run_planned"
    provider_id: str
    environment: str
    endpoint_type: str
    symbol: str
    strategy_name: str
    max_orders: int
    max_session_minutes: int
    max_open_positions: int
    risk_thresholds_snapshot: Mapping[str, Any]
    planned_blueprint: PlannedDemoBlueprint
    operator_token_sanitized: str
    created_at: datetime
    expires_at: datetime
    apply_demo_real: bool = False
    schema_version: int = DEMO_30_MIN_SCHEMA_VERSION
    notes: str = ""
    # FASE 27 - id do snapshot LiveDemoBlueprintProvider. None quando
    # planejamento eh local (FASE 26 dry-run). Quando preenchido,
    # indica que o blueprint veio de preflight read-only fresco.
    live_blueprint_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, DemoEnduranceStage):
            raise TypeError(
                "stage deve ser DemoEnduranceStage; "
                f"recebido {type(self.stage).__name__}"
            )
        if self.mode not in _VALID_MODES:
            raise ValueError(
                f"mode invalido nesta fase: {self.mode!r}; "
                f"aceitos: {list(_VALID_MODES)}"
            )
        if self.apply_demo_real:
            raise ValueError(
                "apply_demo_real=True nao eh permitido na FASE 26. "
                "Use FASE 22 runbook ou aguarde FASE 27."
            )
        if not isinstance(self.planned_blueprint, PlannedDemoBlueprint):
            raise TypeError("planned_blueprint deve ser PlannedDemoBlueprint")
        if self.max_orders <= 0:
            raise ValueError(
                f"max_orders deve ser > 0: {self.max_orders}"
            )
        if self.max_orders > DEMO_30_MIN_MAX_ORDERS_HARD_CAP:
            raise ValueError(
                f"max_orders={self.max_orders} > hard_cap="
                f"{DEMO_30_MIN_MAX_ORDERS_HARD_CAP} nesta fase"
            )
        if self.max_session_minutes <= 0:
            raise ValueError(
                f"max_session_minutes deve ser > 0: "
                f"{self.max_session_minutes}"
            )
        if self.max_session_minutes > DEMO_30_MIN_MAX_SESSION_MINUTES:
            raise ValueError(
                f"max_session_minutes={self.max_session_minutes} > "
                f"hard_cap={DEMO_30_MIN_MAX_SESSION_MINUTES} nesta fase"
            )
        if self.max_open_positions != DEMO_30_MIN_MAX_OPEN_POSITIONS:
            raise ValueError(
                f"max_open_positions deve ser "
                f"{DEMO_30_MIN_MAX_OPEN_POSITIONS} nesta fase; recebido "
                f"{self.max_open_positions}"
            )
        if self.provider_id != self.planned_blueprint.provider_id:
            raise ValueError(
                f"provider_id={self.provider_id!r} != blueprint."
                f"provider_id={self.planned_blueprint.provider_id!r}"
            )
        if self.environment != self.planned_blueprint.environment:
            raise ValueError(
                f"environment={self.environment!r} != blueprint."
                f"environment={self.planned_blueprint.environment!r}"
            )
        if self.endpoint_type != self.planned_blueprint.endpoint_type:
            raise ValueError(
                f"endpoint_type={self.endpoint_type!r} != blueprint."
                f"endpoint_type={self.planned_blueprint.endpoint_type!r}"
            )
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol deve ser string nao-vazia")
        if not isinstance(self.strategy_name, str) or \
                not self.strategy_name.strip():
            raise ValueError("strategy_name deve ser string nao-vazia")
        if self.schema_version != DEMO_30_MIN_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version invalida: {self.schema_version}"
            )
        # Sanitiza timestamps
        if self.created_at.tzinfo is None:
            object.__setattr__(
                self, "created_at",
                self.created_at.replace(tzinfo=timezone.utc),
            )
        if self.expires_at.tzinfo is None:
            object.__setattr__(
                self, "expires_at",
                self.expires_at.replace(tzinfo=timezone.utc),
            )
        # Risk thresholds: snapshot imutavel
        if not isinstance(self.risk_thresholds_snapshot, MappingProxyType):
            object.__setattr__(
                self, "risk_thresholds_snapshot",
                MappingProxyType(dict(self.risk_thresholds_snapshot)),
            )
        # Operator token sempre sanitizado
        object.__setattr__(
            self, "operator_token_sanitized",
            _sanitize_operator_token(self.operator_token_sanitized),
        )
        # Notes sanitizado
        object.__setattr__(self, "notes", _sanitize_notes(self.notes))

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "stage": self.stage.value,
            "mode": self.mode,
            "provider_id": self.provider_id,
            "environment": self.environment,
            "endpoint_type": self.endpoint_type,
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "max_orders": int(self.max_orders),
            "max_session_minutes": int(self.max_session_minutes),
            "max_open_positions": int(self.max_open_positions),
            "risk_thresholds_snapshot": dict(self.risk_thresholds_snapshot),
            "planned_blueprint": self.planned_blueprint.to_dict(),
            "operator_token_sanitized": self.operator_token_sanitized,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "apply_demo_real": bool(self.apply_demo_real),
            "schema_version": int(self.schema_version),
            "notes": self.notes,
            "live_blueprint_id": self.live_blueprint_id,
            "_planned_only_warning": (
                "PlannedDemoBlueprint schema. NEVER bypasses the gate. "
                "In FASE 26 dry-run this is local/synthetic. In FASE 28 "
                "wired dry-run the same schema may carry data from a "
                "live read-only preflight (api-demo.bybit.com), but the "
                "gate FASE 22 still receives dry_run=True. For real "
                "single-shot demo order use run_bybit_demo_session_gated"
                ".py (Comando A + B). First real order via wired runner "
                "remains blocked until FASE 29 explicit approval."
            ),
        }


def build_demo_30_min_plan(
    *,
    symbol: str,
    strategy_name: str,
    max_orders: int,
    max_session_minutes: int,
    risk_thresholds_snapshot: Mapping[str, Any],
    planned_blueprint: PlannedDemoBlueprint,
    operator_token: str,
    notes: str = "",
    session_id: Optional[str] = None,
    now: Optional[datetime] = None,
    provider_id: str = DEMO_30_MIN_PLANNED_PROVIDER_ID,
    environment: str = DEMO_30_MIN_PLANNED_ENVIRONMENT,
    endpoint_type: str = DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
    live_blueprint_id: Optional[str] = None,
) -> Demo30MinPlan:
    """Constroi Demo30MinPlan validando campos e gerando session_id."""
    if max_session_minutes <= 0 or \
            max_session_minutes > DEMO_30_MIN_MAX_SESSION_MINUTES:
        raise Demo30MinPlanRejected(
            f"max_session_minutes invalido: {max_session_minutes}"
        )
    if max_orders <= 0 or max_orders > DEMO_30_MIN_MAX_ORDERS_HARD_CAP:
        raise Demo30MinPlanRejected(
            f"max_orders invalido nesta fase: {max_orders}"
        )
    if operator_token is None or not str(operator_token).strip():
        raise Demo30MinPlanRejected(
            "operator_token eh obrigatorio (sera sanitizado em outputs)"
        )

    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    expires_at = now + timedelta(minutes=int(max_session_minutes))

    if session_id is None:
        session_id = "DEMO30M-" + uuid.uuid4().hex[:12].upper()
    session_id = _sanitize_id(session_id)

    return Demo30MinPlan(
        session_id=session_id,
        stage=DemoEnduranceStage.DEMO_30_MIN,
        mode="dry_run_planned",
        provider_id=provider_id,
        environment=environment,
        endpoint_type=endpoint_type,
        symbol=symbol.strip(),
        strategy_name=strategy_name.strip(),
        max_orders=int(max_orders),
        max_session_minutes=int(max_session_minutes),
        max_open_positions=DEMO_30_MIN_MAX_OPEN_POSITIONS,
        risk_thresholds_snapshot=risk_thresholds_snapshot,
        planned_blueprint=planned_blueprint,
        operator_token_sanitized=str(operator_token),
        created_at=now,
        expires_at=expires_at,
        apply_demo_real=False,
        schema_version=DEMO_30_MIN_SCHEMA_VERSION,
        notes=notes,
        live_blueprint_id=live_blueprint_id,
    )
