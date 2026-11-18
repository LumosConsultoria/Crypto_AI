"""
Testes do BybitDemoExecutor — FASE 9 Fatia 4B
================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede. ZERO ordens enviadas.

Cobertura (Fatias 4A + 4B):
    - Constructor rejeita client testnet/mainnet; aceita demo.
    - safe_check_only(dry_run=True) NÃO chama get_balance.
    - safe_check_only(dry_run=False) chama get_balance EXATAMENTE 1x.
    - safe_check_only bloqueia sem ENABLE_DEMO_EXECUTION/confirm/modo demo.
    - execute(approved, dry_run=True) retorna sucesso simulado sem chamar
      place_market_order.
    - execute(approved, dry_run=False) IMPLEMENTADO (Fatia 4B):
        chama place_market_order após gates; reconcilia via get_order_status
        + get_positions; record_trade_opened apenas se FILLED;
        sem reduceOnly nem leverage no payload; erros sanitizados.
    - execute(blocked, dry_run=True/False) levanta ValueError (invariante).
    - cancel_pending(dry_run=True) simula; (dry_run=False) levanta
      NotImplementedError (fechamento manual via UI demo).
    - to_dict / get_summary / repr / log stream NÃO vazam secrets.
    - bybit_demo_linear migrou para OPT_IN (Fatia 4B); nunca ACTIVE.
    - BybitTestnetExecutor permanece importável e funcional (não tocado).
    - assert_live_allowed permanece intocado.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.exchange.base_exchange import OrderResult
from crypto_trading_bot.exchange.bybit_client import (
    BybitClient,
    BybitExecutionBlockedError,
)
from crypto_trading_bot.execution import (
    BybitDemoExecutor,
    BybitTestnetExecutor,
    DemoExecutionError,
    DemoExecutionResult,
    DemoTrade,
    DemoTradeStatus,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)


_FAKE_KEY_MARKER = "DEMO_FAKE_KEY_SHOULD_NEVER_APPEAR_XYZ"
_FAKE_SECRET_MARKER = "DEMO_FAKE_SECRET_SHOULD_NEVER_APPEAR_XYZ"


# ---------------------------------------------------------------------------
# Fixtures auxiliares
# ---------------------------------------------------------------------------

def _settings_demo_ready() -> Settings:
    """Settings com triple-lock demo satisfeito (mode + flag)."""
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=True,
        enable_testnet_execution=False,
        enable_live_trading=False,
        _env_file=None,  # type: ignore[arg-type]
    )


def _settings_demo_mode_only() -> Settings:
    """Demo mode mas ENABLE_DEMO_EXECUTION=false."""
    return Settings(
        trading_mode=TradingMode.DEMO,
        enable_demo_execution=False,
        _env_file=None,  # type: ignore[arg-type]
    )


def _settings_paper() -> Settings:
    return Settings(
        trading_mode=TradingMode.PAPER,
        enable_demo_execution=True,   # flag não importa se modo errado
        _env_file=None,  # type: ignore[arg-type]
    )


def _make_demo_mock_client(
    *,
    order_id: str = "DEMO_ORDER_001",
    order_status_response: dict | None = None,
    positions_response: list | None = None,
    positions: list | None = None,   # FASE 15 — alias mais curto
    order_history_response: list | None = None,
    executions_response: list | None = None,   # FASE 15
    place_raise: Exception | None = None,
    order_status_raise: Exception | None = None,
    positions_raise: Exception | None = None,
    order_history_raise: Exception | None = None,
    executions_raise: Exception | None = None,   # FASE 15
) -> MagicMock:
    """Mock de BybitClient com environment='demo' e respostas configuráveis."""
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "demo")
    type(client).use_testnet = property(lambda self: False)
    type(client).is_demo = property(lambda self: True)
    type(client).is_mainnet = property(lambda self: False)
    type(client).has_credentials = property(lambda self: True)

    # place_market_order
    if place_raise is not None:
        client.place_market_order.side_effect = place_raise
    else:
        client.place_market_order.return_value = OrderResult(
            order_id=order_id,
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.003,
            price=None,
            status="submitted",
            fee=0.0,
            timestamp=datetime.now(timezone.utc),
        )

    # get_order_status
    if order_status_raise is not None:
        client.get_order_status.side_effect = order_status_raise
    else:
        client.get_order_status.return_value = (
            order_status_response if order_status_response is not None
            else {"orderStatus": "Filled"}
        )

    # get_order_history (FASE 4B+ hardening fallback)
    if order_history_raise is not None:
        client.get_order_history.side_effect = order_history_raise
    else:
        client.get_order_history.return_value = (
            order_history_response if order_history_response is not None
            else []
        )

    # get_positions
    if positions_raise is not None:
        client.get_positions.side_effect = positions_raise
    else:
        # FASE 15 — `positions` (alias) tem preferência sobre `positions_response`
        # FASE 22.4 — default agora popula stopLoss/takeProfit espelhando o
        # signal default (_make_signal): SL=64000, TP=67000. Isso reflete um
        # cenario canonico Bybit Demo onde SL/TP foram anexados server-side.
        # Testes que precisam simular ausencia de SL/TP devem passar
        # explicitamente `positions=` com stopLoss="0"/takeProfit="0".
        pos_default = [{
            "symbol": "BTCUSDT", "side": "buy", "size": "0.003",
            "stopLoss": "64000.0", "takeProfit": "67000.0",
        }]
        if positions is not None:
            client.get_positions.return_value = positions
        elif positions_response is not None:
            client.get_positions.return_value = positions_response
        else:
            client.get_positions.return_value = pos_default

    # FASE 15 — get_executions (novo endpoint read-only). Default: vazio.
    if executions_raise is not None:
        client.get_executions.side_effect = executions_raise
    else:
        client.get_executions.return_value = (
            executions_response if executions_response is not None
            else []
        )
    return client


def _make_testnet_mock_client() -> MagicMock:
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "testnet")
    type(client).use_testnet = property(lambda self: True)
    type(client).is_demo = property(lambda self: False)
    type(client).has_credentials = property(lambda self: True)
    return client


def _make_mainnet_mock_client() -> MagicMock:
    client = MagicMock(spec=BybitClient)
    type(client).environment = property(lambda self: "mainnet")
    type(client).use_testnet = property(lambda self: False)
    type(client).is_demo = property(lambda self: False)
    type(client).is_mainnet = property(lambda self: True)
    type(client).has_credentials = property(lambda self: True)
    return client


def _make_signal(**overrides) -> TradingSignal:
    defaults = dict(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=200.0,
        leverage=1.0,
        strategy_name="test",
    )
    defaults.update(overrides)
    return TradingSignal(**defaults)


def _approved(signal: TradingSignal | None = None) -> RiskResult:
    return RiskResult(approved=True, reason="ok", signal=signal or _make_signal())


def _blocked_result(signal: TradingSignal | None = None) -> RiskResult:
    return RiskResult(approved=False, reason="risk-blocked", signal=signal or _make_signal())


def _make_executor(
    *,
    client: MagicMock | None = None,
    settings: Settings | None = None,
    confirm: bool = True,
    reconciliation_attempts: int = 2,
    reconciliation_delay_seconds: float = 0.0,
):
    """Cria executor com delay=0 por padrão p/ testes rápidos e attempts=2."""
    client = client or _make_demo_mock_client()
    settings = settings or _settings_demo_ready()
    guard = ModeGuard(settings=settings)
    risk = RiskEngine(initial_capital=5000.0)
    executor = BybitDemoExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        confirm_demo_execution=confirm,
        reconciliation_attempts=reconciliation_attempts,
        reconciliation_delay_seconds=reconciliation_delay_seconds,
    )
    return executor, client


# ===========================================================================
# Constructor: rejeita não-demo, aceita demo
# ===========================================================================

class TestConstructorEnvironmentGate:

    def test_rejects_testnet_client(self):
        client = _make_testnet_mock_client()
        with pytest.raises(BybitExecutionBlockedError, match="testnet"):
            _make_executor(client=client)

    def test_rejects_mainnet_client(self):
        client = _make_mainnet_mock_client()
        with pytest.raises(BybitExecutionBlockedError, match="mainnet"):
            _make_executor(client=client)

    def test_accepts_demo_client(self):
        executor, _ = _make_executor()
        assert executor is not None
        assert "demo" in repr(executor)


# ===========================================================================
# safe_check_only
# ===========================================================================

class TestSafeCheckOnly:

    def test_dry_run_does_not_call_get_balance(self):
        executor, client = _make_executor()
        r = executor.safe_check_only(dry_run=True)
        assert isinstance(r, DemoExecutionResult)
        assert r.success is True
        assert r.dry_run is True
        assert r.operation == "safe_check"
        client.get_balance.assert_not_called()

    def test_real_calls_get_balance_exactly_once(self):
        executor, client = _make_executor()
        r = executor.safe_check_only(dry_run=False)
        client.get_balance.assert_called_once()
        assert r.success is True
        assert r.operation == "safe_check"

    def test_blocked_without_confirm_demo_execution(self):
        executor, client = _make_executor(confirm=False)
        r = executor.safe_check_only(dry_run=False)
        assert r.success is False
        assert "modeguard" in r.reason.lower()
        client.get_balance.assert_not_called()

    def test_blocked_without_enable_demo_execution(self):
        executor, client = _make_executor(settings=_settings_demo_mode_only())
        r = executor.safe_check_only(dry_run=False)
        assert r.success is False
        client.get_balance.assert_not_called()

    def test_blocked_in_paper_mode(self):
        executor, client = _make_executor(settings=_settings_paper())
        r = executor.safe_check_only(dry_run=False)
        assert r.success is False
        client.get_balance.assert_not_called()

    def test_api_error_reason_uses_only_type_name(self):
        """Reason NUNCA inclui str(e) — só o type name é seguro."""
        client = _make_demo_mock_client()
        client.get_balance.side_effect = RuntimeError(
            f"contains api_key={_FAKE_KEY_MARKER}"
        )
        executor, _ = _make_executor(client=client)
        r = executor.safe_check_only(dry_run=False)
        assert r.success is False
        assert "RuntimeError" in r.reason
        assert _FAKE_KEY_MARKER not in r.reason
        # to_dict também não vaza
        assert _FAKE_KEY_MARKER not in json.dumps(r.to_dict())


# ===========================================================================
# execute: dry_run=True (simulação)
# ===========================================================================

class TestExecuteDryRunSimulation:

    def test_dry_run_returns_simulated_result(self):
        executor, client = _make_executor()
        r = executor.execute(_approved(), dry_run=True)
        assert isinstance(r, DemoExecutionResult)
        assert r.success is True
        assert r.dry_run is True
        assert r.operation == "place_order"
        client.place_market_order.assert_not_called()

    def test_rejects_unapproved_risk_result(self):
        """INVARIANTE: nunca executa risk_result.approved=False."""
        executor, client = _make_executor()
        with pytest.raises(ValueError, match="REJEITA"):
            executor.execute(_blocked_result(), dry_run=True)
        client.place_market_order.assert_not_called()

    def test_unapproved_rejected_even_with_dry_run_false(self):
        """Rejeição de unapproved tem precedência sobre o dry_run gate."""
        executor, client = _make_executor()
        with pytest.raises(ValueError):
            executor.execute(_blocked_result(), dry_run=False)
        client.place_market_order.assert_not_called()


# ===========================================================================
# execute: dry_run=False (Fatia 4B — envio real gated)
# ===========================================================================

class TestExecuteRealPlaceOrderPayload:
    """Payload enviado a BybitClient.place_market_order."""

    def test_calls_place_market_order_exactly_once_when_all_gates_pass(self):
        executor, client = _make_executor()
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is True
        client.place_market_order.assert_called_once()

    def test_payload_calculates_qty_from_position_size_div_entry_price(self):
        # FASE 14 (qty hardening): qty é normalizado ao qty_step (default
        # 0.001 para BTCUSDT linear demo) com ROUND_DOWN. Para position=200,
        # entry=65000 → qty_raw ≈ 0.003076923 → normalizado a 0.003.
        sig = _make_signal(position_size_usd=200.0, entry_price=65000.0)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        kwargs = client.place_market_order.call_args.kwargs
        assert kwargs["qty"] == pytest.approx(0.003)

    def test_payload_passes_symbol_from_signal(self):
        sig = _make_signal(symbol="BTCUSDT")
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["symbol"] == "BTCUSDT"

    def test_payload_passes_side_buy_lowercase(self):
        sig = _make_signal(side=OrderSide.BUY)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["side"] == "buy"

    def test_payload_passes_side_sell_lowercase(self):
        sig = _make_signal(side=OrderSide.SELL)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["side"] == "sell"

    def test_payload_passes_stop_loss(self):
        sig = _make_signal(stop_loss_price=64000.0)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["stop_loss"] == 64000.0

    def test_payload_passes_take_profit_when_present(self):
        sig = _make_signal(take_profit_price=67000.0)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["take_profit"] == 67000.0

    def test_payload_passes_take_profit_none_when_signal_has_none(self):
        sig = _make_signal(take_profit_price=None)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        assert client.place_market_order.call_args.kwargs["take_profit"] is None

    def test_payload_does_not_pass_reduce_only_kwarg(self):
        """reduceOnly não é suportado nesta fatia — não passar ao client."""
        executor, client = _make_executor()
        executor.execute(_approved(), dry_run=False)
        kwargs = client.place_market_order.call_args.kwargs
        assert "reduceOnly" not in kwargs
        assert "reduce_only" not in kwargs

    def test_payload_does_not_pass_leverage_kwarg(self):
        """leverage NÃO é enviado a Bybit (é setting de conta na UI)."""
        executor, client = _make_executor()
        executor.execute(_approved(), dry_run=False)
        assert "leverage" not in client.place_market_order.call_args.kwargs


class TestExecuteRealReconciliation:

    def test_calls_get_order_status_for_reconciliation(self):
        executor, client = _make_executor()
        executor.execute(_approved(), dry_run=False)
        client.get_order_status.assert_called_once()

    def test_calls_get_positions_for_reconciliation(self):
        executor, client = _make_executor()
        executor.execute(_approved(), dry_run=False)
        client.get_positions.assert_called_once()

    def test_status_filled_when_bybit_returns_filled(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"}
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade is not None
        assert r.trade.status is DemoTradeStatus.FILLED

    def test_status_filled_when_bybit_returns_partiallyfilled(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "PartiallyFilled"}
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED

    def test_status_canceled_when_bybit_returns_cancelled(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Cancelled"}
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.CANCELED

    def test_status_reconciliation_failed_when_orderstatus_empty(self):
        """Hardening: orderStatus ausente + history vazio + sem executions +
        positions vazias → RECONCILIATION_FAILED. FASE 15: positions vazio
        para impedir triangulação de fallback."""
        client = _make_demo_mock_client(
            order_status_response={},
            positions=[],   # FASE 15 — sem posição → sem triangulação
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_status_submitted_when_orderstatus_is_new(self):
        """orderStatus=New (ordem ativa, ainda não preenchida) → SUBMITTED."""
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "New"}
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.SUBMITTED

    def test_reconciliation_get_order_status_failure_falls_back_to_history(self):
        """Hardening: order_status falha → tenta order_history."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("network glitch"),
            order_history_response=[{"orderId": "DEMO_ORDER_001", "orderStatus": "Filled"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        # Fallback confirmou FILLED
        assert r.success is True
        assert r.trade.status is DemoTradeStatus.FILLED
        assert "order_history_fallback" in r.reason

    def test_reconciliation_all_endpoints_fail_results_in_reconciliation_failed(self):
        """Hardening: realtime + history + executions + positions todos
        falham → RECONCILIATION_FAILED (FASE 15)."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("realtime down"),
            order_history_raise=ConnectionError("history down"),
            positions=[],   # FASE 15 — sem posição triangulável
        )
        # Garante que executions também não confirme nada
        client.get_executions.return_value = []
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is True  # ordem foi enviada
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED
        assert r.trade.raw_order_status == {}
        assert "RECONCILIAÇÃO FALHOU" in r.reason

    def test_reconciliation_get_positions_failure_does_not_break(self):
        client = _make_demo_mock_client(
            positions_raise=ConnectionError("positions unavailable")
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is True
        # position_snapshot fica vazio (best-effort)
        assert r.trade.position_snapshot == {}


class TestReconciliationHardening:
    """FASE 9 — hardening pós-primeira-ordem-real:
    retry de get_order_status + fallback get_order_history + classificação precisa.
    """

    def test_get_order_status_retries_until_success(self):
        """1ª tentativa raise + 2ª retorna FILLED → executor usa attempt 2."""
        # responses por chamada via side_effect tupla
        client = _make_demo_mock_client()
        client.get_order_status.side_effect = [
            ConnectionError("transient race"),
            {"orderStatus": "Filled"},
        ]
        executor, _ = _make_executor(
            client=client,
            reconciliation_attempts=3,
            reconciliation_delay_seconds=0.0,
        )
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED
        assert client.get_order_status.call_count == 2
        # Fallback de history NÃO foi acionado
        client.get_order_history.assert_not_called()

    def test_reconciliation_attempts_respected(self):
        """attempts=4 → tenta até 4× antes do fallback."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("perm")
        )
        executor, _ = _make_executor(
            client=client,
            reconciliation_attempts=4,
            reconciliation_delay_seconds=0.0,
        )
        executor.execute(_approved(), dry_run=False)
        assert client.get_order_status.call_count == 4
        # Depois o fallback de history é tentado UMA vez
        assert client.get_order_history.call_count == 1

    def test_constructor_rejects_attempts_below_1(self):
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        client = _make_demo_mock_client()
        settings = _settings_demo_ready()
        guard = ModeGuard(settings=settings)
        risk = RiskEngine(initial_capital=5000.0)
        with pytest.raises(ValueError, match="reconciliation_attempts"):
            BybitDemoExecutor(
                client=client, mode_guard=guard, risk_engine=risk,
                confirm_demo_execution=True,
                reconciliation_attempts=0,
            )

    def test_constructor_rejects_negative_delay(self):
        client = _make_demo_mock_client()
        settings = _settings_demo_ready()
        guard = ModeGuard(settings=settings)
        risk = RiskEngine(initial_capital=5000.0)
        with pytest.raises(ValueError, match="reconciliation_delay"):
            BybitDemoExecutor(
                client=client, mode_guard=guard, risk_engine=risk,
                confirm_demo_execution=True,
                reconciliation_delay_seconds=-0.1,
            )

    def test_history_fallback_confirms_canceled(self):
        """realtime falha + history confirma Cancelled → CANCELED."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[
                {"orderId": "DEMO_ORDER_001", "orderStatus": "Cancelled"}
            ],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.CANCELED
        assert "order_history_fallback" in r.reason

    def test_history_empty_list_results_in_reconciliation_failed(self):
        """realtime erro + history vazio + executions vazio + positions vazio →
        RECONCILIATION_FAILED (FASE 15)."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            positions=[],   # FASE 15
        )
        client.get_executions.return_value = []
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_orderstatus_partiallyfilled_classified_as_filled(self):
        """PartiallyFilled também conta como FILLED para record_trade_opened."""
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "PartiallyFilled"}
        )
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED
        assert spy.call_count == 1

    def test_reconciliation_method_in_reason(self):
        """Reason cita método de reconciliação para auditoria."""
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"}
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert "order_status_attempt_1" in r.reason


