"""
Testes do modelo ExitDecision (FASE 11)
========================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordem.

Cobertura:
    - ExitReason, ExitSource, PositionSide: valores estáveis.
    - OpenPositionState: aceita BUY e SELL; valida invariantes SL/TP.
    - ExitDecision: imutável, metadata MappingProxyType, coerência
      should_close ↔ reason/source.
    - make_hold_decision: produz decisão neutra coerente.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.exit_policy import (
    ExitDecision,
    ExitReason,
    ExitSource,
    OpenPositionState,
    PositionSide,
    make_hold_decision,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Enums estáveis
# ---------------------------------------------------------------------------

class TestEnums:

    def test_exit_reason_values_stable(self):
        assert ExitReason.EMERGENCY.value == "emergency"
        assert ExitReason.MANUAL.value == "manual"
        assert ExitReason.STOP_LOSS.value == "stop_loss"
        assert ExitReason.TAKE_PROFIT.value == "take_profit"
        assert ExitReason.OPPOSITE_SIGNAL.value == "opposite_signal"
        assert ExitReason.TIME_LIMIT.value == "time_limit"
        assert ExitReason.END_OF_DATA.value == "end_of_data"
        assert ExitReason.NONE.value == "none"

    def test_exit_source_values_stable(self):
        assert ExitSource.RULE_EMERGENCY.value == "rule_emergency"
        assert ExitSource.RULE_MANUAL.value == "rule_manual"
        assert ExitSource.RULE_SL_TP.value == "rule_sl_tp"
        assert ExitSource.RULE_OPPOSITE.value == "rule_opposite"
        assert ExitSource.RULE_TIME.value == "rule_time"
        assert ExitSource.SYSTEM_EOD.value == "system_eod"
        assert ExitSource.NONE.value == "none"

    def test_position_side_values_stable(self):
        assert PositionSide.BUY.value == "buy"
        assert PositionSide.SELL.value == "sell"


# ---------------------------------------------------------------------------
# OpenPositionState
# ---------------------------------------------------------------------------

class TestOpenPositionState:

    def test_buy_position_valid(self):
        pos = OpenPositionState(
            symbol="BTCUSDT",
            side=PositionSide.BUY,
            entry_price=65000.0,
            entry_time=_NOW,
            stop_loss_price=64000.0,
            take_profit_price=67000.0,
            position_size_usd=200.0,
            entry_candle_idx=10,
        )
        assert pos.side == PositionSide.BUY
        assert pos.take_profit_price == 67000.0

    def test_sell_position_valid(self):
        pos = OpenPositionState(
            symbol="BTCUSDT",
            side=PositionSide.SELL,
            entry_price=65000.0,
            entry_time=_NOW,
            stop_loss_price=66000.0,
            take_profit_price=63000.0,
            position_size_usd=200.0,
        )
        assert pos.side == PositionSide.SELL

    def test_buy_rejects_stop_above_entry(self):
        with pytest.raises(ValueError, match="stop_loss"):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.BUY,
                entry_price=65000.0, entry_time=_NOW,
                stop_loss_price=66000.0,  # >= entry
                position_size_usd=200.0,
            )

    def test_sell_rejects_stop_below_entry(self):
        with pytest.raises(ValueError, match="stop_loss"):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.SELL,
                entry_price=65000.0, entry_time=_NOW,
                stop_loss_price=64000.0,  # <= entry
                position_size_usd=200.0,
            )

    def test_buy_rejects_tp_below_entry(self):
        with pytest.raises(ValueError, match="take_profit"):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.BUY,
                entry_price=65000.0, entry_time=_NOW,
                stop_loss_price=64000.0,
                take_profit_price=64500.0,  # <= entry
                position_size_usd=200.0,
            )

    def test_negative_prices_rejected(self):
        with pytest.raises(ValueError):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.BUY,
                entry_price=-1.0, entry_time=_NOW,
                stop_loss_price=1.0, position_size_usd=100.0,
            )
        with pytest.raises(ValueError):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.BUY,
                entry_price=10.0, entry_time=_NOW,
                stop_loss_price=-1.0, position_size_usd=100.0,
            )
        with pytest.raises(ValueError):
            OpenPositionState(
                symbol="BTCUSDT", side=PositionSide.BUY,
                entry_price=10.0, entry_time=_NOW,
                stop_loss_price=5.0, position_size_usd=0.0,
            )

    def test_tp_optional_for_retrocompat(self):
        pos = OpenPositionState(
            symbol="BTCUSDT", side=PositionSide.BUY,
            entry_price=65000.0, entry_time=_NOW,
            stop_loss_price=64000.0, position_size_usd=200.0,
            # take_profit_price omitido
        )
        assert pos.take_profit_price is None

    def test_frozen_immutable(self):
        pos = OpenPositionState(
            symbol="BTCUSDT", side=PositionSide.BUY,
            entry_price=65000.0, entry_time=_NOW,
            stop_loss_price=64000.0, position_size_usd=200.0,
        )
        with pytest.raises(Exception):
            pos.entry_price = 100.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExitDecision
# ---------------------------------------------------------------------------

class TestExitDecision:

    def test_decision_close_requires_real_reason(self):
        with pytest.raises(ValueError, match="reason"):
            ExitDecision(
                should_close=True,
                reason=ExitReason.NONE,  # inválido
                source=ExitSource.RULE_SL_TP,
                triggered_at_time=_NOW,
                requires_reduce_only=True,
                auto_execute_blocked=True,
            )

    def test_decision_close_requires_real_source(self):
        with pytest.raises(ValueError, match="source"):
            ExitDecision(
                should_close=True,
                reason=ExitReason.STOP_LOSS,
                source=ExitSource.NONE,  # inválido
                triggered_at_time=_NOW,
                requires_reduce_only=True,
                auto_execute_blocked=True,
            )

    def test_decision_no_close_requires_none(self):
        with pytest.raises(ValueError):
            ExitDecision(
                should_close=False,
                reason=ExitReason.STOP_LOSS,  # inválido
                source=ExitSource.NONE,
                triggered_at_time=_NOW,
                requires_reduce_only=False,
                auto_execute_blocked=False,
            )

    def test_metadata_becomes_mapping_proxy(self):
        d = ExitDecision(
            should_close=True,
            reason=ExitReason.STOP_LOSS,
            source=ExitSource.RULE_SL_TP,
            triggered_at_time=_NOW,
            requires_reduce_only=True,
            auto_execute_blocked=True,
            metadata={"foo": "bar"},
        )
        assert isinstance(d.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            d.metadata["foo"] = "baz"  # type: ignore[index]

    def test_naive_timestamp_promoted_to_utc(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        d = ExitDecision(
            should_close=True,
            reason=ExitReason.MANUAL,
            source=ExitSource.RULE_MANUAL,
            triggered_at_time=naive,
            requires_reduce_only=True,
            auto_execute_blocked=True,
        )
        assert d.triggered_at_time.tzinfo is not None
        assert d.triggered_at_time.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# make_hold_decision
# ---------------------------------------------------------------------------

class TestMakeHoldDecision:

    def test_hold_decision_coherent(self):
        d = make_hold_decision(_NOW)
        assert d.should_close is False
        assert d.reason == ExitReason.NONE
        assert d.source == ExitSource.NONE
        assert d.requires_reduce_only is False
        assert d.auto_execute_blocked is False
        assert d.triggered_at_idx is None

    def test_hold_decision_metadata_empty(self):
        d = make_hold_decision(_NOW)
        assert dict(d.metadata) == {}
