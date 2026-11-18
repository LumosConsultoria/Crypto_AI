"""
BybitClient.get_executions — read-only fallback (FASE 15)
===========================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordens.

Cobertura:
    - Endpoint correto: /v5/execution/list com category=linear.
    - Parse de result.list (lista de fills).
    - Filtro por order_id opcional (kwarg).
    - Bloqueado sem credentials.
    - Bloqueado em mainnet.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from crypto_trading_bot.exchange.bybit_client import (
    BybitClient,
    BybitExecutionBlockedError,
)


class TestGetExecutionsReadOnly:

    def _patch(self, monkeypatch, response: dict, captured: list):
        import crypto_trading_bot.exchange.bybit_client as bc_mod

        def fake_signed_request(self, method, endpoint, query_params=None,
                                body_payload=None, timestamp_ms=None):
            captured.append({
                "method": method,
                "endpoint": endpoint,
                "query_params": dict(query_params or {}),
            })
            return response.get("result", {})

        monkeypatch.setattr(bc_mod.BybitClient, "_signed_request", fake_signed_request)

    def test_endpoint_is_v5_execution_list_with_linear(self, monkeypatch):
        captured: list = []
        self._patch(monkeypatch, {"result": {"list": []}}, captured)
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.get_executions("BTCUSDT")
        assert captured[0]["method"] == "GET"
        assert captured[0]["endpoint"] == "/v5/execution/list"
        assert captured[0]["query_params"]["category"] == "linear"
        assert captured[0]["query_params"]["symbol"] == "BTCUSDT"

    def test_parses_execution_list(self, monkeypatch):
        captured: list = []
        execs = [
            {"orderId": "X1", "execId": "E1", "symbol": "BTCUSDT",
             "side": "Buy", "execPrice": "71583.6", "execQty": "0.001"},
            {"orderId": "X1", "execId": "E2", "symbol": "BTCUSDT",
             "side": "Buy", "execPrice": "71583.7", "execQty": "0.001"},
        ]
        self._patch(monkeypatch, {"result": {"list": execs}}, captured)
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            result = client.get_executions("BTCUSDT")
        assert len(result) == 2
        assert result[0]["orderId"] == "X1"
        assert result[0]["execQty"] == "0.001"

    def test_filters_by_order_id_when_provided(self, monkeypatch):
        captured: list = []
        self._patch(monkeypatch, {"result": {"list": []}}, captured)
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.get_executions("BTCUSDT", order_id="MY_ORDER_ID")
        assert captured[0]["query_params"].get("orderId") == "MY_ORDER_ID"

    def test_returns_empty_list_when_no_executions(self, monkeypatch):
        captured: list = []
        self._patch(monkeypatch, {"result": {"list": []}}, captured)
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            result = client.get_executions("BTCUSDT")
        assert result == []

    def test_blocked_without_credentials(self):
        with patch("httpx.Client"):
            client = BybitClient(environment="demo")  # sem creds
            with pytest.raises(BybitExecutionBlockedError):
                client.get_executions("BTCUSDT")

    def test_blocked_in_mainnet(self):
        with patch("httpx.Client"):
            client = BybitClient(
                use_testnet=False,
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            with pytest.raises(BybitExecutionBlockedError):
                client.get_executions("BTCUSDT")

    def test_respects_custom_category(self, monkeypatch):
        captured: list = []
        self._patch(monkeypatch, {"result": {"list": []}}, captured)
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.get_executions("BTCUSDT", category="linear")
        assert captured[0]["query_params"]["category"] == "linear"
