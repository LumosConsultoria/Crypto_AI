"""
Testes do Data Quality Validator — FASE 3G
=============================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - validate_candles: ok, vazio, duplicatas, não-monotônico, OHLCV inválido,
      volume negativo, low <= 0, gap, symbol/timeframe inconsistente.
    - validate_candles_strict: lança DataQualityError em issues.
    - DataQualityReport.summary().
    - timeframe_to_minutes: aceitos, inválidos, inteiros arbitrários.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from crypto_trading_bot.data.data_quality import (
    DataQualityError,
    DataQualityIssue,
    DataQualityReport,
    timeframe_to_minutes,
    validate_candles,
    validate_candles_strict,
)
from crypto_trading_bot.exchange.base_exchange import Candle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_INTERVAL = timedelta(minutes=15)


def _candle(
    i: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    open: float = 65000.0,
    high: float = 65100.0,
    low: float = 64900.0,
    close: float = 65000.0,
    volume: float = 1000.0,
    timestamp: datetime | None = None,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=timestamp if timestamp is not None else _TS0 + _INTERVAL * i,
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _valid_candles(n: int = 5) -> List[Candle]:
    return [_candle(i) for i in range(n)]


# ---------------------------------------------------------------------------
# timeframe_to_minutes
# ---------------------------------------------------------------------------

class TestTimeframeToMinutes:

    @pytest.mark.parametrize("tf,expected", [
        ("1", 1), ("3", 3), ("5", 5), ("15", 15), ("30", 30),
        ("60", 60), ("120", 120), ("240", 240), ("360", 360), ("720", 720),
        ("D", 1440), ("W", 10080),
    ])
    def test_accepted_timeframes(self, tf, expected):
        assert timeframe_to_minutes(tf) == expected

    def test_invalid_timeframe_raises(self):
        with pytest.raises(ValueError, match="Timeframe"):
            timeframe_to_minutes("invalid")

    def test_zero_timeframe_raises(self):
        with pytest.raises(ValueError, match="positivo"):
            timeframe_to_minutes("0")

    def test_negative_timeframe_raises(self):
        with pytest.raises(ValueError, match="positivo"):
            timeframe_to_minutes("-5")

    def test_arbitrary_integer_string(self):
        """Inteiro não-mapeado é interpretado como minutos diretos."""
        assert timeframe_to_minutes("45") == 45


# ---------------------------------------------------------------------------
# validate_candles — caminhos felizes e edge cases
# ---------------------------------------------------------------------------

class TestValidateCandlesHappyPath:

    def test_valid_candles_returns_ok_report(self):
        report = validate_candles(_valid_candles(5))
        assert isinstance(report, DataQualityReport)
        assert report.ok is True
        assert report.n_candles == 5
        assert report.issues == ()
        assert report.gap_indices == ()
        assert report.duplicate_indices == ()

    def test_empty_candles_returns_empty_report(self):
        report = validate_candles([])
        assert report.n_candles == 0
        assert report.ok is True
        assert report.issues == ()


# ---------------------------------------------------------------------------
# validate_candles — detecções específicas
# ---------------------------------------------------------------------------

class TestValidateCandlesDetections:

    def test_detects_duplicate_timestamps(self):
        candles = _valid_candles(3)
        # Duplica timestamp do candle 1 no candle 2
        candles[2] = _candle(2, timestamp=candles[1].timestamp)
        report = validate_candles(candles)
        assert not report.ok
        kinds = {iss.kind for iss in report.issues}
        assert "duplicate_timestamp" in kinds
        assert 2 in report.duplicate_indices

    def test_detects_non_monotonic_timestamps(self):
        candles = _valid_candles(3)
        # Timestamp do candle 2 fica ANTES do candle 1
        candles[2] = _candle(0)  # mesmo timestamp do candle 0 → também é "antes"
        # Mas detectamos "anterior" ou "duplicado"; vamos forçar estritamente anterior:
        candles[2] = _candle(2, timestamp=candles[1].timestamp - timedelta(minutes=5))
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "non_monotonic_timestamp" in kinds

    def test_detects_high_below_max_open_close(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, high=64500.0, open=65000.0, close=65200.0)
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "high_below_max_oc" in kinds

    def test_detects_low_above_min_open_close(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, low=65500.0, open=65000.0, close=65200.0)
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "low_above_min_oc" in kinds

    def test_detects_zero_low(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, low=0.0, open=65000.0, close=65200.0, high=65300.0)
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "non_positive_low" in kinds

    def test_detects_negative_low(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, low=-100.0, open=65000.0, close=65200.0, high=65300.0)
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "non_positive_low" in kinds

    def test_detects_negative_volume(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, volume=-50.0)
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "negative_volume" in kinds

    def test_volume_zero_is_acceptable(self):
        """Volume zero é PERMITIDO (only negative is bad)."""
        candles = _valid_candles(2)
        candles[1] = _candle(1, volume=0.0)
        report = validate_candles(candles)
        assert not any(iss.kind == "negative_volume" for iss in report.issues)

    def test_detects_gap_when_timeframe_known(self):
        """
        3 candles consecutivos com timestamps esperados a cada 15min.
        Pulamos um → gap detectado.
        """
        c0 = _candle(0)
        c1 = _candle(1)
        # Salto de 30min (1 candle pulado) entre c1 e c2:
        c2 = _candle(2, timestamp=c1.timestamp + timedelta(minutes=30))
        report = validate_candles([c0, c1, c2])
        kinds = {iss.kind for iss in report.issues}
        assert "gap_detected" in kinds
        assert 1 in report.gap_indices  # gap entre idx=1 e idx=2

    def test_no_gap_with_consecutive_timestamps(self):
        report = validate_candles(_valid_candles(10))
        assert not any(iss.kind == "gap_detected" for iss in report.issues)
        assert report.gap_indices == ()

    def test_detects_symbol_inconsistency(self):
        candles = _valid_candles(3)
        candles[2] = _candle(2, symbol="ETHUSDT")
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "symbol_inconsistency" in kinds

    def test_detects_timeframe_inconsistency(self):
        candles = _valid_candles(3)
        candles[2] = _candle(2, timeframe="60")
        report = validate_candles(candles)
        kinds = {iss.kind for iss in report.issues}
        assert "timeframe_inconsistency" in kinds


# ---------------------------------------------------------------------------
# validate_candles_strict
# ---------------------------------------------------------------------------

class TestValidateCandlesStrict:

    def test_strict_ok_no_raise(self):
        # Não deve lançar
        validate_candles_strict(_valid_candles(5))

    def test_strict_raises_on_issues(self):
        bad = _valid_candles(2)
        bad[1] = _candle(1, high=64000.0, open=65000.0, close=65200.0)
        with pytest.raises(DataQualityError) as exc_info:
            validate_candles_strict(bad)
        # Carrega report no exception
        assert exc_info.value.report.ok is False
        assert len(exc_info.value.report.issues) > 0

    def test_strict_empty_does_not_raise(self):
        """Lista vazia é ok (n_candles=0, sem issues)."""
        validate_candles_strict([])


# ---------------------------------------------------------------------------
# DataQualityReport.summary
# ---------------------------------------------------------------------------

class TestDataQualityReportSummary:

    def test_summary_contains_key_info(self):
        report = validate_candles(_valid_candles(5))
        text = report.summary()
        assert "DATA QUALITY REPORT" in text
        assert "Total candles" in text
        assert "✅ OK" in text

    def test_summary_lists_issues_when_present(self):
        candles = _valid_candles(2)
        candles[1] = _candle(1, volume=-1.0)
        report = validate_candles(candles)
        text = report.summary()
        assert "PROBLEMAS DETECTADOS" in text
        assert "negative_volume" in text
