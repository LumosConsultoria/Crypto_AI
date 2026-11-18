"""
Tests - FASE 36.x: Historical Data Readiness BTCUSDT 15m
=========================================================
100% offline. ZERO rede / API / ordem. Datasets gerados em memoria
ou tmp_path. Reaproveita o formato canonico OHLCV/UTC do projeto.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crypto_trading_bot.data_readiness import (
    DEFAULT_MIN_ROWS_BACKTEST,
    ReadinessStatus,
    canonical_dataset_path,
    describe_source_contract,
    import_candle_dataset,
    validate_candle_dataset,
)

_REPO_ROOT = Path(__file__).parent.parent
_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _csv(
    n, *, dup=False, gap_at=None, gap_candles=0, bad_ohlc_at=None,
    neg_vol_at=None, out_of_order=False, tz="Z", interval_min=15,
):
    lines = ["timestamp,open,high,low,close,volume"]
    t = _START
    for i in range(n):
        o, h, lo, c, v = 65000.0, 65100.0, 64900.0, 65050.0, 123.4
        if bad_ohlc_at == i:
            h = 64000.0   # high < open => invalido
        if neg_vol_at == i:
            v = -5.0
        ts = t.strftime("%Y-%m-%dT%H:%M:%S") + (
            "Z" if tz == "Z" else tz
        )
        lines.append(f"{ts},{o},{h},{lo},{c},{v}")
        if dup and i == 3:
            lines.append(f"{ts},{o},{h},{lo},{c},{v}")
        step = interval_min
        if gap_at == i:
            step = interval_min * (1 + gap_candles)
        t += timedelta(minutes=step)
    if out_of_order and n >= 2:
        lines[1], lines[2] = lines[2], lines[1]
    return "\n".join(lines)


# Acima do minimo p/ backtest, abaixo do minimo p/ walk-forward.
_N_OK = DEFAULT_MIN_ROWS_BACKTEST + 50


class TestValidator:

    def test_valid_csv_passes(self):
        r = validate_candle_dataset(csv_text=_csv(_N_OK))
        assert r.readiness_status in (
            ReadinessStatus.READY, ReadinessStatus.READY_WITH_WARNINGS,
        )
        assert r.real_dataset_available is True
        assert r.blocks_backtest is False
        assert r.rows == _N_OK
        assert r.checksum is not None
        assert r.start_timestamp and r.end_timestamp

    def test_duplicate_fails(self):
        r = validate_candle_dataset(csv_text=_csv(_N_OK, dup=True))
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert r.duplicates_count == 1
        assert r.blocks_backtest is True

    def test_out_of_order_fails(self):
        r = validate_candle_dataset(
            csv_text=_csv(_N_OK, out_of_order=True),
        )
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert r.out_of_order_count >= 1

    def test_critical_gap_fails(self):
        # buraco enorme -> gap_fraction > 2% -> not_ready.
        r = validate_candle_dataset(
            csv_text=_csv(_N_OK, gap_at=10, gap_candles=300),
        )
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert r.missing_candles_count == 300
        assert r.blocks_walk_forward is True

    def test_small_gap_warns_but_ready(self):
        # 1 candle faltante em ~550 -> << 2% -> ready_with_warnings.
        r = validate_candle_dataset(
            csv_text=_csv(_N_OK, gap_at=10, gap_candles=1),
        )
        assert r.readiness_status is ReadinessStatus.READY_WITH_WARNINGS
        assert r.gaps_count == 1
        assert r.blocks_backtest is False

    def test_invalid_ohlc_fails(self):
        r = validate_candle_dataset(
            csv_text=_csv(_N_OK, bad_ohlc_at=5),
        )
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert r.invalid_ohlc_count == 1

    def test_negative_volume_fails(self):
        r = validate_candle_dataset(
            csv_text=_csv(_N_OK, neg_vol_at=7),
        )
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert r.volume_anomalies_count == 1

    def test_timezone_non_utc_normalized_with_warning(self):
        r = validate_candle_dataset(csv_text=_csv(_N_OK, tz="+03:00"))
        assert r.readiness_status is ReadinessStatus.READY_WITH_WARNINGS
        assert r.non_utc_normalized_count == _N_OK
        assert any("UTC" in w for w in r.warnings)

    def test_insufficient_blocks_backtest(self):
        r = validate_candle_dataset(csv_text=_csv(100))
        assert r.readiness_status is ReadinessStatus.INSUFFICIENT_DATA
        assert r.blocks_backtest is True
        assert r.blocks_walk_forward is True
        assert r.real_dataset_available is False

    def test_midsize_blocks_only_walk_forward(self):
        # >= min backtest, < min walk-forward.
        r = validate_candle_dataset(csv_text=_csv(_N_OK))
        assert r.blocks_backtest is False
        assert r.blocks_walk_forward is True  # _N_OK < 2000

    def test_large_enables_walk_forward(self):
        r = validate_candle_dataset(csv_text=_csv(2100))
        assert r.readiness_status is ReadinessStatus.READY
        assert r.blocks_walk_forward is False

    def test_missing_columns_not_ready(self):
        bad = "timestamp,open,high,low,close\n" + \
            "2026-01-01T00:00:00Z,1,2,0.5,1.5"
        r = validate_candle_dataset(csv_text=bad)
        assert r.readiness_status is ReadinessStatus.NOT_READY
        assert any("volume" in b for b in r.blockers)

    def test_missing_file_is_missing_status(self):
        r = validate_candle_dataset(
            csv_path="reports/_does_not_exist_xyz.csv",
        )
        assert r.readiness_status is ReadinessStatus.MISSING
        assert r.real_dataset_available is False

    def test_to_dict_has_required_fields(self):
        d = validate_candle_dataset(csv_text=_csv(_N_OK)).to_dict()
        for k in (
            "dataset_path", "symbol", "timeframe", "rows",
            "start_timestamp", "end_timestamp", "coverage_days",
            "gaps_count", "duplicates_count", "invalid_ohlc_count",
            "volume_anomalies_count", "source", "checksum",
            "readiness_status", "blocks_backtest",
            "blocks_walk_forward", "warnings",
        ):
            assert k in d, k


class TestImporter:

    def test_import_valid_writes_canonical_and_metadata(self, tmp_path):
        src = tmp_path / "src.csv"
        src.write_text(_csv(2100), encoding="utf-8")
        base = tmp_path / "data_hist"
        report, dest = import_candle_dataset(
            src_csv=str(src), symbol="BTCUSDT", timeframe="15",
            base_dir=str(base),
        )
        assert dest is not None
        dest_p = Path(dest)
        assert dest_p.is_file()
        meta = dest_p.parent / "metadata.json"
        assert meta.is_file()
        md = json.loads(meta.read_text(encoding="utf-8"))
        assert md["readiness_status"] in ("ready",
                                          "ready_with_warnings")
        assert md["imported_at"]
        assert md["checksum"]

    def test_import_invalid_refused(self, tmp_path):
        src = tmp_path / "bad.csv"
        src.write_text(_csv(_N_OK, dup=True), encoding="utf-8")
        base = tmp_path / "data_hist"
        report, dest = import_candle_dataset(
            src_csv=str(src), base_dir=str(base),
        )
        assert dest is None
        assert report.readiness_status is ReadinessStatus.NOT_READY
        assert not (base).exists() or not any(base.rglob("*.csv"))

    def test_canonical_path_shape(self):
        p = canonical_dataset_path("BTCUSDT", "15", "data/historical")
        assert p.as_posix().endswith(
            "data/historical/BTCUSDT/15m/BTCUSDT_15m.csv",
        )


class TestSourceContract:

    def test_contract_no_auto_fetch(self):
        c = describe_source_contract()
        assert c["fetch_status"] == "manual_import_required"
        assert "timestamp" in c["required_columns"]
        assert "volume" in c["required_columns"]
        assert "bybit_historical_klines" in c["future_sources"]


class TestAdvisorIntegration:

    def _candles(self, vol=0.0024, n=400):
        import random
        random.seed(36003)
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        return generate_trending_candles(
            n=n, base_price=65000.0, trend_pct_per_candle=0.0004,
            volatility_pct=vol, symbol="BTCUSDT", timeframe="15",
        )

    def test_synthetic_blocks_aggressive_real_use(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        rep = analyze_sl_calibration(
            candles=self._candles(), data_source="synthetic_low_vol",
            run_backtests=False, real_dataset_available=False,
            walk_forward_available=False,
        )
        assert rep["synthetic_only"] is True
        assert rep["real_dataset_available"] is False
        assert rep["aggressive_ready_for_real"] is False
        arr = next(r for r in rep["recommendations"]
                   if r["profile"] == "arrojado")
        assert arr["ready_for_real_use"] is False
        assert arr["blocked_reason"]

    def test_real_dataset_enables_aggressive_flag(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        rep = analyze_sl_calibration(
            candles=self._candles(), data_source="csv:real.csv",
            run_backtests=False, real_dataset_available=True,
            walk_forward_available=True,
        )
        assert rep["synthetic_only"] is False
        assert rep["aggressive_ready_for_real"] is True
        arr = next(r for r in rep["recommendations"]
                   if r["profile"] == "arrojado")
        assert arr["ready_for_real_use"] is True
        assert arr["blocked_reason"] is None

    def test_real_dataset_without_wf_still_blocks_aggressive(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        rep = analyze_sl_calibration(
            candles=self._candles(), data_source="csv:real.csv",
            run_backtests=False, real_dataset_available=True,
            walk_forward_available=False,
        )
        assert rep["aggressive_ready_for_real"] is False


class TestCLISourceGuards:

    def test_no_network_no_dotenv(self):
        src = (
            _REPO_ROOT / "scripts" / "run_data_readiness.py"
        ).read_text(encoding="utf-8")
        assert "load_dotenv" not in src
        assert "import httpx" not in src
        assert "requests" not in src
        assert "submit_order" not in src

    def test_cli_validate_missing(self, tmp_path):
        out = tmp_path / "rep.json"
        r = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "run_data_readiness.py"),
             "--from-csv", str(tmp_path / "nope.csv"),
             "--output", str(out)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=120, check=False,
        )
        assert r.returncode == 1
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["readiness_status"] == "missing"

    def test_cli_validate_and_import(self, tmp_path):
        src = tmp_path / "good.csv"
        src.write_text(_csv(2100), encoding="utf-8")
        out = tmp_path / "rep.json"
        r = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "run_data_readiness.py"),
             "--from-csv", str(src), "--import",
             "--base-dir", str(tmp_path / "dh"),
             "--output", str(out)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=120, check=False,
        )
        assert r.returncode == 0, r.stdout[-1500:]
        assert "IMPORTED" in r.stdout
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["real_dataset_available"] is True

    def test_cli_contract(self):
        r = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "run_data_readiness.py"),
             "--contract"],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=120, check=False,
        )
        assert r.returncode == 0
        assert "manual_import_required" in r.stdout
