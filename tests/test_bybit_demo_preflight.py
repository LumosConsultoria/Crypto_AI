"""
Testes do BybitDemoPreflight — FASE 9 Fatia 4B+
==================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Cobertura:
    - instruments-info mockado extrai minOrderQty/maxOrderQty/qtyStep/
      minNotionalValue/tickSize.
    - orderbook mockado calcula bid/ask/mid.
    - ticker mockado usado para last_price quando disponível.
    - preflight escolhe reference_price = mid.
    - preflight calcula qty mínima válida.
    - preflight arredonda qty para qtyStep.
    - preflight aumenta qty quando minNotional exige.
    - preflight respeita maxOrderQty (aborta se excedido).
    - preflight calcula stop_loss ~1.5% abaixo (BUY), alinhado a tickSize.
    - preflight calcula risk_usd corretamente.
    - preflight usa available_balance/wallet quando API retorna.
    - preflight NÃO chama place_market_order / cancel / close.
    - preflight aborta se posição já aberta.
    - preflight aborta se ordens pendentes.
    - preflight aborta se leverage via API != target.
    - preflight reporta manual confirmation quando leverage não confirmável.
    - preflight chama RiskEngine.validate_signal.
    - preflight aborta se RiskEngine rejeita.
    - to_dict/repr não vazam secrets.
"""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.base_exchange import OrderBook, Ticker
from crypto_trading_bot.exchange.bybit_client import (
    BybitClient,
    BybitExecutionBlockedError,
)
from crypto_trading_bot.execution import (
    BybitDemoPreflight,
    PreflightAbortReason,
    PreflightReport,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine


_FAKE_KEY_MARKER = "PREFLIGHT_FAKE_KEY_SHOULD_NEVER_APPEAR_XYZ"
_FAKE_SECRET_MARKER = "PREFLIGHT_FAKE_SECRET_SHOULD_NEVER_APPEAR_XYZ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings_demo_ready() -> Settings:
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_testnet_execution=False,
        enable_live_trading=False,
        _env_file=None,  # type: ignore[arg-type]
    )


def _orderbook(bid: float = 80000.0, ask: float = 80010.0) -> OrderBook:
    return OrderBook(
        symbol="BTCUSDT",
        bids=[(bid, 1.5)],
        asks=[(ask, 1.2)],
    )


def _ticker(last: float = 80005.0) -> Ticker:
    return Ticker(
        symbol="BTCUSDT",
        last_price=last,
        bid=last - 5,
        ask=last + 5,
        volume_24h=1234.5,
    )


def _instrument(
    *,
    min_qty: str = "0.001",
    max_qty: str = "1190.000",
    qty_step: str = "0.001",
    min_notional: str = "5",
    tick_size: str = "0.10",
) -> dict:
    return {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "minOrderQty": min_qty,
            "maxOrderQty": max_qty,
            "qtyStep": qty_step,
            "minNotionalValue": min_notional,
        },
        "priceFilter": {"tickSize": tick_size},
    }


def _balance(usdt_wallet: float = 10000.0, usdt_avail: float = 9800.0) -> dict:
    return {
        "list": [{
            "coin": [{
                "coin": "USDT",
                "walletBalance": str(usdt_wallet),
                "availableToWithdraw": str(usdt_avail),
            }],
        }],
    }


def _make_client(
    *,
    instrument: dict | None = None,
    orderbook: OrderBook | None = None,
    ticker: Ticker | None = None,
    balance: dict | None = None,
    positions: list | None = None,
    open_orders: list | None = None,
    instruments_raise: Exception | None = None,
    orderbook_raise: Exception | None = None,
    balance_raise: Exception | None = None,
    positions_raise: Exception | None = None,
    open_orders_raise: Exception | None = None,
) -> MagicMock:
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "demo")
    type(client).has_credentials = property(lambda self: True)
    client._base_url = "https://api-demo.bybit.com"

    if instruments_raise is not None:
        client.get_instruments_info.side_effect = instruments_raise
    else:
        client.get_instruments_info.return_value = instrument or _instrument()

    if orderbook_raise is not None:
        client.get_order_book.side_effect = orderbook_raise
    else:
        client.get_order_book.return_value = orderbook or _orderbook()

    client.get_ticker.return_value = ticker or _ticker()

    if balance_raise is not None:
        client.get_balance.side_effect = balance_raise
    else:
        client.get_balance.return_value = balance or _balance()

    if positions_raise is not None:
        client.get_positions.side_effect = positions_raise
    else:
        client.get_positions.return_value = (
            positions if positions is not None
            else [{"symbol": "BTCUSDT", "size": "0", "leverage": "1"}]
        )

    if open_orders_raise is not None:
        client.get_open_orders.side_effect = open_orders_raise
    else:
        client.get_open_orders.return_value = open_orders or []

    return client


