"""
Historical Data Readiness - BTCUSDT 15m (FASE 36.x)
====================================================
Validacao OFFLINE de dataset historico de candles para backtest /
walk-forward / calibracao. Reaproveita o formato canonico ja usado
pelo BacktestEngine (timestamp,open,high,low,close,volume; UTC).

⚠️  NUNCA baixa dados (zero rede / zero API / zero credencial).
⚠️  NUNCA libera recomendacao arrojada sem dataset real valido.
⚠️  Thresholds aqui sao de QUALIDADE DE DADOS (defaults de engenharia
    documentados), NAO limites de risco do operador.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from crypto_trading_bot.backtesting.backtest_data import (
    _REQUIRED_COLUMNS,
    _parse_timestamp,
)


# Schema canonico (reaproveitado do BacktestData).
CANONICAL_COLUMNS: Tuple[str, ...] = (
    "timestamp", "open", "high", "low", "close", "volume",
)

# Thresholds de qualidade de dados (defaults documentados, editaveis).
DEFAULT_MIN_ROWS_BACKTEST = 500          # ~5.2 dias de 15m
DEFAULT_MIN_ROWS_WALK_FORWARD = 2000     # ~20.8 dias de 15m
DEFAULT_MAX_GAP_FRACTION = 0.02          # > 2% de candles faltantes = critico
_FLOAT_TOL = 1e-9


class ReadinessStatus(str, Enum):
    READY = "ready"
    READY_WITH_WARNINGS = "ready_with_warnings"
    NOT_READY = "not_ready"
    INSUFFICIENT_DATA = "insufficient_data"
    MISSING = "missing"


@dataclass(frozen=True)
class DataReadinessReport:
    """Relatorio de prontidao do dataset. Frozen, JSON-serializavel."""

    symbol: str
    timeframe: str
    dataset_path: Optional[str]
    source: str
    rows: int
    start_timestamp: Optional[str]
    end_timestamp: Optional[str]
    coverage_days: float
    expected_interval_minutes: int
    gaps_count: int
    missing_candles_count: int
    duplicates_count: int
    out_of_order_count: int
    invalid_ohlc_count: int
    volume_anomalies_count: int
    parse_errors_count: int
    non_utc_normalized_count: int
    checksum: Optional[str]
    readiness_status: ReadinessStatus
    blocks_backtest: bool
    blocks_walk_forward: bool
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    blockers: Tuple[str, ...] = field(default_factory=tuple)
    imported_at: Optional[str] = None

    @property
    def real_dataset_available(self) -> bool:
        """True se ha dataset real utilizavel p/ backtest (nao bloqueia)."""
        return not self.blocks_backtest and self.readiness_status in (
            ReadinessStatus.READY, ReadinessStatus.READY_WITH_WARNINGS,
        )

    def to_dict(self) -> dict:
        return {
            "schema": "data_readiness_v1",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "dataset_path": self.dataset_path,
            "source": self.source,
            "rows": int(self.rows),
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "coverage_days": round(float(self.coverage_days), 4),
            "expected_interval_minutes": int(
                self.expected_interval_minutes
            ),
            "gaps_count": int(self.gaps_count),
            "missing_candles_count": int(self.missing_candles_count),
            "duplicates_count": int(self.duplicates_count),
            "out_of_order_count": int(self.out_of_order_count),
            "invalid_ohlc_count": int(self.invalid_ohlc_count),
            "volume_anomalies_count": int(self.volume_anomalies_count),
            "parse_errors_count": int(self.parse_errors_count),
            "non_utc_normalized_count": int(
                self.non_utc_normalized_count
            ),
            "checksum": self.checksum,
            "readiness_status": self.readiness_status.value,
            "real_dataset_available": self.real_dataset_available,
            "blocks_backtest": bool(self.blocks_backtest),
            "blocks_walk_forward": bool(self.blocks_walk_forward),
            "warnings": list(self.warnings),
            "blockers": list(self.blockers),
            "imported_at": self.imported_at,
            "note": (
                "Offline; sem rede/API. Recomendacao de calibracao "
                "arrojada exige real_dataset_available=True + "
                "blocks_walk_forward=False."
            ),
        }


def _timeframe_minutes(timeframe: str) -> int:
    tf = str(timeframe).strip().lower()
    try:
        if tf.endswith("m"):
            return int(tf[:-1])
        if tf.endswith("h"):
            return int(tf[:-1]) * 60
        return int(tf)
    except (TypeError, ValueError):
        return 15


def _blocked_report(
    *, symbol, timeframe, dataset_path, source,
    status: ReadinessStatus, blockers: Sequence[str],
    checksum: Optional[str] = None,
    invalid_ohlc: int = 0, volume_anomalies: int = 0,
    parse_errors: int = 0, non_utc: int = 0,
) -> DataReadinessReport:
    """Relatorio de bloqueio (missing/not_ready) limpo e consistente."""
    return DataReadinessReport(
        symbol=symbol, timeframe=timeframe,
        dataset_path=(str(dataset_path) if dataset_path else None),
        source=source, rows=0, start_timestamp=None,
        end_timestamp=None, coverage_days=0.0,
        expected_interval_minutes=_timeframe_minutes(timeframe),
        gaps_count=0, missing_candles_count=0, duplicates_count=0,
        out_of_order_count=0, invalid_ohlc_count=invalid_ohlc,
        volume_anomalies_count=volume_anomalies,
        parse_errors_count=parse_errors,
        non_utc_normalized_count=non_utc, checksum=checksum,
        readiness_status=status,
        blocks_backtest=True, blocks_walk_forward=True,
        blockers=tuple(blockers),
    )


def _missing_report(symbol, timeframe, dataset_path, source) -> \
        DataReadinessReport:
    return _blocked_report(
        symbol=symbol, timeframe=timeframe, dataset_path=dataset_path,
        source=source, status=ReadinessStatus.MISSING,
        blockers=("dataset ausente: nenhum CSV historico fornecido",),
    )


def validate_candle_dataset(
    *,
    csv_text: Optional[str] = None,
    csv_path: Optional[str] = None,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    source: str = "csv_import",
    checksum: Optional[str] = None,
    min_rows_backtest: int = DEFAULT_MIN_ROWS_BACKTEST,
    min_rows_walk_forward: int = DEFAULT_MIN_ROWS_WALK_FORWARD,
    max_gap_fraction: float = DEFAULT_MAX_GAP_FRACTION,
) -> DataReadinessReport:
    """Valida um dataset (string OU arquivo). 100% offline.

    Detecta: colunas, parse, ordenacao, duplicidade, OHLC invalido,
    volume negativo/zero, timezone nao-UTC, gaps/candles faltantes,
    cobertura e quantidade minima. NUNCA levanta por dado ruim — tudo
    vira contagem/blocker no relatorio.
    """
    if csv_text is None and csv_path is not None:
        p = Path(csv_path)
        if not p.is_file():
            return _missing_report(symbol, timeframe, csv_path, source)
        raw = p.read_bytes()
        if checksum is None:
            checksum = hashlib.sha256(raw).hexdigest()
        csv_text = raw.decode("utf-8", errors="replace")
    if not csv_text or not csv_text.strip():
        return _missing_report(symbol, timeframe, csv_path, source)
    if checksum is None:
        checksum = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()

    interval = _timeframe_minutes(timeframe)
    reader = csv.DictReader(io.StringIO(csv_text))
    blockers: List[str] = []
    warnings: List[str] = []

    if reader.fieldnames is None:
        return _missing_report(symbol, timeframe, csv_path, source)
    cols = {c.strip().lower() for c in reader.fieldnames}
    missing_cols = _REQUIRED_COLUMNS - cols
    if missing_cols:
        return _blocked_report(
            symbol=symbol, timeframe=timeframe, dataset_path=csv_path,
            source=source, status=ReadinessStatus.NOT_READY,
            checksum=checksum,
            blockers=(
                f"colunas ausentes: {sorted(missing_cols)}; "
                f"obrigatorias: {sorted(_REQUIRED_COLUMNS)}",
            ),
        )

    parse_errors = 0
    invalid_ohlc = 0
    volume_anomalies = 0
    non_utc = 0
    parsed: List[Tuple[datetime, float]] = []  # (ts_utc, volume)

    for i, row in enumerate(reader):
        r = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        try:
            ts = _parse_timestamp(r["timestamp"], row_idx=i)
        except Exception:  # noqa: BLE001
            parse_errors += 1
            continue
        if ts.utcoffset() not in (None, timedelta(0)):
            non_utc += 1
            ts = ts.astimezone(timezone.utc)
        try:
            o = float(r["open"]); h = float(r["high"])
            lo = float(r["low"]); c = float(r["close"])
            vol = float(r["volume"])
        except (KeyError, TypeError, ValueError):
            parse_errors += 1
            continue
        # OHLC valido.
        ohlc_ok = (
            o > 0 and h > 0 and lo > 0 and c > 0
            and h >= max(o, c, lo) - _FLOAT_TOL
            and lo <= min(o, c, h) + _FLOAT_TOL
        )
        if not ohlc_ok:
            invalid_ohlc += 1
        if vol < 0:
            volume_anomalies += 1
        parsed.append((ts, vol))

    rows = len(parsed)
    if rows == 0:
        return _blocked_report(
            symbol=symbol, timeframe=timeframe, dataset_path=csv_path,
            source=source, status=ReadinessStatus.NOT_READY,
            checksum=checksum, invalid_ohlc=invalid_ohlc,
            volume_anomalies=volume_anomalies,
            parse_errors=parse_errors, non_utc=non_utc,
            blockers=("nenhuma linha parseavel",),
        )

    # Ordenacao / duplicidade / gaps (na sequencia ORIGINAL).
    duplicates = 0
    out_of_order = 0
    gaps = 0
    missing_candles = 0
    interval_delta = timedelta(minutes=interval)
    for j in range(1, rows):
        prev_ts = parsed[j - 1][0]
        cur_ts = parsed[j][0]
        delta = cur_ts - prev_ts
        if delta == timedelta(0):
            duplicates += 1
        elif delta < timedelta(0):
            out_of_order += 1
        elif delta > interval_delta:
            gaps += 1
            # candles faltantes inteiros no buraco.
            missing = int(delta / interval_delta) - 1
            if missing > 0:
                missing_candles += missing

    ts_sorted = sorted(p[0] for p in parsed)
    start_ts, end_ts = ts_sorted[0], ts_sorted[-1]
    coverage_days = max(
        0.0, (end_ts - start_ts).total_seconds() / 86400.0,
    )
    expected_candles = max(
        1, int((end_ts - start_ts) / interval_delta) + 1,
    )
    gap_fraction = missing_candles / expected_candles

    # --- classificacao ---
    if invalid_ohlc > 0:
        blockers.append(f"invalid_ohlc_count={invalid_ohlc} > 0")
    if duplicates > 0:
        blockers.append(f"duplicates_count={duplicates} > 0")
    if out_of_order > 0:
        blockers.append(f"out_of_order_count={out_of_order} > 0")
    if volume_anomalies > 0:
        blockers.append(
            f"volume_anomalies_count={volume_anomalies} > 0 "
            "(volume negativo)"
        )
    if parse_errors > 0:
        warnings.append(f"parse_errors_count={parse_errors}")
    if non_utc > 0:
        warnings.append(
            f"non_utc_normalized_count={non_utc} (normalizado p/ UTC)"
        )
    if gaps > 0:
        warnings.append(
            f"gaps_count={gaps}; missing_candles={missing_candles} "
            f"({gap_fraction*100:.2f}% do esperado)"
        )

    critical_gaps = gap_fraction > max_gap_fraction
    insufficient = rows < min_rows_backtest
    hard_invalid = bool(
        invalid_ohlc or duplicates or out_of_order or volume_anomalies
    )

    if hard_invalid:
        status = ReadinessStatus.NOT_READY
    elif insufficient:
        status = ReadinessStatus.INSUFFICIENT_DATA
        blockers.append(
            f"rows={rows} < min_rows_backtest={min_rows_backtest}"
        )
    elif critical_gaps:
        status = ReadinessStatus.NOT_READY
        blockers.append(
            f"gap_fraction={gap_fraction*100:.2f}% > "
            f"{max_gap_fraction*100:.2f}% (gaps criticos)"
        )
    elif warnings:
        status = ReadinessStatus.READY_WITH_WARNINGS
    else:
        status = ReadinessStatus.READY

    blocks_backtest = status in (
        ReadinessStatus.NOT_READY, ReadinessStatus.INSUFFICIENT_DATA,
        ReadinessStatus.MISSING,
    )
    blocks_walk_forward = (
        blocks_backtest
        or rows < min_rows_walk_forward
        or critical_gaps
    )
    if (not blocks_backtest) and rows < min_rows_walk_forward:
        warnings.append(
            f"rows={rows} < min_rows_walk_forward="
            f"{min_rows_walk_forward}: walk-forward bloqueado"
        )

    return DataReadinessReport(
        symbol=symbol, timeframe=timeframe,
        dataset_path=(str(csv_path) if csv_path else None),
        source=source, rows=rows,
        start_timestamp=start_ts.isoformat(),
        end_timestamp=end_ts.isoformat(),
        coverage_days=coverage_days,
        expected_interval_minutes=interval,
        gaps_count=gaps, missing_candles_count=missing_candles,
        duplicates_count=duplicates, out_of_order_count=out_of_order,
        invalid_ohlc_count=invalid_ohlc,
        volume_anomalies_count=volume_anomalies,
        parse_errors_count=parse_errors,
        non_utc_normalized_count=non_utc, checksum=checksum,
        readiness_status=status,
        blocks_backtest=blocks_backtest,
        blocks_walk_forward=blocks_walk_forward,
        warnings=tuple(warnings), blockers=tuple(blockers),
    )


def canonical_dataset_path(
    symbol: str = "BTCUSDT", timeframe: str = "15",
    base_dir: str = "data/historical",
) -> Path:
    """Caminho canonico do dataset: data/historical/<symbol>/<tf>m/<symbol>_<tf>m.csv."""
    tf = str(timeframe).strip().lower()
    tf_dir = tf if tf.endswith(("m", "h")) else f"{tf}m"
    return (
        Path(base_dir) / symbol / tf_dir / f"{symbol}_{tf_dir}.csv"
    )


def check_readiness_at_canonical_path(
    symbol: str = "BTCUSDT", timeframe: str = "15",
    base_dir: str = "data/historical", **kw,
) -> DataReadinessReport:
    """Conveniencia: valida o dataset no caminho canonico (ou MISSING)."""
    path = canonical_dataset_path(symbol, timeframe, base_dir)
    return validate_candle_dataset(
        csv_path=str(path), symbol=symbol, timeframe=timeframe,
        source="canonical_local", **kw,
    )


def import_candle_dataset(
    *,
    src_csv: str,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    base_dir: str = "data/historical",
    source: str = "csv_import",
    allow_warnings: bool = True,
    now: Optional[datetime] = None,
) -> Tuple[DataReadinessReport, Optional[str]]:
    """Valida + (se aprovado) copia para o caminho canonico + metadata.

    Recusa import se NOT_READY/INSUFFICIENT/MISSING. allow_warnings=True
    permite importar READY_WITH_WARNINGS. Retorna (report, dest_path).
    """
    import json as _json
    now = now or datetime.now(timezone.utc)
    src = Path(src_csv)
    if any(p == ".." for p in src.parts):
        raise ValueError("src_csv contem '..'")
    report = validate_candle_dataset(
        csv_path=str(src), symbol=symbol, timeframe=timeframe,
        source=source,
    )
    ok_status = {ReadinessStatus.READY}
    if allow_warnings:
        ok_status.add(ReadinessStatus.READY_WITH_WARNINGS)
    if report.readiness_status not in ok_status:
        return report, None

    dest = canonical_dataset_path(symbol, timeframe, base_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    metadata = {
        **report.to_dict(),
        "imported_at": now.isoformat(),
        "canonical_path": str(dest),
        "original_source_file": str(src),
    }
    (dest.parent / "metadata.json").write_text(
        _json.dumps(metadata, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    return report, str(dest)


# ---------------------------------------------------------------------------
# Contrato de fontes futuras (NAO implementadas; sem rede agora)
# ---------------------------------------------------------------------------

SUPPORTED_FUTURE_SOURCES: Tuple[str, ...] = (
    "bybit_historical_klines",
    "binance_historical_klines",
    "exported_file",
    "kaggle_dataset",
)


def describe_source_contract() -> dict:
    """Contrato do CSV que o operador deve fornecer (sem buscar API)."""
    return {
        "schema": "source_contract_v1",
        "required_columns": list(CANONICAL_COLUMNS),
        "timestamp_format": (
            "ISO 8601 UTC, ex.: 2026-01-01T00:00:00Z "
            "(ou Unix ms/s; offsets nao-UTC sao normalizados)"
        ),
        "example_row": (
            "2026-01-01T00:00:00Z,43000.0,43100.0,42900.0,"
            "43050.0,123.45"
        ),
        "future_sources": list(SUPPORTED_FUTURE_SOURCES),
        "fetch_status": "manual_import_required",
        "note": (
            "Nenhuma fonte real e chamada automaticamente. O operador "
            "exporta um CSV no formato canonico e roda "
            "scripts/run_data_readiness.py --import."
        ),
    }


__all__ = [
    "CANONICAL_COLUMNS",
    "DEFAULT_MAX_GAP_FRACTION",
    "DEFAULT_MIN_ROWS_BACKTEST",
    "DEFAULT_MIN_ROWS_WALK_FORWARD",
    "DataReadinessReport",
    "ReadinessStatus",
    "SUPPORTED_FUTURE_SOURCES",
    "canonical_dataset_path",
    "check_readiness_at_canonical_path",
    "describe_source_contract",
    "import_candle_dataset",
    "validate_candle_dataset",
]
