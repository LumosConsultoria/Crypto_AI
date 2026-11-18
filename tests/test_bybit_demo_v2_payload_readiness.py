"""
Bybit Demo v2 — Payload Readiness (FASE 13)
=============================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Cobertura:
    - BybitClient.place_market_order monta body com stopLoss + takeProfit.
    - BybitDemoExecutor repassa signal.take_profit_price ao BybitClient.
    - Script de diagnostic --prepare-demo-v2-order não chama rede.
    - Script aborta com SL/TP inválido.
    - Nenhum teste chama internet.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError, BybitClient,
)


_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "scripts" / "run_bybit_demo_diagnostic.py"


# ---------------------------------------------------------------------------
# BybitClient.place_market_order monta body com stopLoss + takeProfit
# ---------------------------------------------------------------------------

class TestBybitClientPayload:

    def _setup(self):
        """Patcha _signed_request capturando o body, sem rede."""
        captured: list[dict] = []

        def fake_signed_request(self, method, endpoint, query_params=None,
                                body_payload=None, timestamp_ms=None):
            captured.append({
                "method": method, "endpoint": endpoint,
                "body": dict(body_payload or {}),
            })
            return {
                "orderId": "FAKE123",
                "orderLinkId": "LINK123",
            }

        return captured, fake_signed_request

    def test_payload_includes_stop_loss_and_take_profit(self, monkeypatch):
        captured, fake_signed = self._setup()
        with patch("httpx.Client"):
            monkeypatch.setattr(
                BybitClient, "_signed_request", fake_signed,
            )
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=64000.0, take_profit=67000.0,
            )

        assert len(captured) == 1
        body = captured[0]["body"]
        assert body["symbol"] == "BTCUSDT"
        assert body["side"] == "Buy"
        assert body["orderType"] == "Market"
        assert body["stopLoss"] == "64000.0"
        assert body["takeProfit"] == "67000.0"

    def test_payload_works_for_sell(self, monkeypatch):
        captured, fake_signed = self._setup()
        with patch("httpx.Client"):
            monkeypatch.setattr(
                BybitClient, "_signed_request", fake_signed,
            )
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.place_market_order(
                symbol="BTCUSDT", side="sell", qty=0.001,
                stop_loss=66000.0, take_profit=63000.0,
            )

        body = captured[0]["body"]
        assert body["side"] == "Sell"
        assert body["stopLoss"] == "66000.0"
        assert body["takeProfit"] == "63000.0"

    def test_payload_omits_tp_when_none(self, monkeypatch):
        captured, fake_signed = self._setup()
        with patch("httpx.Client"):
            monkeypatch.setattr(
                BybitClient, "_signed_request", fake_signed,
            )
            client = BybitClient(
                environment="demo",
                api_key="FAKE_K", api_secret="FAKE_S",
            )
            client.place_market_order(
                symbol="BTCUSDT", side="buy", qty=0.001,
                stop_loss=64000.0, take_profit=None,
            )
        body = captured[0]["body"]
        assert "stopLoss" in body
        assert "takeProfit" not in body


# ---------------------------------------------------------------------------
# BybitDemoExecutor repassa take_profit do signal
# ---------------------------------------------------------------------------

class TestDemoExecutorPassesTakeProfit:

    def test_executor_passes_take_profit_to_client(self):
        """
        Audita por inspeção de fonte: BybitDemoExecutor.place_demo_order
        deve passar take_profit=signal.take_profit_price ao
        BybitClient.place_market_order.
        """
        import crypto_trading_bot.execution.bybit_demo_executor as mod
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "take_profit=signal.take_profit_price" in src, (
            "BybitDemoExecutor deve repassar take_profit do signal "
            "ao BybitClient.place_market_order"
        )


# ---------------------------------------------------------------------------
# Script --prepare-demo-v2-order: OFFLINE + zero ordem
# ---------------------------------------------------------------------------

class TestDiagnosticPrepareV2:

    def _run_script(self, *args: str) -> tuple[int, str]:
        """Executa o script em subprocess capturando stdout."""
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        return result.returncode, result.stdout + result.stderr

    def test_prepare_v2_offline_succeeds_with_valid_buy(self):
        code, out = self._run_script(
            "--prepare-demo-v2-order",
            "--symbol", "BTCUSDT",
            "--side", "buy",
            "--entry-price", "65000",
            "--stop-loss", "64000",
            "--take-profit", "67000",
            "--position-size", "200",
        )
        assert code == 0, out
        assert "DEMO v2 READINESS" in out
        assert "OFFLINE" in out
        # Payload V5 preview deve aparecer
        assert "stopLoss" in out
        assert "takeProfit" in out

    def test_prepare_v2_aborts_buy_with_invalid_sl(self):
        code, out = self._run_script(
            "--prepare-demo-v2-order",
            "--symbol", "BTCUSDT",
            "--side", "buy",
            "--entry-price", "65000",
            "--stop-loss", "66000",  # > entry → inválido para BUY
            "--take-profit", "67000",
            "--position-size", "200",
        )
        assert code == 1
        assert "READINESS ABORT" in out

    def test_prepare_v2_aborts_sell_with_invalid_tp(self):
        code, out = self._run_script(
            "--prepare-demo-v2-order",
            "--symbol", "BTCUSDT",
            "--side", "sell",
            "--entry-price", "65000",
            "--stop-loss", "66000",
            "--take-profit", "68000",  # > entry → inválido para SELL
            "--position-size", "200",
        )
        assert code == 1
        assert "READINESS ABORT" in out

    def test_prepare_v2_does_not_send_order(self):
        """Texto explícito de que execução real fica para FASE 14."""
        code, out = self._run_script(
            "--prepare-demo-v2-order",
            "--entry-price", "65000",
            "--stop-loss", "64000",
            "--take-profit", "67000",
            "--position-size", "200",
        )
        assert code == 0
        assert "FASE 14" in out
        assert "aprovação humana" in out
        assert "Nenhuma ordem enviada" in out

    def test_prepare_v2_does_not_log_secrets(self):
        code, out = self._run_script(
            "--prepare-demo-v2-order",
            "--entry-price", "65000",
            "--stop-loss", "64000",
            "--take-profit", "67000",
            "--position-size", "200",
        )
        # Tokens sensíveis não podem aparecer
        lower = out.lower()
        for tok in ("api_key=", "api_secret=", "x-bapi-sign", "bearer "):
            assert tok not in lower, f"Output contém token sensível: {tok}"