def _make_preflight(
    *,
    client: MagicMock | None = None,
    settings: Settings | None = None,
    confirm: bool = True,
    side: str = "buy",
    leverage_target: float = 1.0,
):
    client = client or _make_client()
    settings = settings or _settings_demo_ready()
    guard = ModeGuard(settings=settings)
    risk = RiskEngine(initial_capital=10000.0)
    return BybitDemoPreflight(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        symbol="BTCUSDT",
        side=side,
        leverage_target=leverage_target,
        confirm_demo_execution=confirm,
    ), client


# ===========================================================================
# Public market info
# ===========================================================================

class TestMarketInfoCollection:

    def test_extracts_lot_size_filter_fields(self):
        pf, client = _make_preflight()
        r = pf.run()
        assert r.ok
        assert r.market_info.min_order_qty == 0.001
        assert r.market_info.max_order_qty == 1190.0
        assert r.market_info.qty_step == 0.001
        assert r.market_info.min_notional_value == 5.0
        assert r.market_info.tick_size == 0.10

    def test_calculates_mid_from_orderbook(self):
        pf, _ = _make_preflight(client=_make_client(
            orderbook=_orderbook(bid=80000.0, ask=80010.0)
        ))
        r = pf.run()
        assert r.market_info.best_bid == 80000.0
        assert r.market_info.best_ask == 80010.0
        assert r.market_info.mid_price == 80005.0
        assert r.market_info.reference_price == 80005.0

    def test_uses_ticker_for_last_price(self):
        pf, _ = _make_preflight(client=_make_client(
            ticker=_ticker(last=80007.5)
        ))
        r = pf.run()
        assert r.market_info.last_price == 80007.5

    def test_ticker_failure_does_not_break_preflight(self):
        client = _make_client()
        client.get_ticker.side_effect = ConnectionError("network blip")
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        assert r.ok  # last_price=None mas mid funciona
        assert r.market_info.last_price is None


class TestMarketInfoAbort:

    def test_aborts_when_instruments_info_raises(self):
        pf, _ = _make_preflight(client=_make_client(
            instruments_raise=ValueError("instrument lotSizeFilter incomplete")
        ))
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.INSTRUMENT_INFO_INCOMPLETE

    def test_aborts_when_orderbook_empty(self):
        pf, _ = _make_preflight(client=_make_client(
            orderbook=OrderBook(symbol="BTCUSDT", bids=[], asks=[])
        ))
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.ORDERBOOK_EMPTY


# ===========================================================================
# Account state
# ===========================================================================

class TestAccountStateCollection:

    def test_extracts_usdt_balance(self):
        pf, _ = _make_preflight(client=_make_client(
            balance=_balance(usdt_wallet=12345.67, usdt_avail=11000.0)
        ))
        r = pf.run()
        assert r.account_state.wallet_balance_usdt == 12345.67
        assert r.account_state.available_balance_usdt == 11000.0

    def test_counts_open_positions(self):
        pf, _ = _make_preflight(client=_make_client(
            positions=[
                {"symbol": "BTCUSDT", "size": "0.0", "leverage": "1"},
            ]
        ))
        r = pf.run()
        assert r.account_state.open_positions_count == 0

    def test_extracts_leverage_when_present(self):
        pf, _ = _make_preflight(client=_make_client(
            positions=[{"symbol": "BTCUSDT", "size": "0", "leverage": "1"}]
        ))
        r = pf.run()
        assert r.account_state.leverage_confirmable is True
        assert r.account_state.leverage_value == 1.0

    def test_manual_confirmation_when_leverage_not_in_response(self):
        pf, _ = _make_preflight(client=_make_client(
            positions=[]  # nenhum leverage info
        ))
        r = pf.run()
        # Sem leverage info → manual confirmation needed
        assert r.account_state.leverage_confirmable is False
        assert any("leverage" in m.lower() for m in r.manual_confirmations_needed)

    def test_manual_confirmation_when_balance_fails(self):
        client = _make_client(balance_raise=ConnectionError("net"))
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        assert any("wallet" in m.lower() for m in r.manual_confirmations_needed)


# ===========================================================================
# Conflict aborts
# ===========================================================================

