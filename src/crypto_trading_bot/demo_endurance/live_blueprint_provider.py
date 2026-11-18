"""
LiveDemoBlueprintProvider (FASE 27)
======================================
Wrapper read-only sobre BybitDemoPreflight (FASE 22). Converte
PreflightReport (com MarketInfo + AccountState + OrderProposal) em
PlannedDemoBlueprint da FASE 26, adicionando metadados de freshness
(blueprint_id, generated_at, ttl_seconds) e regra de refresh.

⚠️  100% read-only via BybitDemoPreflight.run().
⚠️  NUNCA chama BybitDemoExecutor.execute.
⚠️  NUNCA envia ordem.
⚠️  preflight_factory eh INJETAVEL para testes (default produzido
    via BybitDemoPreflight real; testes substituem por fake).
⚠️  Default TTL = 60s (FASE 27 conservador). FASE 22 single-shot
    usa 300s. Justificativa: FASE 27 espera sinal por ate 30 min,
    e blueprint stale antes da ordem deve forcar re-preflight, nao
    aceitar dados antigos.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Protocol

from crypto_trading_bot.demo_endurance.plan import PlannedDemoBlueprint
from crypto_trading_bot.demo_endurance.safety_thresholds import (
    DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
    DEMO_30_MIN_PLANNED_ENVIRONMENT,
    DEMO_30_MIN_PLANNED_PROVIDER_ID,
)


# TTL curto especifico para FASE 27. Justificativa documentada acima.
LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS: int = 60

# Threshold para forcar re-preflight antes de chamar gate.
LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS: int = 30


class LiveDemoBlueprintError(RuntimeError):
    """Erro de provider live (preflight falhou ou manual_confirmations)."""


class PreflightLike(Protocol):
    """Protocolo minimo aceito como preflight result.

    Compativel com PreflightReport da FASE 22, mas tambem aceita
    fakes de teste com mesma shape.
    """
    ok: bool
    market_info: Any
    account_state: Any
    proposal: Any
    abort_reason: Any
    abort_details: str
    manual_confirmations_needed: tuple


@dataclass(frozen=True)
class LiveBlueprintSnapshot:
    """Snapshot completo do preflight + metadados.

    Atributos:
        blueprint_id:   UUID sanitizado, unico por chamada.
        generated_at:   tz-aware UTC.
        ttl_seconds:    TTL aplicado (default 60s).
        preflight:      objeto preflight-like com ok/market_info/etc.
        blueprint:      PlannedDemoBlueprint convertido (FASE 26 schema).
    """
    blueprint_id: str
    generated_at: datetime
    ttl_seconds: int
    preflight: PreflightLike
    blueprint: PlannedDemoBlueprint

    @property
    def age_seconds(self) -> int:
        now = datetime.now(timezone.utc)
        return max(0, int((now - self.generated_at).total_seconds()))

    def ttl_remaining(self, now: Optional[datetime] = None) -> int:
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        delta = self.ttl_seconds - (now - self.generated_at).total_seconds()
        return max(0, int(delta))

    def is_fresh(
        self,
        now: Optional[datetime] = None,
        threshold_seconds: int = LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS,
    ) -> bool:
        return self.ttl_remaining(now) >= int(threshold_seconds)


def _preflight_to_planned_blueprint(
    preflight: PreflightLike,
    *,
    generated_at: datetime,
    risk_pct: float,
    ttl_seconds: int,
) -> PlannedDemoBlueprint:
    """Converte PreflightReport-like para PlannedDemoBlueprint FASE 26.

    Usa OrderProposal como autoridade sobre entry/SL/TP/qty/notional.
    Usa AccountState para wallet/open_counts. Endpoint/provider/
    environment fixos no padrao FASE 26.
    """
    proposal = preflight.proposal
    account = preflight.account_state
    if proposal is None or account is None:
        raise LiveDemoBlueprintError(
            "preflight sem proposal/account_state nao pode virar blueprint"
        )
    side = str(getattr(proposal, "side", "buy")).lower()
    entry = float(getattr(proposal, "reference_price", 0.0))
    stop_loss = float(getattr(proposal, "stop_loss", 0.0))
    take_profit_attr = getattr(proposal, "take_profit", None)
    if take_profit_attr is None or float(take_profit_attr) <= 0:
        raise LiveDemoBlueprintError(
            "preflight proposal.take_profit ausente; demo real exige "
            "TP server-side. Use target_take_profit_rr no preflight."
        )
    take_profit = float(take_profit_attr)
    qty = float(getattr(proposal, "qty", 0.0))
    position_size_usd = float(getattr(proposal, "position_size_usd", 0.0))
    wallet = getattr(account, "wallet_balance_usdt", None)
    if wallet is None or wallet <= 0:
        # Fallback defensivo: usa capital do proposal (preflight valida).
        wallet = float(getattr(proposal, "capital", 0.0))
    return PlannedDemoBlueprint(
        side=side,
        entry_price=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        qty=qty,
        notional_usd=position_size_usd,
        risk_pct=float(risk_pct),
        wallet_balance_usd=float(wallet),
        open_positions_count=int(
            getattr(account, "open_positions_count", 0) or 0
        ),
        open_orders_count=int(
            getattr(account, "open_orders_count", 0) or 0
        ),
        conditional_orders_count=0,
        endpoint_type=DEMO_30_MIN_PLANNED_ENDPOINT_TYPE,
        provider_id=DEMO_30_MIN_PLANNED_PROVIDER_ID,
        environment=DEMO_30_MIN_PLANNED_ENVIRONMENT,
        generated_at=generated_at,
        ttl_seconds=ttl_seconds,
    )


class LiveDemoBlueprintProvider:
    """Provider que executa BybitDemoPreflight read-only e produz snapshot.

    Args:
        preflight_factory: callable() -> PreflightLike. Producao usa
                           BybitDemoPreflight(...).run; testes injetam fake.
        ttl_seconds:       TTL aplicado ao blueprint (default 60s).
        clock:             callable() -> datetime UTC (default datetime.now).
        risk_pct_calculator: callable(preflight) -> float; default usa
                             proposal.risk_usd/proposal.capital.

    Garantias:
        - Nunca chama BybitDemoExecutor.execute.
        - Nunca envia ordem.
        - Cache em memoria do ultimo snapshot; refresh() re-roda
          preflight e atualiza cache.
    """

    def __init__(
        self,
        *,
        preflight_factory: Callable[[], PreflightLike],
        ttl_seconds: int = LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS,
        clock: Optional[Callable[[], datetime]] = None,
        risk_pct_calculator: Optional[
            Callable[[PreflightLike], float]
        ] = None,
    ) -> None:
        if not callable(preflight_factory):
            raise TypeError("preflight_factory deve ser callable")
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds deve ser int > 0; recebido {ttl_seconds}"
            )
        self._factory = preflight_factory
        self._ttl_seconds = int(ttl_seconds)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._risk_pct_calc = (
            risk_pct_calculator or _default_risk_pct_calculator
        )
        self._last_snapshot: Optional[LiveBlueprintSnapshot] = None

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    @property
    def last_snapshot(self) -> Optional[LiveBlueprintSnapshot]:
        return self._last_snapshot

    def preflight(self) -> LiveBlueprintSnapshot:
        """Roda preflight via factory e retorna snapshot atualizado.

        Valida ok=True e manual_confirmations_needed vazio.

        Raises:
            LiveDemoBlueprintError: preflight nao-ok ou requer confirmacoes.
        """
        pf = self._factory()
        if pf is None:
            raise LiveDemoBlueprintError(
                "preflight_factory retornou None"
            )
        if not getattr(pf, "ok", False):
            reason = getattr(pf, "abort_reason", None)
            reason_val = getattr(reason, "value", str(reason or "unknown"))
            details = str(getattr(pf, "abort_details", ""))[:200]
            raise LiveDemoBlueprintError(
                f"preflight not ok: reason={reason_val} details={details!r}"
            )
        confirmations = tuple(
            getattr(pf, "manual_confirmations_needed", ()) or ()
        )
        if confirmations:
            raise LiveDemoBlueprintError(
                "preflight requires manual confirmations: "
                f"{list(confirmations)[:10]}"
            )
        now = self._clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        risk_pct = float(self._risk_pct_calc(pf))
        blueprint = _preflight_to_planned_blueprint(
            pf,
            generated_at=now,
            risk_pct=risk_pct,
            ttl_seconds=self._ttl_seconds,
        )
        bp_id = "BP-" + uuid.uuid4().hex[:12].upper()
        snapshot = LiveBlueprintSnapshot(
            blueprint_id=bp_id,
            generated_at=now,
            ttl_seconds=self._ttl_seconds,
            preflight=pf,
            blueprint=blueprint,
        )
        self._last_snapshot = snapshot
        return snapshot

    def refresh(self) -> LiveBlueprintSnapshot:
        """Alias semantico para preflight() — re-executa e atualiza cache."""
        return self.preflight()

    def ensure_fresh(
        self,
        *,
        threshold_seconds: int = (
            LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS
        ),
        now: Optional[datetime] = None,
    ) -> LiveBlueprintSnapshot:
        """Retorna snapshot fresco; re-executa preflight se stale.

        Garante que qualquer ordem subsequente use dados frescos.
        Usa self._clock() quando now=None (preserva determinismo
        em testes que injetam clock fixo).
        """
        if self._last_snapshot is None:
            return self.preflight()
        effective_now = now if now is not None else self._clock()
        if effective_now is not None and effective_now.tzinfo is None:
            effective_now = effective_now.replace(tzinfo=timezone.utc)
        if self._last_snapshot.is_fresh(effective_now, threshold_seconds):
            return self._last_snapshot
        return self.preflight()


def _default_risk_pct_calculator(preflight: PreflightLike) -> float:
    """risk_usd / capital, defensivo."""
    proposal = getattr(preflight, "proposal", None)
    if proposal is None:
        return 0.0
    risk_usd = float(getattr(proposal, "risk_usd", 0.0) or 0.0)
    capital = float(getattr(proposal, "capital", 0.0) or 0.0)
    if capital <= 0:
        return 0.0
    return risk_usd / capital
