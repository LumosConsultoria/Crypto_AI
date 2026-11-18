"""
DemoApiBlueprint + persistência + bridge (FASE 22)
======================================================
⚠️  Reaproveita BybitDemoPreflight (FASE 9 Fatia 4B+). NÃO recria
    coleta de instruments-info, orderbook, ticker, balance, positions
    ou open_orders. NÃO duplica lógica de minOrderQty, qtyStep,
    minNotional, tickSize, reference_price, SL/TP ou risk_usd.
⚠️  Funções puras: sem I/O de rede, sem mutação de globals.
    Persistência JSON usa Path local; sem leitura de .env.
⚠️  Bridge OrderProposal → SignalBlueprint exige TP > 0 (FASE 20).
⚠️  Blueprint stale rejeitado em load_from_json. Default TTL = 60s.
⚠️  NUNCA inclui api_key/api_secret/headers/assinatura no JSON.

ARQUITETURA:
    DemoApiBlueprint            — frozen, JSON-serializável, sem secrets.
    DemoApiBlueprintRejected    — RuntimeError levantado pelo builder
                                   e pelo loader.
    build_demo_api_blueprint    — consome PreflightReport.ok=True
                                   + aborts adicionais (posição/ordem
                                   aberta, spread, leverage manual).
    serialize_to_json           — grava JSON sanitizado em path.
    load_from_json              — carrega + valida TTL + schema_version.
    to_signal_blueprint         — bridge para SignalBlueprint (FASE 20).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from crypto_trading_bot.demo_session_execution.plan import (
    BlueprintSide,
    SignalBlueprint,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    MarketInfo,
    OrderProposal,
    PreflightReport,
)


_SCHEMA_VERSION = 2  # FASE 22.1 — added take_profit_rr field
DEFAULT_TTL_SECONDS = 60
DEFAULT_MAX_SPREAD_PCT = 0.10  # 0.10% (decimal: 0.001 = 0.1%)
DEFAULT_TAKE_PROFIT_RR = 2.0   # conservador, editavel via CLI

# FASE 22.1: substrings que tornam manual_confirmations CRITICOS.
# Bloqueiam build_demo_api_blueprint (sem bypass facil nesta fase).
_CRITICAL_MANUAL_CONFIRMATION_SUBSTRINGS = (
    "open orders",
    "open_orders",
)


# ---------------------------------------------------------------------------
# Exceção
# ---------------------------------------------------------------------------

class DemoApiBlueprintRejected(RuntimeError):
    """Levantada quando o blueprint não pode ser construído ou carregado.

    Causas: preflight não-OK, proposal ausente, posição aberta, ordem
    aberta, spread acima do limite, leverage não-confirmable sem flag,
    take_profit=None no bridge, blueprint stale, JSON inválido, etc.
    """


# ---------------------------------------------------------------------------
# Sanitização de command preview
# ---------------------------------------------------------------------------

_SUSPICIOUS_LOG_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def _sanitize_text(text: str) -> str:
    if not isinstance(text, str):
        return ""
    lower = text.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        return "<redacted_suspicious>"
    return text[:500]


# ---------------------------------------------------------------------------
# DemoApiBlueprint
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DemoApiBlueprint:
    """Blueprint API-driven imutável da próxima sessão demo gated.

    Frozen. JSON-serializável via to_dict(). SEM secrets em qualquer
    campo. Consumido pelo gate da FASE 20 via to_signal_blueprint().

    FASE 22.1: campo take_profit_rr registra o RR usado pelo preflight
    para auditar a origem do TP (None quando TP veio de factor ou
    quando TP é ausente).
    """
    blueprint_id: str
    generated_at: datetime
    schema_version: int
    market_info: MarketInfo
    account_state: AccountState
    proposal: OrderProposal
    spread_pct: float
    notional_usd: float
    risk_pct: float
    readiness_summary: Mapping[str, Any]
    manual_confirmations_needed: Tuple[str, ...]
    command_preview: str
    take_profit_rr: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.blueprint_id, str) or not self.blueprint_id.strip():
            raise ValueError("blueprint_id deve ser string não-vazia")
        if not isinstance(self.market_info, MarketInfo):
            raise TypeError(
                f"market_info deve ser MarketInfo; "
                f"recebido {type(self.market_info).__name__}"
            )
        if not isinstance(self.account_state, AccountState):
            raise TypeError(
                f"account_state deve ser AccountState; "
                f"recebido {type(self.account_state).__name__}"
            )
        if not isinstance(self.proposal, OrderProposal):
            raise TypeError(
                f"proposal deve ser OrderProposal; "
                f"recebido {type(self.proposal).__name__}"
            )
        if self.schema_version != _SCHEMA_VERSION:
            raise ValueError(
                f"schema_version inválido: {self.schema_version} "
                f"(esperado {_SCHEMA_VERSION})"
            )
        # tz-aware
        if self.generated_at.tzinfo is None:
            object.__setattr__(
                self,
                "generated_at",
                self.generated_at.replace(tzinfo=timezone.utc),
            )
        # tuplas/mapping defensivos
        if not isinstance(self.manual_confirmations_needed, tuple):
            object.__setattr__(
                self,
                "manual_confirmations_needed",
                tuple(self.manual_confirmations_needed),
            )
        if not isinstance(self.readiness_summary, MappingProxyType):
            object.__setattr__(
                self,
                "readiness_summary",
                MappingProxyType(dict(self.readiness_summary)),
            )
        # command_preview sanitizado
        if any(s in self.command_preview.lower()
               for s in _SUSPICIOUS_LOG_SUBSTRINGS):
            raise ValueError(
                "command_preview contém substring suspeita — recusado"
            )

    def to_dict(self) -> dict:
        return {
            "blueprint_id": self.blueprint_id,
            "generated_at": self.generated_at.isoformat(),
            "schema_version": self.schema_version,
            "market_info": self.market_info.to_dict(),
            "account_state": self.account_state.to_dict(),
            "proposal": self.proposal.to_dict(),
            "spread_pct": self.spread_pct,
            "notional_usd": self.notional_usd,
            "risk_pct": self.risk_pct,
            "readiness_summary": dict(self.readiness_summary),
            "manual_confirmations_needed": list(
                self.manual_confirmations_needed
            ),
            "command_preview": self.command_preview,
            "take_profit_rr": self.take_profit_rr,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _compute_spread_pct(market: MarketInfo) -> float:
    if market.best_bid <= 0 or market.best_ask <= 0:
        raise DemoApiBlueprintRejected(
            "market_info contém bid/ask não-positivo"
        )
    if market.best_ask < market.best_bid:
        raise DemoApiBlueprintRejected(
            "market_info ask < bid — orderbook inconsistente"
        )
    if market.mid_price <= 0:
        raise DemoApiBlueprintRejected("mid_price não-positivo")
    return ((market.best_ask - market.best_bid) / market.mid_price) * 100.0


def _build_command_preview(proposal: OrderProposal) -> str:
    """Comando preview ASCII-only, sanitizado. Operador copia e revisa."""
    side = proposal.side.lower()
    return (
        "python scripts/run_bybit_demo_session_gated.py "
        f"--profile personal --capital {proposal.capital} "
        f"--symbol {proposal.symbol} --side {side} "
        f"--from-blueprint <BLUEPRINT_JSON_PATH> "
        "--execute-demo --confirm-demo-session "
        "--operator-token <OPERATOR_EMAIL> "
        "--i-understand-this-is-demo"
    )


def _classify_manual_confirmations(
    manual_confirmations: Tuple[str, ...],
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Particiona manual_confirmations em (critical, non_critical).

    Critical = qualquer entrada que contenha substring de
    _CRITICAL_MANUAL_CONFIRMATION_SUBSTRINGS (case-insensitive).
    """
    critical: list[str] = []
    non_critical: list[str] = []
    for entry in manual_confirmations:
        lower = entry.lower()
        if any(s in lower for s in _CRITICAL_MANUAL_CONFIRMATION_SUBSTRINGS):
            critical.append(entry)
        else:
            non_critical.append(entry)
    return tuple(critical), tuple(non_critical)


