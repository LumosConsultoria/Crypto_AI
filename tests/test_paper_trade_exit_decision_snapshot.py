"""
PaperTrade.exit_decision_snapshot — Retrocompat (FASE 13)
==========================================================
⚠️  100% offline.

Cobertura:
    - Default None.
    - close_trade(..., exit_decision_snapshot=None) preserva None.
    - close_trade(..., exit_decision_snapshot=dict) armazena cópia.
    - Snapshot é JSON-serializável.
    - Cópia defensiva: mutar dict original não afeta o armazenado.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import (
    PaperTrade,
    PaperTradeStatus,
    PaperTrader,
)
from crypto_trading_bot.risk.risk_engine import RiskEngine

from tests.test_paper_trader import (
    _make_approved_risk_result,
    _make_valid_signal,
)


def _trader_with_open() -> tuple[PaperTrader, str]:
    trader = PaperTrader(
        risk_engine=RiskEngine(initial_capital=5000.0),
        exchange=MockExchange(initial_balance_usdt=5000.0),
    )
    res = trader.execute(_make_approved_risk_result(_make_valid_signal()))
    return trader, res.trade.trade_id


class TestDefault:

    def test_default_is_none(self):
        trader, tid = _trader_with_open()
        assert trader.open_trades[tid].exit_decision_snapshot is None

    def test_close_without_snapshot_keeps_none(self):
        trader, tid = _trader_with_open()
        result = trader.close_trade(tid, close_price=66000.0, reason="manual")
        assert result.trade.exit_decision_snapshot is None


class TestSnapshotStored:

    def test_close_with_snapshot_stores_copy(self):
        trader, tid = _trader_with_open()
        snap = {
            "reason": "stop_loss",
            "source": "rule_sl_tp",
            "auto_execute_blocked": False,
            "capability_allows_auto_close": True,
        }
        result = trader.close_trade(
            tid, close_price=63700.0, reason="stop_loss",
            exit_decision_snapshot=snap,
        )
        stored = result.trade.exit_decision_snapshot
        assert stored == snap
        # Cópia defensiva: mutar o original não afeta o armazenado.
        snap["reason"] = "MUTATED"
        assert result.trade.exit_decision_snapshot["reason"] == "stop_loss"

    def test_snapshot_json_serializable(self):
        trader, tid = _trader_with_open()
        snap = {
            "reason": "time_limit",
            "source": "rule_time",
            "requires_reduce_only": True,
            "auto_execute_blocked": True,
            "elapsed_candles": None,
            "elapsed_seconds": 120.0,
            "capability_allows_auto_close": False,
            "provider_id": "paper",
        }
        result = trader.close_trade(
            tid, close_price=65500.0, reason="time_limit",
            exit_decision_snapshot=snap,
        )
        # Tenta serializar — não pode levantar
        json.dumps(snap)
        assert result.trade.status == PaperTradeStatus.CLOSED_TIME_LIMIT


class TestNewStatuses:

    def test_time_limit_status_available(self):
        assert PaperTradeStatus.CLOSED_TIME_LIMIT.value == "closed_time_limit"

    def test_opposite_signal_status_available(self):
        assert (
            PaperTradeStatus.CLOSED_OPPOSITE_SIGNAL.value
            == "closed_opposite_signal"
        )

    def test_emergency_status_available(self):
        assert PaperTradeStatus.CLOSED_EMERGENCY.value == "closed_emergency"

    def test_legacy_statuses_unchanged(self):
        assert PaperTradeStatus.OPEN.value == "open"
        assert PaperTradeStatus.CLOSED_STOP_LOSS.value == "closed_stop_loss"
        assert PaperTradeStatus.CLOSED_TAKE_PROFIT.value == "closed_take_profit"
        assert PaperTradeStatus.CLOSED_MANUAL.value == "closed_manual"
        assert PaperTradeStatus.FAILED.value == "failed"