class TestExecuteRealRiskEngineNotification:

    def test_record_trade_opened_called_only_on_filled_status(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"}
        )
        executor, _ = _make_executor(client=client)
        # Espia record_trade_opened
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        executor.execute(_approved(), dry_run=False)
        assert spy.call_count == 1

    def test_record_trade_opened_not_called_on_submitted_status(self):
        """orderStatus=New (active) → SUBMITTED → não notifica RiskEngine."""
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "New"}
        )
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        executor.execute(_approved(), dry_run=False)
        # Status SUBMITTED → não notifica
        assert spy.call_count == 0

    def test_record_trade_opened_not_called_on_reconciliation_failed(self):
        """Hardening: reconciliação falhou → NÃO notifica RiskEngine.
        Política conservadora: sem FILLED confirmado, sem record.
        FASE 15: positions/executions vazios para garantir fallback total."""
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_raise=ConnectionError("net2"),
            positions=[],
        )
        client.get_executions.return_value = []
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED
        assert spy.call_count == 0

    def test_record_trade_opened_not_called_on_canceled_status(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Cancelled"}
        )
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        executor.execute(_approved(), dry_run=False)
        assert spy.call_count == 0

    def test_record_trade_opened_failure_does_not_break_result(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"}
        )
        executor, _ = _make_executor(client=client)
        executor._risk_engine.record_trade_opened = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("risk update glitch")
        )
        r = executor.execute(_approved(), dry_run=False)
        # Mesmo com falha em record_trade_opened, resultado segue success=True
        assert r.success is True