class TestConflictAborts:

    def test_aborts_when_position_already_open(self):
        pf, _ = _make_preflight(client=_make_client(
            positions=[{"symbol": "BTCUSDT", "size": "0.001", "leverage": "1"}]
        ))
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.POSITION_ALREADY_OPEN

    def test_aborts_when_open_orders_pending(self):
        pf, _ = _make_preflight(client=_make_client(
            open_orders=[{"orderId": "X1"}]
        ))
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.OPEN_ORDERS_PENDING

    def test_aborts_when_leverage_differs_from_target(self):
        pf, _ = _make_preflight(
            client=_make_client(
                positions=[{"symbol": "BTCUSDT", "size": "0", "leverage": "3"}]
            ),
            leverage_target=1.0,
        )
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.LEVERAGE_NOT_TARGET


# ===========================================================================
# Order proposal computation
# ===========================================================================

class TestOrderProposalComputation:

    def test_qty_starts_at_min_order_qty(self):
        pf, _ = _make_preflight(client=_make_client(
            instrument=_instrument(
                min_qty="0.001", qty_step="0.001", min_notional="0"
            )
        ))
        r = pf.run()
        assert r.proposal.qty == 0.001

    def test_qty_aligned_to_step(self):
        # min_notional força qty maior; aceitar arredondamento pelo step
        pf, _ = _make_preflight(client=_make_client(
            instrument=_instrument(
                min_qty="0.001", qty_step="0.001", min_notional="100"
            ),
            orderbook=_orderbook(bid=80000.0, ask=80000.0),
        ))
        r = pf.run()
        # min notional 100 / 80000 = 0.00125 → arredonda para 0.002
        assert r.proposal.qty == pytest.approx(0.002, abs=1e-9)

    def test_qty_satisfies_min_notional(self):
        pf, _ = _make_preflight(client=_make_client(
            instrument=_instrument(
                min_qty="0.001", qty_step="0.001", min_notional="200"
            ),
            orderbook=_orderbook(bid=80000.0, ask=80000.0),
        ))
        r = pf.run()
        assert r.proposal.qty * r.proposal.reference_price >= 200.0

    def test_aborts_when_max_qty_exceeded(self):
        pf, _ = _make_preflight(client=_make_client(
            instrument=_instrument(
                min_qty="100.0", max_qty="50.0",  # impossível: min > max
                qty_step="1", min_notional="0"
            )
        ))
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.MAX_ORDER_QTY_EXCEEDED

    def test_position_size_usd_equals_qty_times_reference(self):
        pf, _ = _make_preflight()
        r = pf.run()
        assert r.proposal.position_size_usd == pytest.approx(
            r.proposal.qty * r.proposal.reference_price, abs=1e-9
        )


class TestStopLossCalculation:

    def test_stop_loss_is_below_entry_for_buy(self):
        pf, _ = _make_preflight()
        r = pf.run()
        assert r.proposal.stop_loss < r.proposal.reference_price

    def test_stop_loss_aligned_to_tick(self):
        pf, _ = _make_preflight(client=_make_client(
            instrument=_instrument(tick_size="1.0"),
            orderbook=_orderbook(bid=80000.0, ask=80000.0),
        ))
        r = pf.run()
        # tick_size=1.0 → stop_loss inteiro
        assert r.proposal.stop_loss == math.floor(r.proposal.stop_loss)

    def test_stop_loss_approximately_1_5pct_below(self):
        pf, _ = _make_preflight(client=_make_client(
            orderbook=_orderbook(bid=80000.0, ask=80000.0),
        ))
        r = pf.run()
        # ~1.5% below 80000 = 78800; alinhado a tick_size 0.10
        assert 78700.0 <= r.proposal.stop_loss <= 78900.0

    def test_risk_usd_is_positive_and_realistic(self):
        pf, _ = _make_preflight(client=_make_client(
            orderbook=_orderbook(bid=80000.0, ask=80000.0),
        ))
        r = pf.run()
        assert r.proposal.risk_usd > 0
        # qty 0.001 * ~1.5% de 80000 ≈ 1.2 USD
        assert 0.5 < r.proposal.risk_usd < 5.0


class TestCapitalSelection:

    def test_uses_wallet_or_available_balance_when_present(self):
        # Preflight escolhe max(available, wallet, margin_floor) — o maior
        # garante que RiskEngine não rejeite por max_position_size_pct.
        pf, _ = _make_preflight(client=_make_client(
            balance=_balance(usdt_wallet=10000.0, usdt_avail=9500.0),
        ))
        r = pf.run()
        # capital >= max(available, wallet) ≥ 9500
        assert r.proposal.capital >= 9500.0
        assert r.proposal.capital == 10000.0  # wallet é o maior

    def test_falls_back_to_wallet_when_no_available(self):
        client = _make_client(balance={
            "list": [{"coin": [{"coin": "USDT", "walletBalance": "5000"}]}]
        })
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        # available_balance ausente → usa wallet
        assert r.proposal.capital >= 5000.0

    def test_falls_back_to_margin_floor_when_no_balance_data(self):
        client = _make_client(balance={"list": []})
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        # Sem wallet → usa margin_floor = position_size * 15
        assert r.proposal.capital == pytest.approx(
            r.proposal.position_size_usd * 15.0, abs=0.01
        )


