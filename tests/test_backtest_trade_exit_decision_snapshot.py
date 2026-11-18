"""
Snapshot opcional em BacktestTrade (FASE 12)
=============================================
⚠️  100% offline.

Cobertura:
    - Campo exit_decision_snapshot é None por default.
    - to_dict() omite a chave quando None (preserva schema legado).
    - to_dict() inclui a chave quando preenchido.
    - Snapshot é dict puro e JSON-serializável.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.backtesting.backtest_trade import (
    BacktestTrade,
    CloseReason,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _new_trade() -> BacktestTrade:
    return BacktestTrade(
        symbol="BTCUSDT", strategy_name="t",
        entry_candle_idx=10, entry_time=_NOW,
        entry_price=65000.0, stop_loss_price=64000.0,
        take_profit_price=67000.0, position_size_usd=200.0,
        side="buy",
    )


class TestSnapshotDefault:

    def test_default_is_none(self):
        t = _new_trade()
        assert t.exit_decision_snapshot is None

    def test_to_dict_omits_snapshot_when_none(self):
        t = _new_trade()
        d = t.to_dict()
        assert "exit_decision_snapshot" not in d

    def test_close_without_snapshot_keeps_none(self):
        t = _new_trade()
        t.close(
            exit_candle_idx=15,
            exit_time=_NOW,
            exit_price=64000.0,
            close_reason=CloseReason.STOP_LOSS,
        )
        assert t.exit_decision_snapshot is None


class TestSnapshotIncluded:

    def test_close_with_snapshot_stores_copy(self):
        t = _new_trade()
        snap = {
            "reason": "stop_loss",
            "source": "rule_sl_tp",
            "auto_execute_blocked": False,
            "capability_allows_auto_close": True,
        }
        t.close(
            exit_candle_idx=15,
            exit_time=_NOW,
            exit_price=64000.0,
            close_reason=CloseReason.STOP_LOSS,
            exit_decision_snapshot=snap,
        )
        assert t.exit_decision_snapshot == snap
        # Cópia defensiva — mutar o original não afeta o snapshot armazenado
        snap["reason"] = "MUTATED"
        assert t.exit_decision_snapshot["reason"] == "stop_loss"

    def test_to_dict_includes_snapshot_when_set(self):
        t = _new_trade()
        snap = {
            "reason": "take_profit", "source": "rule_sl_tp",
            "auto_execute_blocked": False,
        }
        t.close(
            exit_candle_idx=15,
            exit_time=_NOW,
            exit_price=67000.0,
            close_reason=CloseReason.TAKE_PROFIT,
            exit_decision_snapshot=snap,
        )
        d = t.to_dict()
        assert "exit_decision_snapshot" in d
        assert d["exit_decision_snapshot"]["reason"] == "take_profit"

    def test_snapshot_is_json_serializable(self):
        t = _new_trade()
        snap = {
            "reason": "time_limit",
            "source": "rule_time",
            "requires_reduce_only": True,
            "auto_execute_blocked": True,
            "elapsed_candles": 5,
            "elapsed_seconds": 75.0,
            "capability_allows_auto_close": False,
            "provider_id": "bybit_demo_linear",
            "trigger_price": 64000.0,
        }
        t.close(
            exit_candle_idx=15,
            exit_time=_NOW,
            exit_price=64000.0,
            close_reason=CloseReason.TIME_LIMIT,
            exit_decision_snapshot=snap,
        )
        # Deve serializar sem erro
        json.dumps(t.to_dict())


class TestNewCloseReasonsAvailable:

    def test_time_limit_value_stable(self):
        assert CloseReason.TIME_LIMIT.value == "time_limit"

    def test_opposite_signal_value_stable(self):
        assert CloseReason.OPPOSITE_SIGNAL.value == "opposite_signal"

    def test_existing_values_unchanged(self):
        assert CloseReason.STOP_LOSS.value == "stop_loss"
        assert CloseReason.TAKE_PROFIT.value == "take_profit"
        assert CloseReason.END_OF_DATA.value == "end_of_data"
        assert CloseReason.RISK_BLOCKED.value == "risk_blocked"
