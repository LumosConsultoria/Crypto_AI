"""
Testes de SessionRunResult + SessionBlockEvent + SessionStopReason (FASE 17)
=============================================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Frozen.
    - to_dict JSON-serializável.
    - blocks tuple imutável.
    - total_blocks == soma por origem.
    - SessionStopReason valores estáveis.
    - SessionBlockEvent metadata protegido.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.session_runner.result import (
    BLOCK_PROFILE_CONCURRENT,
    BLOCK_PROFILE_HOURS,
    BLOCK_PROFILE_TIME_LIMIT,
    BLOCK_RISK_ENGINE,
    BLOCK_SAFETY_STATE,
    SessionBlockEvent,
    SessionRunResult,
    SessionStopReason,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# SessionStopReason
# ---------------------------------------------------------------------------

class TestSessionStopReasonStability:

    def test_values_stable(self):
        assert SessionStopReason.MAX_CYCLES.value == "max_cycles"
        assert SessionStopReason.MANUAL_STOP.value == "manual_stop"
        assert SessionStopReason.TIME_LIMIT.value == "time_limit"
        assert SessionStopReason.PROFILE_TRADES_LIMIT.value == "profile_trades_limit"
        assert SessionStopReason.PROFILE_CONSECUTIVE_LOSSES.value == "profile_consecutive_losses"
        assert SessionStopReason.PROFILE_SYMBOL_NOT_ALLOWED.value == "profile_symbol_not_allowed"
        assert SessionStopReason.KILL_SWITCH.value == "kill_switch"
        assert SessionStopReason.SAFETY_HALT_ACTIVE.value == "safety_halt_active"
        assert SessionStopReason.ERROR.value == "error"


# ---------------------------------------------------------------------------
# SessionBlockEvent
# ---------------------------------------------------------------------------

class TestSessionBlockEvent:

    def _make(self, **kw):
        defaults = dict(
            cycle_index=0,
            block_source=BLOCK_SAFETY_STATE,
            reason="t",
            triggered_at=_NOW,
        )
        defaults.update(kw)
        return SessionBlockEvent(**defaults)

    def test_frozen(self):
        e = self._make()
        with pytest.raises(Exception):
            e.cycle_index = 1  # type: ignore[misc]

    def test_metadata_becomes_mappingproxy(self):
        e = self._make(metadata={"k": "v"})
        assert isinstance(e.metadata, MappingProxyType)
        with pytest.raises(TypeError):
            e.metadata["k"] = "x"  # type: ignore[index]

    def test_invalid_block_source_rejected(self):
        with pytest.raises(ValueError, match="block_source"):
            self._make(block_source="invalid_source")

    def test_naive_timestamp_promoted_to_utc(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        e = self._make(triggered_at=naive)
        assert e.triggered_at.tzinfo == timezone.utc

    def test_to_dict_json_serializable(self):
        e = self._make(metadata={"a": 1, "b": [1, 2]})
        d = e.to_dict()
        json.dumps(d)


# ---------------------------------------------------------------------------
# SessionRunResult
# ---------------------------------------------------------------------------

class TestSessionRunResult:

    def _make_blocks(self):
        return (
            SessionBlockEvent(
                cycle_index=0, block_source=BLOCK_SAFETY_STATE,
                reason="x", triggered_at=_NOW,
            ),
            SessionBlockEvent(
                cycle_index=1, block_source=BLOCK_PROFILE_HOURS,
                reason="y", triggered_at=_NOW,
            ),
            SessionBlockEvent(
                cycle_index=2, block_source=BLOCK_PROFILE_TIME_LIMIT,
                reason="z", triggered_at=_NOW,
            ),
            SessionBlockEvent(
                cycle_index=3, block_source=BLOCK_RISK_ENGINE,
                reason="w", triggered_at=_NOW,
            ),
        )

    def test_from_blocks_aggregates_correctly(self):
        blocks = self._make_blocks()
        r = SessionRunResult.from_blocks(
            total_cycles_requested=10,
            total_cycles_completed=4,
            trades_opened=2,
            trades_closed=1,
            pnl_paper=-1.5,
            drawdown_paper=-2.0,
            consecutive_losses_final=1,
            blocks=blocks,
            final_safety_state="normal",
            stopped_reason=SessionStopReason.MAX_CYCLES,
            started_at=_NOW, ended_at=_NOW,
        )
        assert r.total_blocks == 4
        assert r.blocks_by_safety == 1
        assert r.blocks_by_profile == 2
        assert r.blocks_by_risk == 1
        assert (r.blocks_by_safety + r.blocks_by_profile + r.blocks_by_risk
                == r.total_blocks)

    def test_blocks_are_tuple_immutable(self):
        blocks = self._make_blocks()
        r = SessionRunResult.from_blocks(
            total_cycles_requested=10,
            total_cycles_completed=4,
            trades_opened=0, trades_closed=0,
            pnl_paper=0.0, drawdown_paper=0.0,
            consecutive_losses_final=0,
            blocks=blocks,
            final_safety_state="normal",
            stopped_reason=SessionStopReason.MAX_CYCLES,
            started_at=_NOW, ended_at=_NOW,
        )
        assert isinstance(r.blocks, tuple)
        with pytest.raises(Exception):
            r.blocks.append(  # type: ignore[attr-defined]
                self._make_blocks()[0]
            )

    def test_frozen(self):
        r = SessionRunResult.from_blocks(
            total_cycles_requested=10,
            total_cycles_completed=10,
            trades_opened=0, trades_closed=0,
            pnl_paper=0.0, drawdown_paper=0.0,
            consecutive_losses_final=0,
            blocks=(),
            final_safety_state="normal",
            stopped_reason=SessionStopReason.MAX_CYCLES,
            started_at=_NOW, ended_at=_NOW,
        )
        with pytest.raises(Exception):
            r.total_cycles_completed = 5  # type: ignore[misc]

    def test_to_dict_json_serializable(self):
        blocks = self._make_blocks()
        r = SessionRunResult.from_blocks(
            total_cycles_requested=10,
            total_cycles_completed=4,
            trades_opened=2, trades_closed=1,
            pnl_paper=-1.5, drawdown_paper=-2.0,
            consecutive_losses_final=1,
            blocks=blocks,
            final_safety_state="normal",
            stopped_reason=SessionStopReason.MAX_CYCLES,
            started_at=_NOW, ended_at=_NOW,
        )
        d = r.to_dict()
        json.dumps(d)
        assert d["stopped_reason"] == "max_cycles"
        assert d["total_blocks"] == 4

    def test_inconsistent_total_blocks_rejected(self):
        with pytest.raises(ValueError, match="total_blocks"):
            SessionRunResult(
                total_cycles_requested=10, total_cycles_completed=4,
                trades_opened=0, trades_closed=0,
                pnl_paper=0.0, drawdown_paper=0.0,
                consecutive_losses_final=0,
                blocks=self._make_blocks(),
                blocks_by_safety=1, blocks_by_profile=2, blocks_by_risk=1,
                total_blocks=99,  # divergente
                final_safety_state="normal",
                stopped_reason=SessionStopReason.MAX_CYCLES,
                started_at=_NOW, ended_at=_NOW,
            )

    def test_aggregated_inconsistency_rejected(self):
        with pytest.raises(ValueError, match="Inconsist"):
            SessionRunResult(
                total_cycles_requested=10, total_cycles_completed=4,
                trades_opened=0, trades_closed=0,
                pnl_paper=0.0, drawdown_paper=0.0,
                consecutive_losses_final=0,
                blocks=self._make_blocks(),
                blocks_by_safety=10,  # propositalmente errado
                blocks_by_profile=0, blocks_by_risk=0,
                total_blocks=4,
                final_safety_state="normal",
                stopped_reason=SessionStopReason.MAX_CYCLES,
                started_at=_NOW, ended_at=_NOW,
            )

    def test_empty_blocks_aggregates_zero(self):
        r = SessionRunResult.from_blocks(
            total_cycles_requested=10,
            total_cycles_completed=10,
            trades_opened=0, trades_closed=0,
            pnl_paper=0.0, drawdown_paper=0.0,
            consecutive_losses_final=0,
            blocks=(),
            final_safety_state="normal",
            stopped_reason=SessionStopReason.MAX_CYCLES,
            started_at=_NOW, ended_at=_NOW,
        )
        assert r.total_blocks == 0
        assert r.blocks_by_safety == 0
        assert r.blocks_by_profile == 0
        assert r.blocks_by_risk == 0