class TestExecuteRealGates:

    def test_blocked_when_confirm_demo_execution_false(self):
        executor, client = _make_executor(confirm=False)
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is False
        assert "modeguard" in r.reason.lower()
        client.place_market_order.assert_not_called()

    def test_blocked_when_enable_demo_execution_false(self):
        executor, client = _make_executor(settings=_settings_demo_mode_only())
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is False
        client.place_market_order.assert_not_called()

    def test_blocked_in_paper_mode(self):
        executor, client = _make_executor(settings=_settings_paper())
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is False
        client.place_market_order.assert_not_called()

    def test_blocked_when_entry_price_zero(self):
        sig = _make_signal()
        # Mock signal with entry_price=0 (TradingSignal would reject; bypass via object_setattr)
        bad_sig = TradingSignal(
            symbol="BTCUSDT", side=OrderSide.BUY,
            entry_price=1.0,  # válido no construtor
            stop_loss_price=0.99,
            take_profit_price=None,
            position_size_usd=100.0,
            leverage=1.0,
            strategy_name="test",
        )
        # Força entry_price=0 via object.__setattr__ (TradingSignal pode ser frozen)
        try:
            object.__setattr__(bad_sig, "entry_price", 0.0)
        except Exception:
            # Se não conseguir, pular este teste — invariância garantida em outra camada
            pytest.skip("TradingSignal não permite mutação; entry_price já validado upstream")
        executor, client = _make_executor()
        r = executor.execute(_approved(bad_sig), dry_run=False)
        assert r.success is False
        assert "entry_price" in r.reason.lower()
        client.place_market_order.assert_not_called()


