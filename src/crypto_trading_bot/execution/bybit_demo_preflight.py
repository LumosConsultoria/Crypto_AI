"""
BybitDemoPreflight — FASE 9 Fatia 4B+
=======================================
Preflight automático para preparar uma ordem mínima Bybit Demo Trading.

⚠️  100% READ-ONLY. NUNCA chama place_market_order, cancel_order ou
    close_position. NUNCA envia ordem.
⚠️  Apenas chamadas read-only:
       públicas:  get_instruments_info, get_order_book, get_ticker
       privadas:  get_balance, get_positions, get_open_orders
⚠️  Objetivo: coletar tudo o que a API pode fornecer e propor a menor
    ordem demo válida (qty, position_size_usd, stop_loss, risk_usd).
⚠️  Sem hardcode de minOrderQty, qtyStep, minNotional, tickSize, capital,
    sizing, leverage ou risco. Tudo vem da API ou do RiskEngine.
⚠️  Resultado é um PreflightReport imutável e sanitizado. NUNCA contém
    api_key, api_secret, assinatura ou headers sensíveis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
    BybitExecutionBlockedError,
)
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    TradingSignal,
)

if TYPE_CHECKING:
    pass

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


EXPECTED_DEMO_ENDPOINT = "https://api-demo.bybit.com"


# ---------------------------------------------------------------------------
# Tipos auxiliares
# ---------------------------------------------------------------------------

class PreflightAbortReason(str, Enum):
    """Por que o preflight abortou (NUNCA descreve via str(e) de exceção)."""
    CLIENT_NOT_DEMO = "client_not_demo"
    ENDPOINT_NOT_DEMO = "endpoint_not_demo"
    CREDENTIALS_ABSENT = "credentials_absent"
    MODE_GUARD_BLOCKED = "mode_guard_blocked"
    INSTRUMENT_INFO_INCOMPLETE = "instrument_info_incomplete"
    ORDERBOOK_EMPTY = "orderbook_empty"
    PRIVATE_READ_FAILED = "private_read_failed"
    POSITION_ALREADY_OPEN = "position_already_open"
    OPEN_ORDERS_PENDING = "open_orders_pending"
    LEVERAGE_NOT_TARGET = "leverage_not_target"
    MIN_NOTIONAL_UNSATISFIABLE = "min_notional_unsatisfiable"
    MAX_ORDER_QTY_EXCEEDED = "max_order_qty_exceeded"
    STOP_LOSS_INVALID = "stop_loss_invalid"
    REFERENCE_PRICE_INVALID = "reference_price_invalid"
    RISK_ENGINE_REJECTED = "risk_engine_rejected"
    # FASE 13 — readiness para Demo v2 com TP atrelado à ordem de entrada.
    TAKE_PROFIT_INVALID = "take_profit_invalid"


@dataclass(frozen=True)
class MarketInfo:
    """Dados públicos de mercado coletados via API. Sem credenciais."""
    symbol: str
    category: str
    best_bid: float
    best_ask: float
    mid_price: float
    last_price: Optional[float]
    reference_price: float
    min_order_qty: float
    max_order_qty: Optional[float]
    qty_step: float
    min_notional_value: float
    tick_size: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "category": self.category,
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "last_price": self.last_price,
            "reference_price": self.reference_price,
            "min_order_qty": self.min_order_qty,
            "max_order_qty": self.max_order_qty,
            "qty_step": self.qty_step,
            "min_notional_value": self.min_notional_value,
            "tick_size": self.tick_size,
        }


@dataclass(frozen=True)
class AccountState:
    """Estado da conta demo coletado via endpoints privados read-only.

    ⚠️  NUNCA contém api_key/api_secret/headers/assinatura.
    """
    wallet_balance_usdt: Optional[float]
    available_balance_usdt: Optional[float]
    open_positions_count: int
    open_orders_count: int
    leverage_confirmable: bool
    leverage_value: Optional[float]

    def to_dict(self) -> dict:
        return {
            "wallet_balance_usdt": self.wallet_balance_usdt,
            "available_balance_usdt": self.available_balance_usdt,
            "open_positions_count": self.open_positions_count,
            "open_orders_count": self.open_orders_count,
            "leverage_confirmable": self.leverage_confirmable,
            "leverage_value": self.leverage_value,
        }


@dataclass(frozen=True)
class OrderProposal:
    """Proposta calculada para a ordem mínima. NUNCA enviada por este módulo."""
    symbol: str
    side: str
    reference_price: float
    qty: float
    position_size_usd: float
    stop_loss: float
    take_profit: Optional[float]
    leverage: float
    risk_usd: float
    capital: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "reference_price": self.reference_price,
            "qty": self.qty,
            "position_size_usd": self.position_size_usd,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "leverage": self.leverage,
            "risk_usd": self.risk_usd,
            "capital": self.capital,
        }


@dataclass(frozen=True)
class PreflightReport:
    """Resultado imutável e sanitizado do preflight."""
    ok: bool
    market_info: Optional[MarketInfo]
    account_state: Optional[AccountState]
    proposal: Optional[OrderProposal]
    abort_reason: Optional[PreflightAbortReason]
    abort_details: str
    manual_confirmations_needed: tuple = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "market_info": self.market_info.to_dict() if self.market_info else None,
            "account_state": (
                self.account_state.to_dict() if self.account_state else None
            ),
            "proposal": self.proposal.to_dict() if self.proposal else None,
            "abort_reason": (
                self.abort_reason.value if self.abort_reason else None
            ),
            "abort_details": self.abort_details,
            "manual_confirmations_needed": list(self.manual_confirmations_needed),
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class BybitDemoPreflight:
    """
    Coleta dados e propõe uma ordem mínima Bybit Demo.

    ⚠️  100% read-only — NUNCA chama place_market_order / cancel / close.
    ⚠️  Não envia ordem nem em dry_run=False.

    Uso típico (sempre via script com triple-lock demo):
        preflight = BybitDemoPreflight(
            client=BybitClient(environment="demo", api_key=..., api_secret=...),
            mode_guard=ModeGuard(settings=...),
            risk_engine=RiskEngine(initial_capital=...),
            symbol="BTCUSDT",
            side="buy",
            leverage_target=1.0,
            confirm_demo_execution=True,
        )
        report = preflight.run()
        if report.ok:
            print(report.to_dict())  # sanitizado
    """

    SL_BUY_FACTOR = 0.985    # ~1.5% abaixo do entry para BUY
    SL_SELL_FACTOR = 1.015   # ~1.5% acima do entry para SELL
    CAPITAL_MARGIN_FACTOR = 15.0  # capital = max(15 * position_size_usd, wallet)

    def __init__(
        self,
        client: BybitClient,
        mode_guard: ModeGuard,
        risk_engine: RiskEngine,
        *,
        symbol: str = "BTCUSDT",
        side: str = "buy",
        leverage_target: float = 1.0,
        confirm_demo_execution: bool = False,
        # FASE 13 — Demo v2 readiness: factor relativo ao reference_price.
        # None (default) preserva o preflight da FASE 9 (sem TP).
        # BUY: factor > 1.0 (ex.: 1.03 → tp 3% acima do entry).
        # SELL: factor < 1.0 (ex.: 0.97 → tp 3% abaixo do entry).
        target_take_profit_factor: Optional[float] = None,
        # FASE 22.1 — TP via Risk-Reward (RR) relativo ao stop_loss.
        # Conservador/editável. None (default) preserva o comportamento
        # anterior. Mutuamente exclusivo com target_take_profit_factor.
        # BUY:  TP = entry + (entry - SL) * RR
        # SELL: TP = entry - (SL - entry) * RR
        # Alinhado ao tick_size do instrumento (sem hardcode).
        target_take_profit_rr: Optional[float] = None,
    ) -> None:
        self._client = client
        self._mode_guard = mode_guard
        self._risk_engine = risk_engine
        self._symbol = symbol
        self._side = side.lower()
        self._leverage_target = float(leverage_target)
        self._confirm_demo_execution = bool(confirm_demo_execution)
        if (
            target_take_profit_factor is not None
            and target_take_profit_rr is not None
        ):
            raise ValueError(
                "BybitDemoPreflight: target_take_profit_factor e "
                "target_take_profit_rr são mutuamente exclusivos"
            )
        self._target_take_profit_factor = (
            float(target_take_profit_factor)
            if target_take_profit_factor is not None
            else None
        )
        self._target_take_profit_rr = (
            float(target_take_profit_rr)
            if target_take_profit_rr is not None
            else None
        )
        if self._target_take_profit_rr is not None and self._target_take_profit_rr <= 0:
            raise ValueError(
                f"target_take_profit_rr deve ser > 0; recebido "
                f"{self._target_take_profit_rr}"
            )

    @property
    def target_take_profit_rr(self) -> Optional[float]:
        """RR usado para calcular TP (None se TP via factor ou ausente)."""
        return self._target_take_profit_rr

    # ------------------------------------------------------------------- run

    def run(self) -> PreflightReport:
        """Orquestra o preflight. NUNCA levanta — sempre retorna PreflightReport."""
        manual: List[str] = []

        # 1. Sanity de cliente/ambiente — defesa em profundidade
        if getattr(self._client, "environment", None) != "demo":
            return self._abort(
                PreflightAbortReason.CLIENT_NOT_DEMO,
                f"client.environment={getattr(self._client, 'environment', None)!r}",
                manual,
            )
        if getattr(self._client, "_base_url", None) != EXPECTED_DEMO_ENDPOINT:
            return self._abort(
                PreflightAbortReason.ENDPOINT_NOT_DEMO,
                f"base_url mismatch (expected {EXPECTED_DEMO_ENDPOINT})",
                manual,
            )
        if not self._client.has_credentials:
            return self._abort(
                PreflightAbortReason.CREDENTIALS_ABSENT,
                "api_key/api_secret absent in client",
                manual,
            )

        # 2. ModeGuard triple-lock demo
        try:
            self._mode_guard.assert_demo_execution_allowed(
                confirm_demo_execution=self._confirm_demo_execution,
                context="BybitDemoPreflight",
            )
        except Exception as e:
            return self._abort(
                PreflightAbortReason.MODE_GUARD_BLOCKED,
                f"{type(e).__name__}",
                manual,
            )

        # 3. Public: market info
        try:
            market_info = self._collect_market_info()
        except ValueError as e:
            msg = str(e).lower()
            if "orderbook" in msg or "bid" in msg or "ask" in msg:
                reason = PreflightAbortReason.ORDERBOOK_EMPTY
            else:
                reason = PreflightAbortReason.INSTRUMENT_INFO_INCOMPLETE
            return self._abort(reason, f"{type(e).__name__}", manual)
        except Exception as e:
            return self._abort(
                PreflightAbortReason.INSTRUMENT_INFO_INCOMPLETE,
                f"{type(e).__name__}",
                manual,
            )

        _audit.info(
            f"preflight.market_info | symbol={market_info.symbol} | "
            f"mid={market_info.mid_price} | minQty={market_info.min_order_qty} | "
            f"qtyStep={market_info.qty_step} | minNotional={market_info.min_notional_value}"
        )

        # 4. Private: account state
        try:
            account_state = self._collect_account_state(manual)
        except BybitExecutionBlockedError as e:
            return self._abort(
                PreflightAbortReason.PRIVATE_READ_FAILED,
                f"{type(e).__name__}",
                manual,
                market_info=market_info,
            )
        except Exception as e:
            return self._abort(
                PreflightAbortReason.PRIVATE_READ_FAILED,
                f"{type(e).__name__}",
                manual,
                market_info=market_info,
            )

        _audit.info(
            f"preflight.account_state | symbol={self._symbol} | "
            f"open_positions={account_state.open_positions_count} | "
            f"open_orders={account_state.open_orders_count} | "
            f"leverage_confirmable={account_state.leverage_confirmable}"
        )

        # 5. Conflict checks
        if account_state.open_positions_count > 0:
            return self._abort(
                PreflightAbortReason.POSITION_ALREADY_OPEN,
                f"{account_state.open_positions_count} open position(s) in {self._symbol}",
                manual, market_info=market_info, account_state=account_state,
            )
        if account_state.open_orders_count > 0:
            return self._abort(
                PreflightAbortReason.OPEN_ORDERS_PENDING,
                f"{account_state.open_orders_count} open order(s) in {self._symbol}",
                manual, market_info=market_info, account_state=account_state,
            )

        # 6. Leverage check
        if account_state.leverage_confirmable:
            if account_state.leverage_value != self._leverage_target:
                return self._abort(
                    PreflightAbortReason.LEVERAGE_NOT_TARGET,
                    f"leverage={account_state.leverage_value} != target {self._leverage_target}",
                    manual, market_info=market_info, account_state=account_state,
                )
        else:
            manual.append(
                f"leverage não pôde ser confirmada via API; confirme manualmente "
                f"na UI Bybit Demo que está em {self._leverage_target}x antes de executar"
            )

        # 7. Compute proposal
        try:
            proposal = self._compute_order_proposal(market_info, account_state)
        except _MinNotionalError as e:
            return self._abort(
                PreflightAbortReason.MIN_NOTIONAL_UNSATISFIABLE,
                str(e), manual,
                market_info=market_info, account_state=account_state,
            )
        except _MaxOrderQtyError as e:
            return self._abort(
                PreflightAbortReason.MAX_ORDER_QTY_EXCEEDED,
                str(e), manual,
                market_info=market_info, account_state=account_state,
            )
        except _StopLossError as e:
            return self._abort(
                PreflightAbortReason.STOP_LOSS_INVALID,
                str(e), manual,
                market_info=market_info, account_state=account_state,
            )
        except _ReferencePriceError as e:
            return self._abort(
                PreflightAbortReason.REFERENCE_PRICE_INVALID,
                str(e), manual,
                market_info=market_info, account_state=account_state,
            )
        except _TakeProfitError as e:
            return self._abort(
                PreflightAbortReason.TAKE_PROFIT_INVALID,
                str(e), manual,
                market_info=market_info, account_state=account_state,
            )

        # 8. RiskEngine validation com capital PROPOSTO (não o injetado)
        # O risk_engine injetado é usado como SOURCE de RiskConfig; criamos
        # uma instância fresca com initial_capital=proposal.capital para que
        # a validação reflita as condições reais da ordem proposta.
        side_enum = OrderSide.BUY if self._side == "buy" else OrderSide.SELL
        signal = TradingSignal(
            symbol=proposal.symbol,
            side=side_enum,
            entry_price=proposal.reference_price,
            stop_loss_price=proposal.stop_loss,
            take_profit_price=proposal.take_profit,
            position_size_usd=proposal.position_size_usd,
            leverage=proposal.leverage,
            strategy_name="cli_bybit_demo_preflight",
        )
        validation_engine = RiskEngine(
            initial_capital=float(proposal.capital),
            config=self._risk_engine._config,  # reusa RiskConfig do injetado
        )
        risk_result = validation_engine.validate_signal(signal)
        if not risk_result.approved:
            return self._abort(
                PreflightAbortReason.RISK_ENGINE_REJECTED,
                f"block_reason={risk_result.block_reason}",
                manual, market_info=market_info,
                account_state=account_state, proposal=proposal,
            )

        # 9. Sucesso
        return PreflightReport(
            ok=True,
            market_info=market_info,
            account_state=account_state,
            proposal=proposal,
            abort_reason=None,
            abort_details="",
            manual_confirmations_needed=tuple(manual),
        )

    # ------------------------------------------------------------ collectors

    def _collect_market_info(self) -> MarketInfo:
        info = self._client.get_instruments_info(self._symbol, category="linear")
        lot = info.get("lotSizeFilter") or {}
        price_filter = info.get("priceFilter") or {}

        try:
            min_qty = float(lot["minOrderQty"])
            qty_step = float(lot["qtyStep"])
            tick_size = float(price_filter["tickSize"])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"instrument lotSizeFilter/priceFilter incomplete: {type(e).__name__}"
            )

        max_qty_raw = lot.get("maxOrderQty")
        try:
            max_qty: Optional[float] = (
                float(max_qty_raw) if max_qty_raw is not None else None
            )
        except (TypeError, ValueError):
            max_qty = None

        min_notional_raw = lot.get("minNotionalValue", 0)
        try:
            min_notional = float(min_notional_raw or 0)
        except (TypeError, ValueError):
            min_notional = 0.0

        # Public: orderbook
        ob = self._client.get_order_book(self._symbol, depth=1, category="linear")
        best_bid = ob.best_bid
        best_ask = ob.best_ask
        if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
            raise ValueError("orderbook empty or invalid")
        mid = (best_bid + best_ask) / 2.0

        # Optional: ticker
        last_price: Optional[float] = None
        try:
            ticker = self._client.get_ticker(self._symbol, category="linear")
            lp = getattr(ticker, "last_price", None)
            if lp is not None and lp > 0:
                last_price = float(lp)
        except Exception:
            pass

        return MarketInfo(
            symbol=self._symbol,
            category="linear",
            best_bid=float(best_bid),
            best_ask=float(best_ask),
            mid_price=mid,
            last_price=last_price,
            reference_price=mid,
            min_order_qty=min_qty,
            max_order_qty=max_qty,
            qty_step=qty_step,
            min_notional_value=min_notional,
            tick_size=tick_size,
        )

    def _collect_account_state(self, manual: List[str]) -> AccountState:
        wallet_usdt: Optional[float] = None
        available_usdt: Optional[float] = None
        try:
            balance_resp = self._client.get_balance(account_type="UNIFIED")
            items = balance_resp.get("list", []) if isinstance(balance_resp, dict) else []
            if items:
                coins = items[0].get("coin", []) if isinstance(items[0], dict) else []
                for c in coins:
                    if not isinstance(c, dict):
                        continue
                    if c.get("coin") == "USDT":
                        try:
                            wallet_usdt = float(c.get("walletBalance", 0) or 0)
                        except (TypeError, ValueError):
                            pass
                        # availableToWithdraw é o típico em Unified; fallback availableBalance
                        for key in ("availableToWithdraw", "availableBalance"):
                            v = c.get(key)
                            if v is not None and v != "":
                                try:
                                    available_usdt = float(v)
                                    break
                                except (TypeError, ValueError):
                                    pass
                        break
        except Exception as e:
            manual.append(
                f"wallet balance não pôde ser lido via API ({type(e).__name__}); "
                "operador deve confirmar saldo manualmente"
            )

        # Positions
        leverage_confirmable = False
        leverage_value: Optional[float] = None
        open_positions_count = 0
        try:
            positions = self._client.get_positions(
                symbol=self._symbol, category="linear"
            )
            for p in positions:
                if not isinstance(p, dict):
                    continue
                try:
                    size = float(p.get("size", 0) or 0)
                    if size > 0:
                        open_positions_count += 1
                except (TypeError, ValueError):
                    pass
                lev = p.get("leverage")
                if lev is not None and lev != "":
                    try:
                        leverage_value = float(lev)
                        leverage_confirmable = True
                    except (TypeError, ValueError):
                        pass
        except Exception as e:
            manual.append(
                f"positions não puderam ser lidas via API ({type(e).__name__}); "
                "operador deve confirmar manualmente"
            )

        # Open orders
        # FASE 22.2 — captura BybitAPIError separadamente para expor
        # retCode/retMsg sanitizados no manual_confirmation. Sem secrets.
        open_orders_count = 0
        try:
            orders = self._client.get_open_orders(self._symbol, category="linear")
            open_orders_count = len(orders)
        except BybitAPIError as e:
            # retCode/retMsg vem da Bybit (numero + descricao curta),
            # nao sao credenciais. Truncado defensivamente em 120 chars.
            ret_msg_safe = str(getattr(e, "ret_msg", "") or "")[:120]
            manual.append(
                f"open orders nao puderam ser lidas via API (BybitAPIError "
                f"retCode={getattr(e, 'ret_code', 'unknown')} "
                f"retMsg='{ret_msg_safe}'); "
                "operador deve confirmar manualmente"
            )
        except Exception as e:
            manual.append(
                f"open orders nao puderam ser lidas via API "
                f"({type(e).__name__}); "
                "operador deve confirmar manualmente"
            )

        return AccountState(
            wallet_balance_usdt=wallet_usdt,
            available_balance_usdt=available_usdt,
            open_positions_count=open_positions_count,
            open_orders_count=open_orders_count,
            leverage_confirmable=leverage_confirmable,
            leverage_value=leverage_value,
        )

    # ---------------------------------------------------------- computation

    def _compute_order_proposal(
        self, market: MarketInfo, account: AccountState,
    ) -> OrderProposal:
        if market.reference_price <= 0:
            raise _ReferencePriceError(f"reference_price={market.reference_price}")

        # Start with minimum valid qty
        qty = float(market.min_order_qty)

        # Satisfy minNotionalValue if specified
        if market.min_notional_value > 0:
            current_notional = qty * market.reference_price
            if current_notional < market.min_notional_value:
                qty_needed_raw = market.min_notional_value / market.reference_price
                steps_needed = math.ceil(qty_needed_raw / market.qty_step)
                qty = steps_needed * market.qty_step

        # Defensive: align qty to step
        steps = max(1, round(qty / market.qty_step))
        qty = steps * market.qty_step
        # If after step alignment, still below minOrderQty, bump up one step
        while qty < market.min_order_qty:
            qty += market.qty_step

        # Verify minNotional satisfied
        if market.min_notional_value > 0:
            if qty * market.reference_price < market.min_notional_value:
                raise _MinNotionalError(
                    f"qty {qty} * ref {market.reference_price} < minNotional {market.min_notional_value}"
                )

        # Check max
        if market.max_order_qty is not None and qty > market.max_order_qty:
            raise _MaxOrderQtyError(
                f"qty {qty} > maxOrderQty {market.max_order_qty}"
            )

        position_size_usd = qty * market.reference_price

        # Stop loss
        if self._side == "buy":
            sl_raw = market.reference_price * self.SL_BUY_FACTOR
            sl_ticks = math.floor(sl_raw / market.tick_size)
            stop_loss = sl_ticks * market.tick_size
            if stop_loss >= market.reference_price or stop_loss <= 0:
                raise _StopLossError(
                    f"stop_loss {stop_loss} invalid vs ref {market.reference_price}"
                )
        else:
            # SELL: stop above entry
            sl_raw = market.reference_price * self.SL_SELL_FACTOR
            sl_ticks = math.ceil(sl_raw / market.tick_size)
            stop_loss = sl_ticks * market.tick_size
            if stop_loss <= market.reference_price:
                raise _StopLossError(
                    f"stop_loss {stop_loss} invalid vs ref {market.reference_price}"
                )

        # Risk in USD
        if self._side == "buy":
            risk_usd = qty * (market.reference_price - stop_loss)
        else:
            risk_usd = qty * (stop_loss - market.reference_price)

        # Capital selection (sem hardcode):
        # Preferência: usar available_balance/wallet da API.
        # Fallback: position_size_usd * CAPITAL_MARGIN_FACTOR (para satisfazer
        # max_position_size_pct do RiskEngine sem exigir capital arbitrário do usuário).
        margin_floor = position_size_usd * self.CAPITAL_MARGIN_FACTOR
        candidates: List[float] = []
        if account.available_balance_usdt and account.available_balance_usdt > 0:
            candidates.append(account.available_balance_usdt)
        if account.wallet_balance_usdt and account.wallet_balance_usdt > 0:
            candidates.append(account.wallet_balance_usdt)
        candidates.append(margin_floor)
        capital = max(candidates)

        # FASE 13 — Take profit opcional (Demo v2 readiness).
        # FASE 22.1 — preferir RR-based quando disponível; fallback factor.
        # Validação determinística + tick alignment + sanity vs. side.
        take_profit: Optional[float] = None
        if self._target_take_profit_rr is not None:
            # RR-based: TP = entry + (entry - SL) * RR  (BUY)
            #           TP = entry - (SL - entry) * RR  (SELL)
            sl_distance = abs(market.reference_price - stop_loss)
            if sl_distance <= 0:
                raise _TakeProfitError(
                    "RR-based TP: distancia entry-SL <= 0"
                )
            if self._side == "buy":
                tp_raw = market.reference_price + sl_distance * self._target_take_profit_rr
                tp_ticks = math.floor(tp_raw / market.tick_size)
                take_profit = tp_ticks * market.tick_size
                if take_profit <= market.reference_price:
                    raise _TakeProfitError(
                        f"BUY RR TP {take_profit} <= reference "
                        f"{market.reference_price} (rr={self._target_take_profit_rr})"
                    )
            else:  # sell
                tp_raw = market.reference_price - sl_distance * self._target_take_profit_rr
                tp_ticks = math.ceil(tp_raw / market.tick_size)
                take_profit = tp_ticks * market.tick_size
                if take_profit >= market.reference_price or take_profit <= 0:
                    raise _TakeProfitError(
                        f"SELL RR TP {take_profit} invalid vs reference "
                        f"{market.reference_price} (rr={self._target_take_profit_rr})"
                    )
        elif self._target_take_profit_factor is not None:
            tp_raw = market.reference_price * self._target_take_profit_factor
            if self._side == "buy":
                if self._target_take_profit_factor <= 1.0:
                    raise _TakeProfitError(
                        f"BUY exige factor > 1.0: "
                        f"{self._target_take_profit_factor}"
                    )
                tp_ticks = math.floor(tp_raw / market.tick_size)
                take_profit = tp_ticks * market.tick_size
                if take_profit <= market.reference_price:
                    raise _TakeProfitError(
                        f"BUY take_profit {take_profit} "
                        f"<= reference {market.reference_price}"
                    )
            else:  # sell
                if self._target_take_profit_factor >= 1.0:
                    raise _TakeProfitError(
                        f"SELL exige factor < 1.0: "
                        f"{self._target_take_profit_factor}"
                    )
                tp_ticks = math.ceil(tp_raw / market.tick_size)
                take_profit = tp_ticks * market.tick_size
                if take_profit >= market.reference_price or take_profit <= 0:
                    raise _TakeProfitError(
                        f"SELL take_profit {take_profit} invalid vs "
                        f"reference {market.reference_price}"
                    )

        return OrderProposal(
            symbol=market.symbol,
            side=self._side,
            reference_price=market.reference_price,
            qty=qty,
            position_size_usd=position_size_usd,
            stop_loss=stop_loss,
            take_profit=take_profit,
            leverage=self._leverage_target,
            risk_usd=risk_usd,
            capital=capital,
        )

    # ----------------------------------------------------------------- abort

    def _abort(
        self,
        reason: PreflightAbortReason,
        details: str,
        manual: List[str],
        *,
        market_info: Optional[MarketInfo] = None,
        account_state: Optional[AccountState] = None,
        proposal: Optional[OrderProposal] = None,
    ) -> PreflightReport:
        _logger.warning(
            f"BybitDemoPreflight ABORT | reason={reason.value} | details={details}"
        )
        return PreflightReport(
            ok=False,
            market_info=market_info,
            account_state=account_state,
            proposal=proposal,
            abort_reason=reason,
            abort_details=details,
            manual_confirmations_needed=tuple(manual),
        )


# ---------------------------------------------------------------------------
# Exceções internas para classificar abort por tipo
# ---------------------------------------------------------------------------

class _MinNotionalError(ValueError):
    pass


class _MaxOrderQtyError(ValueError):
    pass


class _StopLossError(ValueError):
    pass


class _ReferencePriceError(ValueError):
    pass


class _TakeProfitError(ValueError):
    """FASE 13 — TP inválido relativo ao reference_price/side."""
    pass
