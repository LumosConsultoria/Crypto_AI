"""
--post-session-check — Read-only Operational Check (FASE 15)
============================================================
⚠️  100% offline. ZERO secrets. ZERO rede real. ZERO ordens.

Cobertura:
    - Sub-modo chama apenas métodos read-only do BybitClient.
    - Reporta posição residual quando há size > 0.
    - Reporta open orders residuais.
    - Compara baseline balance opcional.
    - Output não contém secrets.
    - NÃO chama place_market_order, cancel_order, close_position.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.test_run_bybit_demo_diagnostic import (
    _FAKE_KEY_MARKER,
    _FAKE_SECRET_MARKER,
    _load_script_module,
    _setup_demo_env,
    _setup_paper_env,
)


def _patch_bybit_for_post_session(
    monkeypatch,
    *,
    positions: list | None = None,
    open_orders: list | None = None,
    balance: dict | None = None,
    positions_raise: Exception | None = None,
    open_orders_raise: Exception | None = None,
    balance_raise: Exception | None = None,
) -> MagicMock:
    """Patcha BybitClient inteiro para evitar qualquer rede real."""
    instance = MagicMock(name="BybitClient_demo_mock")
    instance.environment = "demo"
    instance._base_url = "https://api-demo.bybit.com"
    instance.is_demo = True

    if positions_raise is not None:
        instance.get_positions.side_effect = positions_raise
    else:
        instance.get_positions.return_value = positions or []

    if open_orders_raise is not None:
        instance.get_open_orders.side_effect = open_orders_raise
    else:
        instance.get_open_orders.return_value = open_orders or []

    if balance_raise is not None:
        instance.get_balance.side_effect = balance_raise
    else:
        instance.get_balance.return_value = balance or {
            "list": [{
                "coin": [{
                    "coin": "USDT",
                    "walletBalance": "4999.92",
                }],
            }],
        }

    import crypto_trading_bot.exchange.bybit_client as bc_mod
    monkeypatch.setattr(bc_mod, "BybitClient", MagicMock(return_value=instance))
    return instance


# ---------------------------------------------------------------------------
# Read-only only
# ---------------------------------------------------------------------------

class TestPostSessionReadOnly:

    def test_calls_only_readonly_methods(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_for_post_session(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--post-session-check"])
        # Sem posições/orders residuais → rc=0
        assert rc == 0
        client.get_positions.assert_called_once()
        client.get_open_orders.assert_called_once()
        client.get_balance.assert_called_once()
        # Nada de escrita
        client.place_market_order.assert_not_called()
        client.cancel_order.assert_not_called()
        # Nenhum método cancel_position/close_position deve ter sido chamado.
        for attr in ("close_position", "cancel_all_orders"):
            method = getattr(client, attr, None)
            if method is not None and hasattr(method, "assert_not_called"):
                method.assert_not_called()


class TestPostSessionResidualPosition:

    def test_reports_residual_position(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(
            monkeypatch,
            positions=[
                {"symbol": "BTCUSDT", "side": "buy", "size": "0.001"},
            ],
        )
        mod = _load_script_module()
        rc = mod.main(["--post-session-check"])
        out = capsys.readouterr().out
        assert "POSIÇÃO RESIDUAL" in out
        # Resíduo → rc=1 (exige ação manual)
        assert rc == 1


class TestPostSessionResidualOrders:

    def test_reports_residual_open_orders(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(
            monkeypatch,
            open_orders=[
                {"orderId": "X1", "symbol": "BTCUSDT", "side": "Buy"},
            ],
        )
        mod = _load_script_module()
        rc = mod.main(["--post-session-check"])
        out = capsys.readouterr().out
        assert "ORDENS ABERTAS" in out
        assert rc == 1


class TestPostSessionBaselineDelta:

    def test_reports_delta_against_baseline(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(monkeypatch)
        mod = _load_script_module()
        rc = mod.main([
            "--post-session-check",
            "--baseline-balance", "5000.0",
        ])
        out = capsys.readouterr().out
        assert "baseline_balance" in out
        assert "delta vs baseline" in out
        # 4999.92 - 5000.0 = -0.08
        assert "-0.08" in out
        assert rc == 0

    def test_no_baseline_means_no_delta_line(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(monkeypatch)
        mod = _load_script_module()
        mod.main(["--post-session-check"])
        out = capsys.readouterr().out
        assert "delta vs baseline" not in out


class TestPostSessionNoSecretsInOutput:

    def test_no_api_key_or_secret_in_output(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(monkeypatch)
        mod = _load_script_module()
        mod.main(["--post-session-check"])
        out = capsys.readouterr().out
        # Os env vars usam marker explícito; se aparecer, é vazamento.
        assert _FAKE_KEY_MARKER not in out
        assert _FAKE_SECRET_MARKER not in out
        # Tokens comuns de auth/secret
        for tok in ("X-BAPI-SIGN", "Bearer ", "Authorization:"):
            assert tok not in out


class TestPostSessionGates:

    def test_blocked_in_paper_mode(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        client = _patch_bybit_for_post_session(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--post-session-check"])
        assert rc == 1
        # Nenhuma chamada deveria ter sido feita
        client.get_positions.assert_not_called()


class TestPostSessionApiErrorSurfacing:

    def test_bybit_api_error_in_positions_surfaces_retcode(
        self, monkeypatch, capsys
    ):
        from crypto_trading_bot.exchange.bybit_client import BybitAPIError
        _setup_demo_env(monkeypatch)
        _patch_bybit_for_post_session(
            monkeypatch,
            positions_raise=BybitAPIError(
                ret_code=10003, ret_msg="API key is invalid",
                endpoint="/v5/position/list",
            ),
        )
        mod = _load_script_module()
        rc = mod.main(["--post-session-check"])
        out = capsys.readouterr().out
        assert "BybitAPIError" in out
        assert "10003" in out
        assert "API key is invalid" in out
        # Erro grave → rc=1
        assert rc == 1