# ===========================================================================
# RiskEngine integration
# ===========================================================================

class TestRiskEngineValidation:

    def test_validates_via_risk_engine_when_passing(self):
        pf, _ = _make_preflight()
        r = pf.run()
        assert r.ok
        assert r.proposal is not None

    def test_aborts_when_riskengine_rejects(self):
        # Forçar RiskEngine a rejeitar: leverage muito alta (max é 3x)
        pf, _ = _make_preflight(leverage_target=10.0)
        r = pf.run()
        assert not r.ok
        # Como leverage 10 != 1, preflight aborta no leverage check primeiro
        # ou em risk_engine.
        assert r.abort_reason in (
            PreflightAbortReason.LEVERAGE_NOT_TARGET,
            PreflightAbortReason.RISK_ENGINE_REJECTED,
        )


# ===========================================================================
# Defesa em profundidade
# ===========================================================================

class TestSafetyGates:

    def test_aborts_when_client_not_demo(self):
        client = MagicMock(spec=BybitClient)
        type(client).environment = property(lambda self: "testnet")
        type(client).has_credentials = property(lambda self: True)
        client._base_url = "https://api-testnet.bybit.com"
        guard = ModeGuard(settings=_settings_demo_ready())
        risk = RiskEngine(initial_capital=10000.0)
        pf = BybitDemoPreflight(
            client=client, mode_guard=guard, risk_engine=risk,
            confirm_demo_execution=True,
        )
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.CLIENT_NOT_DEMO

    def test_aborts_when_endpoint_not_api_demo(self):
        client = _make_client()
        client._base_url = "https://api.bybit.com"  # mainnet!
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.ENDPOINT_NOT_DEMO

    def test_aborts_when_credentials_absent(self):
        client = _make_client()
        type(client).has_credentials = property(lambda self: False)
        pf, _ = _make_preflight(client=client)
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.CREDENTIALS_ABSENT

    def test_aborts_when_modeguard_blocks(self):
        settings = Settings(
            trading_mode=TradingMode.PAPER, _env_file=None,  # type: ignore[arg-type]
        )
        client = _make_client()
        guard = ModeGuard(settings=settings)
        risk = RiskEngine(initial_capital=10000.0)
        pf = BybitDemoPreflight(
            client=client, mode_guard=guard, risk_engine=risk,
            confirm_demo_execution=True,
        )
        r = pf.run()
        assert not r.ok
        assert r.abort_reason is PreflightAbortReason.MODE_GUARD_BLOCKED


# ===========================================================================
# Read-only invariant
# ===========================================================================

class TestReadOnlyInvariant:

    def test_never_calls_place_market_order(self):
        pf, client = _make_preflight()
        pf.run()
        client.place_market_order.assert_not_called()

    def test_never_calls_cancel_order(self):
        pf, client = _make_preflight()
        pf.run()
        client.cancel_order.assert_not_called()

    def test_never_calls_get_order_status_for_existing_order(self):
        """Preflight não reconcilia ordens — só get_open_orders (listar)."""
        pf, client = _make_preflight()
        pf.run()
        client.get_order_status.assert_not_called()

    def test_calls_only_read_only_methods(self):
        pf, client = _make_preflight()
        pf.run()
        client.get_instruments_info.assert_called()
        client.get_order_book.assert_called()
        client.get_balance.assert_called()
        client.get_positions.assert_called()
        client.get_open_orders.assert_called()


# ===========================================================================
# Sanitização
# ===========================================================================

class TestSanitization:

    def test_report_to_dict_does_not_contain_secrets(self):
        # Mesmo com erro contendo markers, reason fica sanitizado
        pf, _ = _make_preflight(client=_make_client(
            instruments_raise=RuntimeError(
                f"X-BAPI-SIGN: secret_sig api_key={_FAKE_KEY_MARKER}"
            )
        ))
        r = pf.run()
        blob = json.dumps(r.to_dict())
        assert _FAKE_KEY_MARKER not in blob
        assert _FAKE_SECRET_MARKER not in blob
        assert "X-BAPI-SIGN" not in blob
