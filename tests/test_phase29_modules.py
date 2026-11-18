"""
Tests - FASE 29 modules (flat, pnl, exit_resolver, monitor, close_wrapper)
==============================================================================
100% offline. ZERO network. ZERO ordem.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.demo_endurance import (
    CloseExecutionResult,
    CloseExecutorWrapper,
    DEFAULT_MAX_TIME_IN_POSITION_SECONDS,
    ExitDecisionResolver,
    FlatCheckResult,
    PnLResult,
    PnLTracker,
    PositionMonitor,
    PositionSnapshot,
    build_open_position_state_from_snapshot,
    build_phase29_exit_policy,
    validate_flat,
)


NOW = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)


# ===========================================================================
# FlatCheckValidator
# ===========================================================================

class TestFlatCheckValidator:

    def test_all_empty_is_flat(self):
        r = validate_flat(
            positions=[], open_orders=[], conditional_orders=[],
        )
        assert r.is_flat is True
        assert r.positions_count == 0
        assert r.blockers == ()

    def test_position_residual(self):
        r = validate_flat(
            positions=[{"size": "0.003"}], open_orders=[],
            conditional_orders=[],
        )
        assert r.is_flat is False
        assert r.positions_count == 1
        assert r.residual_qty == 0.003

    def test_open_orders_blocks(self):
        r = validate_flat(
            positions=[], open_orders=[{"id": "X"}],
            conditional_orders=[],
        )
        assert r.is_flat is False
        assert r.open_orders_count == 1

    def test_conditional_orders_blocks(self):
        r = validate_flat(
            positions=[], open_orders=[],
            conditional_orders=[{"id": "Y"}],
        )
        assert r.is_flat is False
        assert r.conditional_orders_count == 1

    def test_to_dict(self):
        r = validate_flat()
        d = r.to_dict()
        for key in (
            "is_flat", "positions_count", "open_orders_count",
            "conditional_orders_count", "residual_qty", "blockers",
        ):
            assert key in d


# ===========================================================================
# PnLTracker
# ===========================================================================

class TestPnLTracker:

    def test_execution_list_success(self):
        def fake_exec(symbol, start_ms, end_ms):
            return {"result": {"list": [
                {"execPnl": "1.5", "execFee": "0.1"},
                {"execPnl": "0.5", "execFee": "0.05"},
            ]}}
        tracker = PnLTracker(execution_list_fetch=fake_exec)
        r = tracker.fetch_pnl(
            symbol="BTCUSDT", entry_price=100.0, exit_price=102.0,
            qty=0.01, side="buy", entry_ms=1000, exit_ms=2000,
        )
        assert r.pnl_source == "api_execution_list"
        assert r.realized_pnl_usd == 2.0
        assert r.fees_usd == 0.15

    def test_falls_back_to_closed_pnl(self):
        tracker = PnLTracker(
            execution_list_fetch=lambda **k: None,
            closed_pnl_fetch=lambda **k: {"result": {"list": [
                {"closedPnl": "0.8", "cumExitFee": "0.02"},
            ]}},
        )
        r = tracker.fetch_pnl(
            symbol="BTCUSDT", entry_price=100.0, exit_price=102.0,
            qty=0.01, side="buy", entry_ms=1000, exit_ms=2000,
        )
        assert r.pnl_source == "api_closed_pnl"
        assert r.realized_pnl_usd == 0.8

    def test_falls_back_to_local(self):
        tracker = PnLTracker(
            execution_list_fetch=lambda **k: None,
            closed_pnl_fetch=lambda **k: None,
        )
        r = tracker.fetch_pnl(
            symbol="BTCUSDT", entry_price=100.0, exit_price=102.0,
            qty=0.5, side="buy", entry_ms=1000, exit_ms=2000,
        )
        assert r.pnl_source == "local_calculation"
        assert r.realized_pnl_usd == 1.0

    def test_falls_back_to_manual_pending(self):
        tracker = PnLTracker()
        r = tracker.fetch_pnl(
            symbol="BTCUSDT", entry_price=100.0, exit_price=None,
            qty=0.01, side="buy", entry_ms=1000, exit_ms=None,
        )
        assert r.pnl_source == "manual_pending"
        assert r.realized_pnl_usd is None

    def test_local_calculation_sell_side(self):
        tracker = PnLTracker()
        r = tracker.fetch_pnl(
            symbol="BTCUSDT", entry_price=100.0, exit_price=98.0,
            qty=1.0, side="sell", entry_ms=1000, exit_ms=2000,
        )
        assert r.pnl_source == "local_calculation"
        assert r.realized_pnl_usd == 2.0  # short profit

    def test_invalid_pnl_source_rejected(self):
        with pytest.raises(ValueError):
            PnLResult(
                realized_pnl_usd=1.0, fees_usd=0.0,
                pnl_source="bogus_source",
                entry_price=100.0, exit_price=102.0, qty=0.01,
                entry_timestamp=None, exit_timestamp=None,
                exit_reason=None,
            )


# ===========================================================================
# ExitDecisionResolver
# ===========================================================================

class TestExitResolver:

    def test_policy_has_reduce_only_capability(self):
        policy = build_phase29_exit_policy()
        cap = policy.provider_capability
        assert cap.supports_reduce_only is True
        assert cap.is_demo_environment is True

    def test_no_exit_when_no_trigger(self):
        from crypto_trading_bot.exchange.base_exchange import Candle
        resolver = ExitDecisionResolver(
            exit_policy=build_phase29_exit_policy(
                emergency_close_enabled=True,
            ),
            clock=lambda: NOW,
        )
        position = build_open_position_state_from_snapshot(
            {"side": "buy"}, symbol="BTCUSDT",
            entry_price=100.0, entry_time=NOW,
            stop_loss=95.0, take_profit=110.0,
            position_size_usd=100.0,
        )
        candle = Candle(
            symbol="BTCUSDT", timeframe="15", timestamp=NOW,
            open=102.0, high=103.0, low=101.0, close=102.0,
            volume=1.0,
        )
        decision = resolver.resolve(
            position=position, candle=candle, candle_idx=0,
        )
        assert decision.should_close is False

    def test_sl_hit_triggers_close(self):
        from crypto_trading_bot.exchange.base_exchange import Candle
        resolver = ExitDecisionResolver(
            exit_policy=build_phase29_exit_policy(),
            clock=lambda: NOW,
        )
        position = build_open_position_state_from_snapshot(
            {"side": "buy"}, symbol="BTCUSDT",
            entry_price=100.0, entry_time=NOW,
            stop_loss=95.0, take_profit=110.0,
            position_size_usd=100.0,
        )
        # candle baixou abaixo de SL
        candle = Candle(
            symbol="BTCUSDT", timeframe="15", timestamp=NOW,
            open=98.0, high=99.0, low=94.0, close=95.0,
            volume=1.0,
        )
        decision = resolver.resolve(
            position=position, candle=candle, candle_idx=0,
        )
        assert decision.should_close is True
        assert decision.reason.value == "stop_loss"
        assert decision.requires_reduce_only is True


# ===========================================================================
# PositionMonitor
# ===========================================================================

class TestPositionMonitor:

    def test_poll_happy_path(self):
        positions = [{"size": "0.003", "side": "Buy"}]
        m = PositionMonitor(
            symbol="BTCUSDT",
            positions_fetch=lambda **k: positions,
            orders_fetch=lambda **k: [],
            conditional_orders_fetch=lambda **k: [],
            ticker_fetch=lambda **k: 65000.0,
            clock=lambda: NOW,
            sleep=lambda s: None,
        )
        snap = m.poll_once(poll_idx=0)
        assert snap.open_position_qty == 0.003
        assert snap.mark_price == 65000.0
        assert snap.error is None

    def test_strike_increments_on_failure(self):
        def fail(*a, **kw):
            raise RuntimeError("net err")
        m = PositionMonitor(
            symbol="BTCUSDT", positions_fetch=fail,
            orders_fetch=lambda **k: [],
            conditional_orders_fetch=lambda **k: [],
            clock=lambda: NOW, sleep=lambda s: None,
        )
        m.poll_once(poll_idx=0)
        m.poll_once(poll_idx=1)
        m.poll_once(poll_idx=2)
        assert m.has_too_many_failures() is True

    def test_invalid_symbol_rejected(self):
        with pytest.raises(ValueError):
            PositionMonitor(
                symbol="", positions_fetch=lambda **k: [],
                orders_fetch=lambda **k: [],
                conditional_orders_fetch=lambda **k: [],
            )

    def test_position_flat_after_close(self):
        m = PositionMonitor(
            symbol="BTCUSDT",
            positions_fetch=lambda **k: [],
            orders_fetch=lambda **k: [],
            conditional_orders_fetch=lambda **k: [],
            clock=lambda: NOW, sleep=lambda s: None,
        )
        snap = m.poll_once(poll_idx=0)
        assert snap.is_flat is True
        assert snap.open_position_qty == 0.0


# ===========================================================================
# CloseExecutorWrapper
# ===========================================================================

class TestCloseExecutorWrapper:

    def test_buy_position_close_with_sell_order(self):
        captured = {}

        def fake_submit(*, symbol, side, qty, dry_run, confirm_demo_execution):
            captured.update(
                symbol=symbol, side=side, qty=qty,
                dry_run=dry_run,
                confirm_demo_execution=confirm_demo_execution,
            )
            r = MagicMock()
            r.success = True
            r.reason = "OK"
            r.manual_review_required = False
            r.safety_halt_recommended = False
            r.to_dict = lambda: {"ok": True}
            return r

        executor = MagicMock()
        executor.submit_reduce_only_close = fake_submit

        wrapper = CloseExecutorWrapper(executor=executor)
        result = wrapper.close_position(
            symbol="BTCUSDT", position_side="buy",
            position_qty=0.003, dry_run=True,
        )
        assert result.success
        assert captured["side"] == "sell"
        assert captured["qty"] == 0.003

    def test_sell_position_close_with_buy_order(self):
        executor = MagicMock()
        captured = {}

        def fake_submit(*, symbol, side, qty, dry_run,
                        confirm_demo_execution):
            captured["side"] = side
            r = MagicMock()
            r.success = True
            r.reason = "OK"
            r.manual_review_required = False
            r.safety_halt_recommended = False
            r.to_dict = lambda: {}
            return r
        executor.submit_reduce_only_close = fake_submit

        wrapper = CloseExecutorWrapper(executor=executor)
        wrapper.close_position(
            symbol="BTCUSDT", position_side="sell",
            position_qty=0.5, dry_run=True,
        )
        assert captured["side"] == "buy"

    def test_qty_zero_rejected(self):
        executor = MagicMock()
        wrapper = CloseExecutorWrapper(executor=executor)
        r = wrapper.close_position(
            symbol="BTCUSDT", position_side="buy",
            position_qty=0.0, dry_run=True,
        )
        assert r.success is False
        assert r.manual_review_required is True

    def test_dry_run_false_without_confirm_rejected(self):
        executor = MagicMock()
        wrapper = CloseExecutorWrapper(executor=executor)
        r = wrapper.close_position(
            symbol="BTCUSDT", position_side="buy",
            position_qty=0.003, dry_run=False,
            confirm_demo_execution=False,
        )
        assert r.success is False

    def test_executor_exception_caught(self):
        def fake_submit(**kw):
            raise RuntimeError("net down")
        executor = MagicMock()
        executor.submit_reduce_only_close = fake_submit
        wrapper = CloseExecutorWrapper(executor=executor)
        r = wrapper.close_position(
            symbol="BTCUSDT", position_side="buy",
            position_qty=0.003, dry_run=True,
        )
        assert r.success is False
        assert r.manual_review_required is True
        assert r.safety_halt_recommended is True

    def test_executor_without_method_rejected(self):
        with pytest.raises(TypeError):
            CloseExecutorWrapper(executor=object())