def build_demo_api_blueprint(
    preflight_report: PreflightReport,
    *,
    max_spread_pct: float = DEFAULT_MAX_SPREAD_PCT,
    accept_leverage_manual_confirmation: bool = False,
    take_profit_rr: Optional[float] = None,
    now: Optional[datetime] = None,
) -> DemoApiBlueprint:
    """Constrói DemoApiBlueprint a partir de PreflightReport.

    Aborts:
      - preflight_report.ok=False
      - proposal/market_info/account_state ausentes
      - posição aberta no símbolo (open_positions_count > 0)
      - ordem aberta no símbolo (open_orders_count > 0)
      - spread > max_spread_pct
      - leverage não confirmable sem accept_leverage_manual_confirmation
    """
    if not isinstance(preflight_report, PreflightReport):
        raise DemoApiBlueprintRejected(
            f"preflight_report deve ser PreflightReport; "
            f"recebido {type(preflight_report).__name__}"
        )
    if not preflight_report.ok:
        raise DemoApiBlueprintRejected(
            f"preflight_report.ok=False "
            f"(abort_reason={preflight_report.abort_reason})"
        )
    if preflight_report.market_info is None:
        raise DemoApiBlueprintRejected("market_info ausente")
    if preflight_report.account_state is None:
        raise DemoApiBlueprintRejected("account_state ausente")
    if preflight_report.proposal is None:
        raise DemoApiBlueprintRejected("proposal ausente")

    market = preflight_report.market_info
    account = preflight_report.account_state
    proposal = preflight_report.proposal

    # Aborts adicionais
    if account.open_positions_count > 0:
        raise DemoApiBlueprintRejected(
            f"open_positions_count={account.open_positions_count} > 0 — "
            "posição residual presente"
        )
    if account.open_orders_count > 0:
        raise DemoApiBlueprintRejected(
            f"open_orders_count={account.open_orders_count} > 0 — "
            "ordem residual presente"
        )

    spread_pct = _compute_spread_pct(market)
    if spread_pct > max_spread_pct:
        raise DemoApiBlueprintRejected(
            f"spread_pct={spread_pct:.4f}% > max_spread_pct="
            f"{max_spread_pct:.4f}%"
        )

    if not account.leverage_confirmable and not accept_leverage_manual_confirmation:
        raise DemoApiBlueprintRejected(
            "leverage_confirmable=False e "
            "accept_leverage_manual_confirmation=False — "
            "operador deve confirmar leverage explicitamente"
        )

    # FASE 22.1: manual_confirmations CRITICOS (open orders API failure)
    # bloqueiam blueprint. Sem bypass facil nesta fase.
    critical_confirmations, _ = _classify_manual_confirmations(
        tuple(preflight_report.manual_confirmations_needed)
    )
    if critical_confirmations:
        raise DemoApiBlueprintRejected(
            "critical_manual_confirmation: "
            f"{critical_confirmations[0]!r}"
        )

    # Derivados
    notional_usd = proposal.qty * proposal.reference_price
    if proposal.capital > 0:
        risk_pct = (proposal.risk_usd / proposal.capital) * 100.0
    else:
        risk_pct = 0.0

    # Readiness summary (counts derivados do account_state)
    readiness_summary = {
        "wallet_balance_usdt": account.wallet_balance_usdt,
        "available_balance_usdt": account.available_balance_usdt,
        "open_positions_count": account.open_positions_count,
        "open_orders_count": account.open_orders_count,
        "leverage_confirmable": account.leverage_confirmable,
        "leverage_value": account.leverage_value,
    }

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    return DemoApiBlueprint(
        blueprint_id=str(uuid.uuid4()),
        generated_at=clock,
        schema_version=_SCHEMA_VERSION,
        market_info=market,
        account_state=account,
        proposal=proposal,
        spread_pct=spread_pct,
        notional_usd=notional_usd,
        risk_pct=risk_pct,
        readiness_summary=readiness_summary,
        manual_confirmations_needed=tuple(
            preflight_report.manual_confirmations_needed
        ),
        command_preview=_build_command_preview(proposal),
        take_profit_rr=(
            float(take_profit_rr) if take_profit_rr is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# Persistência JSON
# ---------------------------------------------------------------------------

def serialize_to_json(blueprint: DemoApiBlueprint, path: Path) -> None:
    """Grava blueprint como JSON sanitizado em path local.

    NÃO inclui secrets. Sobrescreve se existir.
    """
    if not isinstance(blueprint, DemoApiBlueprint):
        raise TypeError(
            f"blueprint deve ser DemoApiBlueprint; "
            f"recebido {type(blueprint).__name__}"
        )
    if not isinstance(path, Path):
        path = Path(path)
    # Path traversal defensivo: rejeita .. em qualquer parte
    if any(part == ".." for part in path.parts):
        raise DemoApiBlueprintRejected(
            "path contém '..' — recusado por segurança"
        )
    data = blueprint.to_dict()
    payload = json.dumps(data, indent=2, sort_keys=True, default=str)
    # Defesa em profundidade: rejeita serialização que contenha substring
    # suspeita (não deveria, pois MarketInfo/AccountState/OrderProposal não
    # contêm secrets — mas validamos antes de gravar).
    lower = payload.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        raise DemoApiBlueprintRejected(
            "payload JSON contém substring suspeita — gravação recusada"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def load_from_json(
    path: Path,
    *,
    max_age_seconds: int = DEFAULT_TTL_SECONDS,
    now: Optional[datetime] = None,
) -> DemoApiBlueprint:
    """Carrega blueprint do JSON.

    Rejeita:
      - path inexistente
      - path traversal (..)
      - JSON malformado
      - schema_version diferente
      - blueprint stale (age > max_age_seconds)
      - blueprint no futuro (clock skew)
    """
    if not isinstance(path, Path):
        path = Path(path)
    if any(part == ".." for part in path.parts):
        raise DemoApiBlueprintRejected(
            "path contém '..' — recusado por segurança"
        )
    if not path.exists():
        raise DemoApiBlueprintRejected(f"path inexistente")
    try:
        text = path.read_text(encoding="utf-8")
        raw = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        raise DemoApiBlueprintRejected(
            f"json_invalid:{type(e).__name__}"
        ) from e
    if not isinstance(raw, dict):
        raise DemoApiBlueprintRejected("json não é objeto")

    if raw.get("schema_version") != _SCHEMA_VERSION:
        raise DemoApiBlueprintRejected(
            f"schema_version mismatch (esperado {_SCHEMA_VERSION})"
        )

    # Reconstroi tipos imutáveis a partir dos dicts.
    try:
        mi_raw = raw["market_info"]
        market = MarketInfo(
            symbol=str(mi_raw["symbol"]),
            category=str(mi_raw["category"]),
            best_bid=float(mi_raw["best_bid"]),
            best_ask=float(mi_raw["best_ask"]),
            mid_price=float(mi_raw["mid_price"]),
            last_price=(
                float(mi_raw["last_price"])
                if mi_raw.get("last_price") is not None
                else None
            ),
            reference_price=float(mi_raw["reference_price"]),
            min_order_qty=float(mi_raw["min_order_qty"]),
            max_order_qty=(
                float(mi_raw["max_order_qty"])
                if mi_raw.get("max_order_qty") is not None
                else None
            ),
            qty_step=float(mi_raw["qty_step"]),
            min_notional_value=float(mi_raw["min_notional_value"]),
            tick_size=float(mi_raw["tick_size"]),
        )
        as_raw = raw["account_state"]
        account = AccountState(
            wallet_balance_usdt=(
                float(as_raw["wallet_balance_usdt"])
                if as_raw.get("wallet_balance_usdt") is not None
                else None
            ),
            available_balance_usdt=(
                float(as_raw["available_balance_usdt"])
                if as_raw.get("available_balance_usdt") is not None
                else None
            ),
            open_positions_count=int(as_raw["open_positions_count"]),
            open_orders_count=int(as_raw["open_orders_count"]),
            leverage_confirmable=bool(as_raw["leverage_confirmable"]),
            leverage_value=(
                float(as_raw["leverage_value"])
                if as_raw.get("leverage_value") is not None
                else None
            ),
        )
        pr_raw = raw["proposal"]
        proposal = OrderProposal(
            symbol=str(pr_raw["symbol"]),
            side=str(pr_raw["side"]),
            reference_price=float(pr_raw["reference_price"]),
            qty=float(pr_raw["qty"]),
            position_size_usd=float(pr_raw["position_size_usd"]),
            stop_loss=float(pr_raw["stop_loss"]),
            take_profit=(
                float(pr_raw["take_profit"])
                if pr_raw.get("take_profit") is not None
                else None
            ),
            leverage=float(pr_raw["leverage"]),
            risk_usd=float(pr_raw["risk_usd"]),
            capital=float(pr_raw["capital"]),
        )
        generated_at = datetime.fromisoformat(raw["generated_at"])
    except (KeyError, ValueError, TypeError) as e:
        raise DemoApiBlueprintRejected(
            f"json_schema_invalid:{type(e).__name__}"
        ) from e

    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    age_seconds = (clock - generated_at).total_seconds()
    if age_seconds < 0:
        raise DemoApiBlueprintRejected(
            "generated_at no futuro — clock inconsistente"
        )
    if age_seconds > max_age_seconds:
        raise DemoApiBlueprintRejected(
            f"blueprint_stale: age={age_seconds:.0f}s > "
            f"max={max_age_seconds}s"
        )

    tp_rr_raw = raw.get("take_profit_rr")
    tp_rr_loaded = float(tp_rr_raw) if tp_rr_raw is not None else None
    blueprint = DemoApiBlueprint(
        blueprint_id=str(raw["blueprint_id"]),
        generated_at=generated_at,
        schema_version=_SCHEMA_VERSION,
        market_info=market,
        account_state=account,
        proposal=proposal,
        spread_pct=float(raw["spread_pct"]),
        notional_usd=float(raw["notional_usd"]),
        risk_pct=float(raw["risk_pct"]),
        readiness_summary=dict(raw.get("readiness_summary", {})),
        manual_confirmations_needed=tuple(
            raw.get("manual_confirmations_needed", [])
        ),
        command_preview=_sanitize_text(str(raw.get("command_preview", ""))),
        take_profit_rr=tp_rr_loaded,
    )
    return blueprint


# ---------------------------------------------------------------------------
# Bridge OrderProposal → SignalBlueprint (FASE 20)
# ---------------------------------------------------------------------------

def to_signal_blueprint(api_blueprint: DemoApiBlueprint) -> SignalBlueprint:
    """Constrói SignalBlueprint (FASE 20) a partir do DemoApiBlueprint.

    Rejeita take_profit=None — FASE 20 exige TP > 0.
    Validação de ordering BUY/SELL fica a cargo de
    SignalBlueprint.__post_init__.
    """
    proposal = api_blueprint.proposal
    if proposal.take_profit is None:
        raise DemoApiBlueprintRejected(
            "OrderProposal.take_profit=None — SignalBlueprint exige TP > 0"
        )
    side_lower = proposal.side.lower()
    if side_lower == "buy":
        side_enum = BlueprintSide.BUY
    elif side_lower == "sell":
        side_enum = BlueprintSide.SELL
    else:
        raise DemoApiBlueprintRejected(
            f"side inválido: {proposal.side!r}"
        )
    return SignalBlueprint(
        symbol=proposal.symbol,
        side=side_enum,
        entry_price=float(proposal.reference_price),
        stop_loss=float(proposal.stop_loss),
        take_profit=float(proposal.take_profit),
        position_size_usd=float(proposal.position_size_usd),
        strategy_name="demo_session_v1_api_driven",
        leverage=float(proposal.leverage),
    )