class TestExecuteRealErrorHandling:

    def test_handles_bybit_execution_blocked_error_safely(self):
        client = _make_demo_mock_client(
            place_raise=BybitExecutionBlockedError(
                f"sensitive: {_FAKE_KEY_MARKER}"
            )
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is False
        # BybitExecutionBlockedError pode incluir str(e); mas markers ficam no log,
        # não nos secrets reais do operador. Aqui só validamos que não crashou.
        assert "bybit" in r.reason.lower() or "bloqueou" in r.reason.lower()

    def test_handles_generic_exception_with_type_name_only(self):
        """Em erros genéricos, reason usa apenas type(e).__name__ — nunca str(e)."""
        client = _make_demo_mock_client(
            place_raise=RuntimeError(f"X-BAPI-SIGN: secret_sig api_key={_FAKE_KEY_MARKER}")
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.success is False
        assert "RuntimeError" in r.reason
        # Marker NUNCA chega ao reason (executor sanitiza na origem)
        assert _FAKE_KEY_MARKER not in r.reason
        assert "X-BAPI-SIGN" not in r.reason

    def test_failure_to_dict_does_not_leak_after_real_path_error(self):
        client = _make_demo_mock_client(
            place_raise=RuntimeError(
                f"X-BAPI-SIGN: sig Authorization: Bearer x api_key={_FAKE_KEY_MARKER}"
            )
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        blob = json.dumps(r.to_dict())
        assert _FAKE_KEY_MARKER not in blob
        assert "X-BAPI-SIGN" not in blob


class TestExecuteRealTradeRecord:

    def test_trade_stored_in_submitted_trades_after_success(self):
        executor, _ = _make_executor()
        executor.execute(_approved(), dry_run=False)
        assert len(executor.submitted_trades) == 1

    def test_trade_id_uses_demo_prefix(self):
        executor, _ = _make_executor()
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.trade_id.startswith("BT_DEMO_")
        assert "BTCUSDT" in r.trade.trade_id


class TestExecuteRealLogStream:

    def test_log_stream_does_not_leak_marker_during_real_execute(self):
        from loguru import logger as loguru_logger
        client = _make_demo_mock_client(
            place_raise=RuntimeError(
                f"contains api_key={_FAKE_KEY_MARKER}"
            )
        )
        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            executor, _ = _make_executor(client=client)
            executor.execute(_approved(), dry_run=False)
        finally:
            loguru_logger.remove(sink_id)
        captured = buf.getvalue()
        assert _FAKE_KEY_MARKER not in captured
        assert _FAKE_SECRET_MARKER not in captured


# ===========================================================================
# cancel_pending: write real bloqueado
# ===========================================================================

class TestCancelPending:

    def test_dry_run_returns_simulated_result(self):
        executor, client = _make_executor()
        r = executor.cancel_pending("BTCUSDT", "order_xyz", dry_run=True)
        assert r.success is True
        assert r.operation == "cancel_order"
        assert r.dry_run is True
        client.cancel_order.assert_not_called()

    def test_real_cancel_raises_not_implemented(self):
        executor, client = _make_executor()
        with pytest.raises(NotImplementedError, match="BLOQUEAD"):
            executor.cancel_pending("BTCUSDT", "order_xyz", dry_run=False)
        client.cancel_order.assert_not_called()


# ===========================================================================
# Sanitização e segurança
# ===========================================================================

class TestSanitization:

    def test_repr_does_not_leak_secrets(self):
        executor, _ = _make_executor()
        r = repr(executor)
        # repr é seguro: nunca inclui valores de api_key/secret
        for marker in (_FAKE_KEY_MARKER, _FAKE_SECRET_MARKER,
                       "api_key=", "api_secret=", "secret="):
            assert marker not in r

    def test_result_to_dict_does_not_leak_secrets(self):
        executor, _ = _make_executor()
        r = executor.execute(_approved(), dry_run=True)
        blob = json.dumps(r.to_dict())
        for marker in (_FAKE_KEY_MARKER, _FAKE_SECRET_MARKER,
                       "x-bapi-sign", "authorization"):
            assert marker.lower() not in blob.lower()

    def test_get_summary_is_safe(self):
        executor, _ = _make_executor()
        summary = executor.get_summary()
        blob = json.dumps(summary)
        for marker in (_FAKE_KEY_MARKER, _FAKE_SECRET_MARKER,
                       "x-bapi-sign", "authorization"):
            assert marker.lower() not in blob.lower()
        # Estrutura mínima esperada
        assert summary["n_submitted"] == 0
        assert summary["n_filled"] == 0
        assert summary["n_canceled"] == 0

    def test_log_stream_during_safe_check_does_not_leak(self):
        """Captura loguru durante init + safe_check. Marker não pode aparecer."""
        from loguru import logger as loguru_logger

        # Simula erro contendo marker — executor deve sanitizar via type name only
        client = _make_demo_mock_client()
        client.get_balance.side_effect = RuntimeError(
            f"oops: api_key={_FAKE_KEY_MARKER} X-BAPI-SIGN: sig123"
        )
        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            executor, _ = _make_executor(client=client)
            _ = executor.safe_check_only(dry_run=False)
        finally:
            loguru_logger.remove(sink_id)

        captured = buf.getvalue()
        assert _FAKE_KEY_MARKER not in captured
        assert _FAKE_SECRET_MARKER not in captured


# ===========================================================================
# Garantias arquiteturais não-regressivas
# ===========================================================================

class TestArchitecturalInvariants:

    def test_bybit_testnet_executor_still_importable(self):
        """BybitTestnetExecutor não foi tocado — continua exposto e funcional."""
        assert BybitTestnetExecutor is not None
        # E continua REJEITANDO clients não-testnet por design (assinatura própria)
        demo_client = _make_demo_mock_client()
        settings = Settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
            _env_file=None,  # type: ignore[arg-type]
        )
        guard = ModeGuard(settings=settings)
        risk = RiskEngine(initial_capital=5000.0)
        # demo client tem use_testnet=False (definido no mock); testnet executor recusa
        with pytest.raises(BybitExecutionBlockedError):
            BybitTestnetExecutor(
                client=demo_client,
                mode_guard=guard,
                risk_engine=risk,
                confirm_testnet_execution=True,
            )

    def test_provider_bybit_demo_linear_promoted_to_opt_in_not_active(self):
        """Fatia 4B promove para OPT_IN. NUNCA vira ACTIVE nesta fatia."""
        from crypto_trading_bot.execution import get_registry
        from crypto_trading_bot.execution.provider_capability import ProviderStatus
        entry = get_registry().get("bybit_demo_linear")
        assert entry.status is ProviderStatus.OPT_IN
        # NÃO vira ACTIVE
        assert entry.status is not ProviderStatus.ACTIVE

    def test_assert_live_allowed_still_blocks(self):
        """ModeGuard.assert_live_allowed continua intocado e operacional."""
        guard = ModeGuard(settings=_settings_demo_ready())
        with pytest.raises(TradingModeError):
            # Mesmo com triple-lock demo OK, assert_live_allowed bloqueia
            # porque trading_mode != live.
            guard.assert_live_allowed(confirm_live_trading=True)

    def test_demo_executor_module_does_not_import_subprocess_or_uiautomation(self):
        """Defesa: módulo do executor não importa subprocess, selenium, etc."""
        import sys
        mod = sys.modules[BybitDemoExecutor.__module__]
        for forbidden in ("subprocess", "selenium", "playwright", "pyautogui"):
            assert not hasattr(mod, forbidden)
