"""
FASE 63 — overlay operacional NAO-preditivo + encerramento. 100% OFFLINE.
Verifica: rede bloqueada sem flag; NENHUM endpoint de ordem chamado; fallback
manual; alertas high/critical viram blockers; demo/live bloqueados; OOS
intocado; politica de reabertura (busca preditiva ENCERRADA). Sem rede/ordem.
"""

from __future__ import annotations

from crypto_trading_bot.risk_overlay import AccountState, Position, RiskLimits
from crypto_trading_bot.risk_overlay.operational import (
    build_operational_overlay)
from crypto_trading_bot.risk_overlay.sources import (
    bybit_readonly_source, manual_source)

_LIM = RiskLimits()


class _FakeAdapter:
    """Read-only fake: account_readonly() OK; metodos de ORDEM registram se
    forem chamados (NUNCA devem ser)."""

    def __init__(self):
        self.account_called = False
        self.order_called = False

    def account_readonly(self):
        self.account_called = True
        return {"wallet": {"equity": 5000, "balance": 5000},
                "positions": [{"symbol": "BTCUSDT", "side": "Buy", "size": 0.1,
                               "avgPrice": 60000, "markPrice": 59500}],
                "open_orders": []}

    def place_order(self, *a, **k):
        self.order_called = True
        raise AssertionError("ordem chamada — PROIBIDO")

    def cancel_order(self, *a, **k):
        self.order_called = True
        raise AssertionError("cancel chamado — PROIBIDO")


def test_network_blocked_without_flag():
    fake = _FakeAdapter()
    src = bybit_readonly_source(allow_network=False, adapter=fake)
    assert src["status"] == "gated_no_network"
    assert fake.account_called is False        # nao tocou a rede/adapter
    assert src["account"] is None and src["positions"] == []


def test_no_order_endpoint_called():
    fake = _FakeAdapter()
    src = bybit_readonly_source(allow_network=True, adapter=fake)
    assert src["status"] == "connected"
    assert fake.account_called is True
    assert fake.order_called is False          # NENHUM endpoint de ordem
    assert src["positions"] and src["positions"][0].symbol == "BTCUSDT"


def test_manual_fallback_works():
    data = {"account": {"equity_usd": 5000, "balance_usd": 5000},
            "positions": [{"symbol": "BTCUSDT", "side": "long",
                           "notional_usd": 1000, "entry_price": 60000,
                           "mark_price": 60000, "stop_loss_price": 59400}]}
    src = manual_source(data)
    rep = build_operational_overlay(src["account"], src["positions"], _LIM,
                                    source_info=src)
    assert rep["source"] == "manual"
    assert rep["exposure_summary"]["open_positions"] == 1
    assert rep["real_execution_allowed"] is False


def test_high_critical_alerts_become_blockers():
    # posicao SEM stop (high) + exposicao > cap (high) + daily loss estourado
    acc = AccountState(equity_usd=4700, balance_usd=5000,
                       realized_pnl_today_usd=-260)
    pos = [Position("BTCUSDT", "long", notional_usd=6000, entry_price=60000,
                    mark_price=59000, stop_loss_price=None)]
    rep = build_operational_overlay(acc, pos, _LIM,
                                    source_info={"status": "manual"})
    assert rep["blockers"], "high/critical devem virar blockers"
    sev = {b["severity"] for b in rep["blockers"]}
    assert sev <= {"high", "critical"}
    assert rep["readiness"]["status"] in ("action_required", "blocked_critical")
    assert rep["readiness"]["authorizes_execution"] is False


def test_safety_flags_and_oos_untouched():
    rep = build_operational_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [], _LIM,
        source_info={"status": "manual"})
    assert rep["real_execution_allowed"] is False
    assert rep["orders_emitted"] == 0
    assert rep["demo_blocked"] and rep["live_blocked"]
    assert rep["oos_untouched"] is True
    assert rep["predictive_search_closed"] is True
    assert rep["overall_status"] == "flat_ok"


class TestReopenPolicy:

    def test_directional_ohlcv_only_blocked(self):
        from crypto_trading_bot.research.rejected_hypotheses_registry import (
            check_reopen)
        r = check_reopen("nova_ideia_btc", family="alguma_nova",
                         data_used=["ohlcv", "funding"])
        assert r["allowed"] is False and "ENCERRADA" in r["reason"]

    def test_new_data_source_reopens(self):
        from crypto_trading_bot.research.rejected_hypotheses_registry import (
            check_reopen)
        r = check_reopen("ideia_orderbook", family="microstructure",
                         data_used=["ohlcv", "orderbook"])
        assert r["allowed"] is True and "NOVA" in r["reason"]

    def test_strong_justification_reopens_with_warning(self):
        from crypto_trading_bot.research.rejected_hypotheses_registry import (
            check_reopen)
        just = ("diferenca estrutural profunda e detalhada com mais de oitenta "
                "caracteres explicando por que e genuinamente nova e distinta")
        r = check_reopen("ideia_x", family="outra_nova", data_used=["ohlcv"],
                         structural_difference=just)
        assert r["allowed"] is True and "CETICISMO" in r["reason"]
