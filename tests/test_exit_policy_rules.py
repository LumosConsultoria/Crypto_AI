"""
Testes de precedência da ExitPolicy (FASE 11)
=============================================
⚠️  100% offline. ZERO rede.

Cobertura: ordem determinística
    1. Emergency
    2. Manual
    3. SL (vence TP no mesmo candle)
    4. TP
    5. Opposite signal (se habilitado)
    6. Time limit (candles e segundos)
    7. Default
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy,
    ExitReason,
    ExitSource,
    OpenPositionState,
    PositionSide,
)
from crypto_trading_bot.strategies.signal_model import (
    StrategyAction,
    StrategySignal,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap(supports_ro: bool = True, provider_id: str = "mock") -> ProviderCapability:
    return ProviderCapability(
        provider_id=provider_id,
        supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _buy_position(
    sl: float = 64000.0,
    tp: float = 67000.0,
    entry_idx: int = 10,
    entry_time: datetime = _NOW,
) -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT",
        side=PositionSide.BUY,
        entry_price=65000.0,
        entry_time=entry_time,
        stop_loss_price=sl,
        take_profit_price=tp,
        position_size_usd=200.0,
        entry_candle_idx=entry_idx,
    )


def _sell_position(
    sl: float = 66000.0,
    tp: float = 63000.0,
    entry_idx: int = 10,
) -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT",
        side=PositionSide.SELL,
        entry_price=65000.0,
        entry_time=_NOW,
        stop_loss_price=sl,
        take_profit_price=tp,
        position_size_usd=200.0,
        entry_candle_idx=entry_idx,
    )


def _candle(*, low: float, high: float, close: float = 65000.0) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        timeframe="15",
        timestamp=_NOW,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1000.0,
    )


# ---------------------------------------------------------------------------
# Precedência
# ---------------------------------------------------------------------------

class TestEmergencyPrecedence:

    def test_emergency_wins_when_enabled(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            emergency_close_enabled=True,
            allow_close_on_opposite_signal=True,
            max_time_in_position_candles=5,
        )
        # Posição com TODOS os triggers ativos ao mesmo tempo
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=60000.0, high=70000.0),  # SL e TP batem
            now=_NOW,
            candle_idx=100,  # tempo excedido
            latest_signal=StrategySignal.sell(
                symbol="BTCUSDT", strategy_name="x",
                entry_price=65000.0, stop_loss_price=66000.0,
                position_size_usd=200.0,
            ),
            manual_close_requested=True,
            emergency_active=True,
        )
        assert d.should_close
        assert d.reason == ExitReason.EMERGENCY
        assert d.source == ExitSource.RULE_EMERGENCY

    def test_emergency_inactive_when_flag_disabled(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            emergency_close_enabled=False,
        )
        d = policy.evaluate(
            position=_buy_position(),
            now=_NOW,
            emergency_active=True,
            manual_close_requested=True,
        )
        assert d.reason == ExitReason.MANUAL


class TestManualPrecedence:

    def test_manual_beats_sl_tp_and_time(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=5,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=60000.0, high=70000.0),  # SL+TP
            now=_NOW,
            candle_idx=100,
            manual_close_requested=True,
        )
        assert d.should_close
        assert d.reason == ExitReason.MANUAL
        assert d.source == ExitSource.RULE_MANUAL


class TestStopLossPrecedence:

    def test_stop_loss_wins_when_both_hit_same_candle_buy(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_buy_position(sl=64000.0, tp=67000.0),
            candle=_candle(low=63500.0, high=67500.0),
            now=_NOW,
            candle_idx=11,
        )
        assert d.reason == ExitReason.STOP_LOSS
        assert d.source == ExitSource.RULE_SL_TP
        assert d.metadata.get("tp_also_hit") is True

    def test_stop_loss_wins_when_both_hit_same_candle_sell(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_sell_position(sl=66000.0, tp=63000.0),
            candle=_candle(low=62500.0, high=66500.0),
            now=_NOW,
            candle_idx=11,
        )
        assert d.reason == ExitReason.STOP_LOSS

    def test_stop_only_triggers(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=63500.0, high=65500.0),
            now=_NOW,
            candle_idx=11,
        )
        assert d.reason == ExitReason.STOP_LOSS


class TestTakeProfitPrecedence:

    def test_tp_triggers_when_sl_not_hit(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_buy_position(sl=64000.0, tp=67000.0),
            candle=_candle(low=64500.0, high=67500.0),  # tp hit, sl não
            now=_NOW,
            candle_idx=11,
        )
        assert d.reason == ExitReason.TAKE_PROFIT
        assert d.source == ExitSource.RULE_SL_TP

    def test_tp_for_sell_side(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_sell_position(sl=66000.0, tp=63000.0),
            candle=_candle(low=62500.0, high=65500.0),  # tp hit
            now=_NOW,
            candle_idx=11,
        )
        assert d.reason == ExitReason.TAKE_PROFIT

    def test_tp_none_does_not_fire(self):
        policy = ExitPolicy(provider_capability=_cap())
        pos = OpenPositionState(
            symbol="BTCUSDT", side=PositionSide.BUY,
            entry_price=65000.0, entry_time=_NOW,
            stop_loss_price=64000.0, position_size_usd=200.0,
            entry_candle_idx=10,  # take_profit_price=None
        )
        d = policy.evaluate(
            position=pos,
            candle=_candle(low=64500.0, high=70000.0),
            now=_NOW,
            candle_idx=11,
        )
        # Sem TP definido e SL não bate → not should_close
        assert d.should_close is False


class TestOppositeSignalPrecedence:

    def test_opposite_signal_fires_when_enabled(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.sell(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=66000.0,
                position_size_usd=200.0,
            ),
        )
        assert d.reason == ExitReason.OPPOSITE_SIGNAL
        assert d.source == ExitSource.RULE_OPPOSITE

    def test_opposite_signal_ignored_when_disabled(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=False,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.sell(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=66000.0,
                position_size_usd=200.0,
            ),
        )
        assert d.should_close is False

    def test_same_direction_signal_does_not_fire(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.buy(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=64000.0,
                position_size_usd=200.0,
            ),
        )
        assert d.should_close is False


class TestTimeLimit:

    def test_time_limit_by_candles_fires(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=5,
        )
        d = policy.evaluate(
            position=_buy_position(entry_idx=10),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=15,  # 15-10=5 ≥ 5
        )
        assert d.reason == ExitReason.TIME_LIMIT
        assert d.source == ExitSource.RULE_TIME
        assert d.metadata.get("limit_kind") == "candles"
        assert d.metadata.get("elapsed_candles") == 5

    def test_time_limit_by_candles_not_fired(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_candles=10,
        )
        d = policy.evaluate(
            position=_buy_position(entry_idx=10),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=15,  # 5 < 10
        )
        assert d.should_close is False

    def test_time_limit_by_seconds_fires(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_seconds=300,
        )
        entry_time = _NOW
        now_late = entry_time + timedelta(seconds=400)
        d = policy.evaluate(
            position=_buy_position(entry_time=entry_time),
            now=now_late,
        )
        assert d.reason == ExitReason.TIME_LIMIT
        assert d.metadata.get("limit_kind") == "seconds"

    def test_time_limit_by_seconds_not_fired(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            max_time_in_position_seconds=600,
        )
        now_short = _NOW + timedelta(seconds=100)
        d = policy.evaluate(
            position=_buy_position(entry_time=_NOW),
            now=now_short,
        )
        assert d.should_close is False


class TestDefaultNoClose:

    def test_default_returns_should_close_false(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(low=64500.0, high=65500.0),
            now=_NOW,
            candle_idx=11,
        )
        assert d.should_close is False
        assert d.reason == ExitReason.NONE
        assert d.source == ExitSource.NONE


# ---------------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_same_inputs_same_decision(self):
        policy = ExitPolicy(provider_capability=_cap())
        pos = _buy_position()
        c = _candle(low=63500.0, high=65500.0)
        d1 = policy.evaluate(position=pos, candle=c, now=_NOW, candle_idx=11)
        d2 = policy.evaluate(position=pos, candle=c, now=_NOW, candle_idx=11)
        assert d1.reason == d2.reason
        assert d1.source == d2.source
        assert d1.requires_reduce_only == d2.requires_reduce_only
        assert d1.auto_execute_blocked == d2.auto_execute_blocked
        assert d1.triggered_at_idx == d2.triggered_at_idx

    def test_candle_none_still_works_for_manual(self):
        policy = ExitPolicy(provider_capability=_cap())
        d = policy.evaluate(
            position=_buy_position(),
            candle=None,
            now=_NOW,
            manual_close_requested=True,
        )
        assert d.reason == ExitReason.MANUAL


# ---------------------------------------------------------------------------
# Validações de construtor
# ---------------------------------------------------------------------------

class TestConstructorValidation:

    def test_rejects_non_capability(self):
        with pytest.raises(TypeError):
            ExitPolicy(provider_capability="not_a_capability")  # type: ignore[arg-type]

    def test_rejects_invalid_time_limits(self):
        with pytest.raises(ValueError):
            ExitPolicy(
                provider_capability=_cap(),
                max_time_in_position_candles=0,
            )
        with pytest.raises(ValueError):
            ExitPolicy(
                provider_capability=_cap(),
                max_time_in_position_seconds=-1,
            )
