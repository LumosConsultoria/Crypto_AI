"""
Tests - BybitDemoExecutor.submit_reduce_only_close (FASE 29)
================================================================
100% offline. ZERO network. Verifica defesa em profundidade do novo
metodo + retrocompat byte-a-byte do payload legado de
BybitClient.place_market_order.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
)


def _make_executor(*, env="demo"):
    client = MagicMock()
    client.environment = env
    client.has_credentials = True
    client.is_demo = (env == "demo")
    # spec evita que MagicMock interprete 'assert_*' como auto-assertion.
    mg = MagicMock(spec=[
        "assert_demo_execution_allowed",
        "assert_safe_mode",
    ])
    re_engine = MagicMock()
    ex = BybitDemoExecutor(
        client=client, mode_guard=mg, risk_engine=re_engine,
        confirm_demo_execution=True,
    )
    return ex, client, mg


class TestReduceOnlyCloseMethodExists:

    def test_method_exists(self):
        ex, _, _ = _make_executor()
        assert hasattr(ex, "submit_reduce_only_close")
        assert callable(ex.submit_reduce_only_close)

    def test_execute_method_preserved(self):
        ex, _, _ = _make_executor()
        # FASE 22 execute() method byte-a-byte preserved.
        assert hasattr(ex, "execute")


class TestReduceOnlyCloseValidation:

    def test_rejects_empty_symbol(self):
        ex, _, _ = _make_executor()
        with pytest.raises(ValueError):
            ex.submit_reduce_only_close(
                symbol="", side="sell", qty=0.003,
                dry_run=True, confirm_demo_execution=True,
            )

    def test_rejects_invalid_side(self):
        ex, _, _ = _make_executor()
        with pytest.raises(ValueError):
            ex.submit_reduce_only_close(
                symbol="BTCUSDT", side="long", qty=0.003,
                dry_run=True, confirm_demo_execution=True,
            )

    def test_rejects_zero_qty(self):
        ex, _, _ = _make_executor()
        with pytest.raises(ValueError):
            ex.submit_reduce_only_close(
                symbol="BTCUSDT", side="sell", qty=0.0,
                dry_run=True, confirm_demo_execution=True,
            )

    def test_rejects_dry_run_false_without_confirm(self):
        ex, _, _ = _make_executor()
        with pytest.raises(ValueError):
            ex.submit_reduce_only_close(
                symbol="BTCUSDT", side="sell", qty=0.003,
                dry_run=False, confirm_demo_execution=False,
            )


class TestReduceOnlyCloseDryRunDoesNotCallNetwork:

    def test_dry_run_does_not_invoke_place_market_order(self):
        ex, client, _ = _make_executor()
        r = ex.submit_reduce_only_close(
            symbol="BTCUSDT", side="sell", qty=0.003,
            dry_run=True, confirm_demo_execution=True,
        )
        assert r.success is True
        assert r.operation == "reduce_only_close"
        # client.place_market_order NUNCA foi chamado em dry_run
        client.place_market_order.assert_not_called()


class TestReduceOnlyCloseRealCallsWithReduceOnlyTrue:

    def test_real_call_sends_reduce_only_true(self):
        ex, client, _ = _make_executor()
        # Mock place_market_order success
        order_mock = MagicMock()
        order_mock.order_id = "ORD-12345"
        client.place_market_order.return_value = order_mock

        r = ex.submit_reduce_only_close(
            symbol="BTCUSDT", side="sell", qty=0.003,
            dry_run=False, confirm_demo_execution=True,
        )
        assert r.success is True
        client.place_market_order.assert_called_once()
        kwargs = client.place_market_order.call_args.kwargs
        assert kwargs.get("reduce_only") is True

    def test_exception_during_real_call_returns_failure(self):
        ex, client, _ = _make_executor()
        client.place_market_order.side_effect = RuntimeError(
            "network err"
        )
        r = ex.submit_reduce_only_close(
            symbol="BTCUSDT", side="sell", qty=0.003,
            dry_run=False, confirm_demo_execution=True,
        )
        assert r.success is False
        assert r.manual_review_required is True
        assert r.safety_halt_recommended is True


class TestNonDemoClientRejected:

    def test_testnet_client_rejected(self):
        client = MagicMock()
        client.environment = "testnet"
        client.has_credentials = True
        with pytest.raises(Exception) as ex_info:
            BybitDemoExecutor(
                client=client, mode_guard=MagicMock(),
                risk_engine=MagicMock(),
                confirm_demo_execution=True,
            )
        assert "demo" in str(ex_info.value).lower()


# ===========================================================================
# BybitClient.place_market_order retrocompat
# ===========================================================================

class TestBybitClientPlaceMarketOrderRetrocompat:

    def test_default_call_does_not_inject_reduce_only(self):
        """Sem `reduce_only`, payload NAO contem campo reduceOnly."""
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        from unittest.mock import patch

        # Patcheia _signed_request para capturar body.
        captured = {}

        def fake_signed_request(
            self, *, method, endpoint, body_payload=None, **kwargs
        ):
            captured["body"] = dict(body_payload or {})
            return {"orderId": "TEST", "result": {}}

        with patch.object(
            BybitClient, "_signed_request", fake_signed_request,
        ):
            # Construir client mock sem rede via override de __init__:
            # Como BybitClient instancia httpx, vamos usar parametros
            # legados mas patcheamos httpx tambem.
            with patch("httpx.Client"):
                client = BybitClient(use_testnet=True, api_key="K",
                                     api_secret="S")
            # Chamada legado sem reduce_only.
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
            )
        body = captured["body"]
        assert "reduceOnly" not in body, (
            "payload legado deve omitir reduceOnly"
        )

    def test_reduce_only_true_injects_field(self):
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        from unittest.mock import patch

        captured = {}

        def fake_signed_request(
            self, *, method, endpoint, body_payload=None, **kwargs
        ):
            captured["body"] = dict(body_payload or {})
            return {"orderId": "TEST", "result": {}}

        with patch.object(
            BybitClient, "_signed_request", fake_signed_request,
        ):
            with patch("httpx.Client"):
                client = BybitClient(use_testnet=True, api_key="K",
                                     api_secret="S")
            client.place_market_order(
                symbol="BTCUSDT", side="sell", qty=0.001,
                reduce_only=True,
            )
        body = captured["body"]
        assert body.get("reduceOnly") is True

    def test_payload_byte_a_byte_legado(self):
        """Garante que o body com SL+TP+sem reduce_only eh EXATAMENTE
        igual ao body legado FASE 22.4."""
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        from unittest.mock import patch

        captured = {}

        def fake_signed_request(
            self, *, method, endpoint, body_payload=None, **kwargs
        ):
            captured["body"] = dict(body_payload or {})
            return {"orderId": "TEST", "result": {}}

        expected_body = {
            "category": "linear",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderType": "Market",
            "qty": "0.001",
            "stopLoss": "60000",
            "takeProfit": "70000",
            "tpslMode": "Full",
            "slTriggerBy": "LastPrice",
            "slOrderType": "Market",
            "tpTriggerBy": "LastPrice",
            "tpOrderType": "Market",
        }

        with patch.object(
            BybitClient, "_signed_request", fake_signed_request,
        ):
            with patch("httpx.Client"):
                client = BybitClient(use_testnet=True, api_key="K",
                                     api_secret="S")
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=60000, take_profit=70000,
            )
        body = captured["body"]
        assert body == expected_body, (
            f"payload mudou! diff: {set(body.keys()) ^ set(expected_body.keys())}"
        )
        assert "reduceOnly" not in body
