"""
Testes dos métodos read-only adicionados no BybitClient — FASE 9 Fatia 4B+
=============================================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede.

Cobertura:
    - get_instruments_info (público): parse correto, erro se list vazia.
    - get_open_orders (signed): parse correto, retorna lista vazia se sem ordens.
    - Os endpoints chamados são os corretos.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
    BybitExecutionBlockedError,
)


def _make_http_mock(json_response: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_response
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# get_instruments_info — PÚBLICO
# ---------------------------------------------------------------------------

class TestGetInstrumentsInfo:

    def test_parses_lot_size_filter_and_price_filter(self):
        with patch("httpx.Client") as MockHttp:
            instance = MockHttp.return_value
            instance.get.return_value = _make_http_mock({
                "retCode": 0, "retMsg": "OK",
                "result": {
                    "list": [{
                        "symbol": "BTCUSDT",
                        "lotSizeFilter": {
                            "minOrderQty": "0.001",
                            "maxOrderQty": "1190.000",
                            "qtyStep": "0.001",
                            "minNotionalValue": "5",
                        },
                        "priceFilter": {"tickSize": "0.10"},
                    }],
                },
            })
            client = BybitClient(environment="testnet")
            info = client.get_instruments_info("BTCUSDT")
            assert info["symbol"] == "BTCUSDT"
            assert info["lotSizeFilter"]["minOrderQty"] == "0.001"
            assert info["priceFilter"]["tickSize"] == "0.10"

    def test_calls_correct_endpoint_and_params(self):
        with patch("httpx.Client") as MockHttp:
            instance = MockHttp.return_value
            instance.get.return_value = _make_http_mock({
                "retCode": 0, "retMsg": "OK",
                "result": {
                    "list": [{
                        "symbol": "BTCUSDT",
                        "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001"},
                        "priceFilter": {"tickSize": "0.10"},
                    }],
                },
            })
            client = BybitClient(environment="demo")
            client.get_instruments_info("BTCUSDT", category="linear")
            call_args = instance.get.call_args
            assert call_args.args[0] == "/v5/market/instruments-info"
            assert call_args.kwargs["params"]["category"] == "linear"
            assert call_args.kwargs["params"]["symbol"] == "BTCUSDT"

    def test_raises_value_error_when_list_empty(self):
        with patch("httpx.Client") as MockHttp:
            instance = MockHttp.return_value
            instance.get.return_value = _make_http_mock({
                "retCode": 0, "retMsg": "OK",
                "result": {"list": []},
            })
            client = BybitClient(environment="testnet")
            with pytest.raises(ValueError, match="Nenhuma informação"):
                client.get_instruments_info("NONEXISTENT")

    def test_propagates_bybit_api_error(self):
        with patch("httpx.Client") as MockHttp:
            instance = MockHttp.return_value
            instance.get.return_value = _make_http_mock({
                "retCode": 10001, "retMsg": "invalid symbol",
            })
            client = BybitClient(environment="testnet")
            with pytest.raises(BybitAPIError):
                client.get_instruments_info("BAD")


# ---------------------------------------------------------------------------
# get_open_orders — SIGNED (requer credentials + ambiente não-mainnet)
# ---------------------------------------------------------------------------

class TestGetOpenOrders:

    def _patch_signed_request(self, monkeypatch, response: dict):
        """Patcha _signed_request para evitar httpx + HMAC reais."""
        import crypto_trading_bot.exchange.bybit_client as bc_mod

        def fake_signed_request(self, method, endpoint, query_params=None, body_payload=None, timestamp_ms=None):
            return response.get("result", {})

        monkeypatch.setattr(bc_mod.BybitClient, "_signed_request", fake_signed_request)

    def test_returns_empty_list_when_no_open_orders(self, monkeypatch):
        with patch("httpx.Client"):
            self._patch_signed_request(
                monkeypatch, {"result": {"list": []}}
            )
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            orders = client.get_open_orders("BTCUSDT")
            assert orders == []

    def test_returns_list_of_open_orders(self, monkeypatch):
        with patch("httpx.Client"):
            self._patch_signed_request(monkeypatch, {"result": {"list": [
                {"orderId": "X1", "symbol": "BTCUSDT", "side": "Buy"},
                {"orderId": "X2", "symbol": "BTCUSDT", "side": "Sell"},
            ]}})
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            orders = client.get_open_orders("BTCUSDT")
            assert len(orders) == 2
            assert orders[0]["orderId"] == "X1"

    def test_blocks_without_credentials_in_demo(self):
        """get_open_orders é signed → _require_private_access bloqueia sem creds."""
        with patch("httpx.Client"):
            client = BybitClient(environment="demo")  # sem credentials
            with pytest.raises(BybitExecutionBlockedError):
                client.get_open_orders("BTCUSDT")

    def test_blocks_in_mainnet_even_with_credentials(self):
        with patch("httpx.Client"):
            client = BybitClient(
                use_testnet=False,
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            with pytest.raises(BybitExecutionBlockedError):
                client.get_open_orders("BTCUSDT")


# ---------------------------------------------------------------------------
# get_order_history — SIGNED (read-only fallback de reconciliação)
# ---------------------------------------------------------------------------

class TestGetOrderHistory:

    def _patch_signed_request(self, monkeypatch, response: dict, captured: list):
        """Patcha _signed_request capturando os params da chamada."""
        import crypto_trading_bot.exchange.bybit_client as bc_mod

        def fake_signed_request(self, method, endpoint, query_params=None, body_payload=None, timestamp_ms=None):
            captured.append({
                "method": method, "endpoint": endpoint,
                "query_params": dict(query_params or {}),
            })
            return response.get("result", {})

        monkeypatch.setattr(bc_mod.BybitClient, "_signed_request", fake_signed_request)

    def test_returns_empty_list_when_no_history(self, monkeypatch):
        with patch("httpx.Client"):
            captured: list = []
            self._patch_signed_request(monkeypatch, {"result": {"list": []}}, captured)
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            history = client.get_order_history("BTCUSDT")
            assert history == []

    def test_returns_list_with_filled_order(self, monkeypatch):
        with patch("httpx.Client"):
            captured: list = []
            self._patch_signed_request(monkeypatch, {"result": {"list": [
                {"orderId": "X1", "symbol": "BTCUSDT",
                 "side": "Buy", "orderStatus": "Filled"},
            ]}}, captured)
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            history = client.get_order_history("BTCUSDT")
            assert len(history) == 1
            assert history[0]["orderStatus"] == "Filled"

    def test_filters_by_order_id_when_provided(self, monkeypatch):
        """order_id é passado no query string para filtrar resultado."""
        with patch("httpx.Client"):
            captured: list = []
            self._patch_signed_request(monkeypatch, {"result": {"list": []}}, captured)
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            client.get_order_history("BTCUSDT", order_id="MY_ORDER_ID")
            assert len(captured) == 1
            assert captured[0]["query_params"].get("orderId") == "MY_ORDER_ID"

    def test_endpoint_is_v5_order_history(self, monkeypatch):
        with patch("httpx.Client"):
            captured: list = []
            self._patch_signed_request(monkeypatch, {"result": {"list": []}}, captured)
            client = BybitClient(
                environment="demo", api_key="FAKE_K", api_secret="FAKE_S"
            )
            client.get_order_history("BTCUSDT")
            assert captured[0]["endpoint"] == "/v5/order/history"

    def test_blocks_in_mainnet(self):
        with patch("httpx.Client"):
            client = BybitClient(
                use_testnet=False,
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            with pytest.raises(BybitExecutionBlockedError):
                client.get_order_history("BTCUSDT")
