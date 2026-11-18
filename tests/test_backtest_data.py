"""
Testes do BacktestData — Carregamento e Geração de Candles
============================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    BacktestDataError,
    _parse_timestamp,
    candles_to_csv_string,
    generate_candles_with_stop_hit,
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
    load_candles_from_csv_string,
    load_candles_from_list,
)
from crypto_trading_bot.exchange.base_exchange import Candle


# ---------------------------------------------------------------------------
# generate_trending_candles
# ---------------------------------------------------------------------------

class TestGenerateTrendingCandles:

    def test_returns_correct_count(self):
        candles = generate_trending_candles(100)
        assert len(candles) == 100

    def test_uptrend_prices_increase(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.001)
        assert candles[-1].close > candles[0].close

    def test_downtrend_prices_decrease(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=-0.001)
        assert candles[-1].close < candles[0].close

    def test_high_gte_close_and_open(self):
        for c in generate_trending_candles(50):
            assert c.high >= c.close, f"high={c.high} < close={c.close}"
            assert c.high >= c.open, f"high={c.high} < open={c.open}"

    def test_low_lte_close_and_open(self):
        for c in generate_trending_candles(50):
            assert c.low <= c.close, f"low={c.low} > close={c.close}"
            assert c.low <= c.open, f"low={c.low} > open={c.open}"

    def test_low_always_positive(self):
        for c in generate_trending_candles(100, trend_pct_per_candle=-0.01):
            assert c.low > 0

    def test_chronological_order(self):
        candles = generate_trending_candles(50)
        for i in range(1, len(candles)):
            assert candles[i].timestamp > candles[i - 1].timestamp

    def test_symbol_set(self):
        candles = generate_trending_candles(10, symbol="ETHUSDT")
        assert all(c.symbol == "ETHUSDT" for c in candles)

    def test_timeframe_set(self):
        candles = generate_trending_candles(10, timeframe="60")
        assert all(c.timeframe == "60" for c in candles)

    def test_candles_are_candle_instances(self):
        candles = generate_trending_candles(10)
        assert all(isinstance(c, Candle) for c in candles)

    def test_zero_candles_raises(self):
        with pytest.raises(BacktestDataError):
            generate_trending_candles(0)

    def test_negative_candles_raises(self):
        with pytest.raises(BacktestDataError):
            generate_trending_candles(-5)


# ---------------------------------------------------------------------------
# generate_ranging_candles
# ---------------------------------------------------------------------------

class TestGenerateRangingCandles:

    def test_returns_correct_count(self):
        candles = generate_ranging_candles(100)
        assert len(candles) == 100

    def test_prices_stay_near_center(self):
        center = 65000.0
        range_pct = 0.05  # ±5%
        candles = generate_ranging_candles(200, center_price=center, range_pct=range_pct)
        for c in candles:
            # Close deve estar dentro de ±7% do center (folga para spread)
            assert abs(c.close - center) / center < 0.10

    def test_chronological_order(self):
        candles = generate_ranging_candles(50)
        for i in range(1, len(candles)):
            assert candles[i].timestamp > candles[i - 1].timestamp

    def test_zero_raises(self):
        with pytest.raises(BacktestDataError):
            generate_ranging_candles(0)


# ---------------------------------------------------------------------------
# generate_candles_with_stop_hit
# ---------------------------------------------------------------------------

class TestGenerateCandlesWithStopHit:

    def test_stop_hit_scenario_has_stop_candle(self):
        """Último candle deve ter low <= stop_price."""
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0,
            stop_price=64000.0,
            hit_what="stop",
        )
        trigger = candles[-1]
        assert trigger.low <= 64000.0

    def test_tp_hit_scenario_has_tp_candle(self):
        """Último candle deve ter high >= take_profit_price."""
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0,
            stop_price=64000.0,
            take_profit_price=67000.0,
            hit_what="tp",
        )
        trigger = candles[-1]
        assert trigger.high >= 67000.0

    def test_both_hit_candle_has_both_prices(self):
        """Candle de ambiguidade deve ter low <= stop E high >= tp."""
        candles = generate_candles_with_stop_hit(
            entry_price=65000.0,
            stop_price=64000.0,
            take_profit_price=67000.0,
            hit_what="both",
        )
        trigger = candles[-1]
        assert trigger.low <= 64000.0
        assert trigger.high >= 67000.0

    def test_returns_list_of_candles(self):
        candles = generate_candles_with_stop_hit(n_before_entry=10)
        assert len(candles) > 0
        assert all(isinstance(c, Candle) for c in candles)


# ---------------------------------------------------------------------------
# load_candles_from_list
# ---------------------------------------------------------------------------

class TestLoadCandlesFromList:

    def _row(self, i: int) -> dict:
        return {
            "timestamp": f"2024-01-{i+1:02d}T00:00:00+00:00",
            "open": 65000.0 + i,
            "high": 65100.0 + i,
            "low": 64900.0 + i,
            "close": 65050.0 + i,
            "volume": 1000.0,
        }

    def test_loads_correct_count(self):
        data = [self._row(i) for i in range(5)]
        candles = load_candles_from_list(data)
        assert len(candles) == 5

    def test_candles_in_chronological_order(self):
        data = [self._row(i) for i in range(5)]
        candles = load_candles_from_list(data)
        for i in range(1, len(candles)):
            assert candles[i].timestamp > candles[i - 1].timestamp

    def test_symbol_applied(self):
        data = [self._row(0)]
        candles = load_candles_from_list(data, symbol="ETHUSDT")
        assert candles[0].symbol == "ETHUSDT"

    def test_empty_list_raises(self):
        with pytest.raises(BacktestDataError, match="vazia"):
            load_candles_from_list([])

    def test_missing_field_raises(self):
        data = [{"timestamp": "2024-01-01", "open": 1.0, "high": 1.1, "low": 0.9}]
        with pytest.raises(BacktestDataError, match="ausentes"):
            load_candles_from_list(data)

    def test_invalid_float_raises(self):
        data = [{
            "timestamp": "2024-01-01T00:00:00+00:00",
            "open": "not_a_number", "high": 1.1, "low": 0.9,
            "close": 1.0, "volume": 100.0
        }]
        with pytest.raises(BacktestDataError):
            load_candles_from_list(data)


# ---------------------------------------------------------------------------
# load_candles_from_csv_string
# ---------------------------------------------------------------------------

class TestLoadCandlesFromCsvString:

    _VALID_CSV = (
        "timestamp,open,high,low,close,volume\n"
        "2024-01-01T00:00:00+00:00,65000,65500,64800,65200,1000\n"
        "2024-01-02T00:00:00+00:00,65200,65700,65000,65400,1200\n"
    )

    def test_loads_two_candles(self):
        candles = load_candles_from_csv_string(self._VALID_CSV)
        assert len(candles) == 2

    def test_prices_correct(self):
        candles = load_candles_from_csv_string(self._VALID_CSV)
        assert candles[0].close == 65200.0
        assert candles[0].high == 65500.0

    def test_empty_string_raises(self):
        with pytest.raises(BacktestDataError):
            load_candles_from_csv_string("")

    def test_missing_column_raises(self):
        bad_csv = "timestamp,open,high,low\n2024-01-01,65000,65500,64800\n"
        with pytest.raises(BacktestDataError):
            load_candles_from_csv_string(bad_csv)

    def test_header_only_raises(self):
        with pytest.raises(BacktestDataError):
            load_candles_from_csv_string("timestamp,open,high,low,close,volume\n")


# ---------------------------------------------------------------------------
# candles_to_csv_string (round-trip)
# ---------------------------------------------------------------------------

class TestCandlesToCsvString:

    def test_round_trip(self):
        """Serializar e deserializar deve retornar os mesmos dados."""
        original = generate_trending_candles(10)
        csv_str = candles_to_csv_string(original)
        restored = load_candles_from_csv_string(csv_str)
        assert len(restored) == len(original)
        for orig, rest in zip(original, restored):
            assert abs(orig.close - rest.close) < 0.01
            assert abs(orig.high - rest.high) < 0.01

    def test_includes_header(self):
        candles = generate_trending_candles(3)
        csv_str = candles_to_csv_string(candles, include_header=True)
        assert "timestamp" in csv_str.lower()
        assert "close" in csv_str.lower()


# ---------------------------------------------------------------------------
# _parse_timestamp
# ---------------------------------------------------------------------------

class TestParseTimestamp:

    def test_iso_with_timezone(self):
        dt = _parse_timestamp("2024-01-01T12:00:00+00:00")
        assert dt.year == 2024
        assert dt.tzinfo is not None

    def test_iso_without_timezone_assumes_utc(self):
        dt = _parse_timestamp("2024-01-01T12:00:00")
        assert dt.tzinfo is not None

    def test_unix_seconds(self):
        dt = _parse_timestamp(1704067200)  # 2024-01-01
        assert dt.year == 2024

    def test_unix_milliseconds(self):
        dt = _parse_timestamp(1704067200000)  # ms
        assert dt.year == 2024

    def test_datetime_with_tz_passthrough(self):
        original = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = _parse_timestamp(original)
        assert result == original

    def test_datetime_without_tz_adds_utc(self):
        naive = datetime(2024, 1, 1)
        result = _parse_timestamp(naive)
        assert result.tzinfo is not None

    def test_invalid_string_raises(self):
        with pytest.raises(BacktestDataError):
            _parse_timestamp("not_a_date")


# ---------------------------------------------------------------------------
# Validação de OHLCV em todos os geradores sintéticos (FASE 3D.5)
# Garante invariantes determinísticos independentemente do gerador:
#   - high >= max(open, close)
#   - low  <= min(open, close)
#   - low  > 0
#   - volume >= 0
#   - timestamps estritamente crescentes
#   - symbol e timeframe preservados
# ---------------------------------------------------------------------------

def _gen_trending(symbol: str, timeframe: str):
    return generate_trending_candles(50, symbol=symbol, timeframe=timeframe)


def _gen_ranging(symbol: str, timeframe: str):
    return generate_ranging_candles(50, symbol=symbol, timeframe=timeframe)


def _gen_stop_hit(symbol: str, timeframe: str):
    return generate_candles_with_stop_hit(
        entry_price=65000.0,
        stop_price=64000.0,
        take_profit_price=67000.0,
        n_before_entry=20,
        n_after_entry=3,
        hit_what="both",
        symbol=symbol,
        timeframe=timeframe,
    )


def _gen_volatile(symbol: str, timeframe: str):
    # FASE 3E.3 — novo gerador inclui-se nas mesmas invariantes OHLCV.
    return generate_volatile_candles(
        50, volatility_pct=0.05, symbol=symbol, timeframe=timeframe
    )


_GENERATORS = [
    pytest.param(_gen_trending, id="trending"),
    pytest.param(_gen_ranging, id="ranging"),
    pytest.param(_gen_stop_hit, id="stop_hit"),
    pytest.param(_gen_volatile, id="volatile"),
]


class TestSyntheticCandlesOhlcvInvariants:
    """
    Invariantes OHLCV que TODOS os geradores sintéticos devem respeitar.
    Aplicado a generate_trending_candles, generate_ranging_candles e
    generate_candles_with_stop_hit via parametrização.
    """

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_high_ge_max_open_close(self, gen):
        for c in gen("BTCUSDT", "15"):
            assert c.high >= max(c.open, c.close), (
                f"high={c.high} < max(open={c.open}, close={c.close})"
            )

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_low_le_min_open_close(self, gen):
        for c in gen("BTCUSDT", "15"):
            assert c.low <= min(c.open, c.close), (
                f"low={c.low} > min(open={c.open}, close={c.close})"
            )

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_low_strictly_positive(self, gen):
        for c in gen("BTCUSDT", "15"):
            assert c.low > 0, f"low={c.low} deve ser estritamente positivo"

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_volume_non_negative(self, gen):
        for c in gen("BTCUSDT", "15"):
            assert c.volume >= 0, f"volume={c.volume} deve ser >= 0"

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_timestamps_strictly_increasing(self, gen):
        candles = gen("BTCUSDT", "15")
        for i in range(1, len(candles)):
            assert candles[i].timestamp > candles[i - 1].timestamp, (
                f"Timestamp não estritamente crescente em índice {i}: "
                f"{candles[i - 1].timestamp} → {candles[i].timestamp}"
            )

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_symbol_preserved(self, gen):
        symbol = "ETHUSDT"
        for c in gen(symbol, "15"):
            assert c.symbol == symbol, f"symbol={c.symbol} != esperado={symbol}"

    @pytest.mark.parametrize("gen", _GENERATORS)
    def test_timeframe_preserved(self, gen):
        timeframe = "60"
        for c in gen("BTCUSDT", timeframe):
            assert c.timeframe == timeframe, (
                f"timeframe={c.timeframe} != esperado={timeframe}"
            )


# ---------------------------------------------------------------------------
# FASE 3E.3 — Testes específicos de generate_volatile_candles
# ---------------------------------------------------------------------------

class TestGenerateVolatileCandles:
    """
    Testes específicos do gerador de candles voláteis (FASE 3E.3).
    Invariantes OHLCV gerais ficam em TestSyntheticCandlesOhlcvInvariants.
    """

    def test_returns_correct_count(self):
        candles = generate_volatile_candles(80, volatility_pct=0.05)
        assert len(candles) == 80

    def test_high_volatility_produces_wider_range_than_trending(self):
        """
        Spread médio (high-low) do gerador volatile DEVE ser maior que o
        do trending com defaults. Confirma que o gerador realmente entrega
        volatilidade alta, não apenas um nome.
        """
        n = 100
        volatile = generate_volatile_candles(n, volatility_pct=0.05)
        trending = generate_trending_candles(n)  # volatility_pct default = 0.005

        avg_range_volatile = sum(c.high - c.low for c in volatile) / n
        avg_range_trending = sum(c.high - c.low for c in trending) / n

        assert avg_range_volatile > avg_range_trending, (
            f"Volatile range médio ({avg_range_volatile:.2f}) deve ser maior "
            f"que trending ({avg_range_trending:.2f})."
        )

    def test_deterministic_same_input_same_output(self):
        """Sem random: chamadas idênticas produzem candles idênticos."""
        c1 = generate_volatile_candles(50, volatility_pct=0.05, base_price=65000.0)
        c2 = generate_volatile_candles(50, volatility_pct=0.05, base_price=65000.0)
        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.open == b.open
            assert a.high == b.high
            assert a.low == b.low
            assert a.close == b.close
            assert a.volume == b.volume
            assert a.timestamp == b.timestamp

    def test_zero_candles_raises(self):
        with pytest.raises(BacktestDataError):
            generate_volatile_candles(0)

    def test_negative_base_price_raises(self):
        with pytest.raises(BacktestDataError):
            generate_volatile_candles(10, base_price=-1.0)

    def test_low_stays_positive_even_with_extreme_volatility(self):
        """
        Mesmo com volatility_pct=0.5 (50%, extremo), low > 0 (clamp em 0.01).
        """
        candles = generate_volatile_candles(30, volatility_pct=0.5)
        for c in candles:
            assert c.low > 0, f"low={c.low} deveria ser > 0"
