"""
Historical Data Fetcher (FASE 37 Parte A/B)
============================================
Orquestra: validar inputs -> buscar via provider read-only -> normalizar
para CSV canonico -> metadata.json -> (opcional) Data Readiness.

⚠️  ZERO ordem / execucao. Provider real so read-only publico.
⚠️  Nao sobrescreve dataset existente sem --force. Suporta dry-run e
    validate-only. NUNCA imprime/persiste secrets.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from crypto_trading_bot.historical_data.providers import (
    CandleRow,
    HistoricalDataError,
    HistoricalDataProvider,
    get_provider,
    validate_fetch_request,
)

CANONICAL_SCHEMA_VERSION = "candle_ohlcv_utc_v1"
_CANONICAL_HEADER = "timestamp,open,high,low,close,volume"


@dataclass(frozen=True)
class FetchResult:
    """Resultado do fetcher (Part I report). Sem secrets."""
    provider: str
    provider_is_real: bool
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    rows_downloaded: int
    rows_saved: int
    first_timestamp: Optional[str]
    last_timestamp: Optional[str]
    checksum: Optional[str]
    dataset_path: Optional[str]
    metadata_path: Optional[str]
    readiness_status: Optional[str]
    readiness_report_path: Optional[str]
    dry_run: bool
    validate_only: bool
    overwrite_blocked: bool = False
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    errors: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "schema": "historical_fetch_report_v1",
            "provider": self.provider,
            "provider_is_real": bool(self.provider_is_real),
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "rows_downloaded": int(self.rows_downloaded),
            "rows_saved": int(self.rows_saved),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "checksum": self.checksum,
            "dataset_path": self.dataset_path,
            "metadata_path": self.metadata_path,
            "readiness_status": self.readiness_status,
            "readiness_report_path": self.readiness_report_path,
            "dry_run": bool(self.dry_run),
            "validate_only": bool(self.validate_only),
            "overwrite_blocked": bool(self.overwrite_blocked),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _rows_to_csv_text(rows: List[CandleRow]) -> str:
    # lineterminator='\n' (canonico): evita '\r\r\n' ao gravar em
    # Windows; checksum e arquivo ficam consistentes (newline='').
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["timestamp", "open", "high", "low", "close",
                     "volume"])
    for r in rows:
        d = r.to_csv_dict()
        writer.writerow([d["timestamp"], d["open"], d["high"],
                         d["low"], d["close"], d["volume"]])
    return buf.getvalue()


def _dedup_sort(rows: List[CandleRow]) -> List[CandleRow]:
    """Ordena por timestamp e remove duplicatas exatas de timestamp."""
    seen = set()
    out: List[CandleRow] = []
    for r in sorted(rows, key=lambda x: x.timestamp):
        key = r.timestamp
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def fetch_historical(
    *,
    provider: str,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
    output_path: Optional[str] = None,
    base_dir: str = "data/historical",
    force: bool = False,
    dry_run: bool = False,
    validate_only: bool = False,
    run_readiness: bool = False,
    allowed_symbols: Optional[Tuple[str, ...]] = None,
    provider_obj: Optional[HistoricalDataProvider] = None,
    readiness_report_dir: str = "reports",
) -> FetchResult:
    """Busca + normaliza + salva candles historicos. Read-only.

    provider_obj: injecao p/ testes (FakeHistoricalProvider). Em
    producao, resolvido por nome via get_provider.
    """
    warnings: List[str] = []

    tf_label, tf_min, start, end = validate_fetch_request(
        symbol=symbol, timeframe=timeframe,
        start_date=start_date, end_date=end_date,
        allowed_symbols=allowed_symbols,
    )
    sym = symbol.strip().upper()

    prov = provider_obj or get_provider(provider)
    dest = (
        Path(output_path) if output_path
        else _canonical_path(base_dir, sym, tf_label)
    )
    if any(p == ".." for p in dest.parts):
        raise HistoricalDataError("output path contem '..'")

    # validate-only: nao baixa nada; so checa inputs + existencia.
    if validate_only:
        return FetchResult(
            provider=prov.name, provider_is_real=prov.is_real,
            symbol=sym, timeframe=tf_label, start_date=start_date,
            end_date=end_date, rows_downloaded=0, rows_saved=0,
            first_timestamp=None, last_timestamp=None, checksum=None,
            dataset_path=str(dest), metadata_path=None,
            readiness_status=None, readiness_report_path=None,
            dry_run=dry_run, validate_only=True,
            warnings=("validate_only: inputs validos; nada baixado",),
        )

    # Guard de sobrescrita.
    overwrite_blocked = dest.exists() and not force and not dry_run
    if overwrite_blocked:
        return FetchResult(
            provider=prov.name, provider_is_real=prov.is_real,
            symbol=sym, timeframe=tf_label, start_date=start_date,
            end_date=end_date, rows_downloaded=0, rows_saved=0,
            first_timestamp=None, last_timestamp=None, checksum=None,
            dataset_path=str(dest), metadata_path=None,
            readiness_status=None, readiness_report_path=None,
            dry_run=dry_run, validate_only=False,
            overwrite_blocked=True,
            errors=(
                f"dataset ja existe: {dest}. Use --force para "
                "sobrescrever (controlado).",
            ),
        )

    # Busca (read-only; provider real so aqui).
    raw = prov.fetch_candles(
        symbol=sym, tf_minutes=tf_min, start=start, end=end,
    )
    rows = _dedup_sort(raw)
    if len(rows) != len(raw):
        warnings.append(
            f"duplicatas removidas: {len(raw) - len(rows)}"
        )
    if not rows:
        return FetchResult(
            provider=prov.name, provider_is_real=prov.is_real,
            symbol=sym, timeframe=tf_label, start_date=start_date,
            end_date=end_date, rows_downloaded=len(raw), rows_saved=0,
            first_timestamp=None, last_timestamp=None, checksum=None,
            dataset_path=str(dest), metadata_path=None,
            readiness_status=None, readiness_report_path=None,
            dry_run=dry_run, validate_only=False,
            errors=("provider retornou 0 candles no range",),
        )

    csv_text = _rows_to_csv_text(rows)
    checksum = hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    first_ts = rows[0].timestamp.astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_ts = rows[-1].timestamp.astimezone(
        timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if dry_run:
        return FetchResult(
            provider=prov.name, provider_is_real=prov.is_real,
            symbol=sym, timeframe=tf_label, start_date=start_date,
            end_date=end_date, rows_downloaded=len(raw),
            rows_saved=0, first_timestamp=first_ts,
            last_timestamp=last_ts, checksum=checksum,
            dataset_path=str(dest), metadata_path=None,
            readiness_status=None, readiness_report_path=None,
            dry_run=True, validate_only=False,
            warnings=tuple(warnings + ["dry_run: nada gravado"]),
        )

    # Grava CSV + metadata.
    dest.parent.mkdir(parents=True, exist_ok=True)
    # newline="" => sem traducao de '\n' (bytes == checksum).
    dest.write_text(csv_text, encoding="utf-8", newline="")
    metadata = {
        "provider": prov.name,
        "provider_is_real": prov.is_real,
        "symbol": sym,
        "timeframe": tf_label,
        "start_date": start_date,
        "end_date": end_date,
        "rows": len(rows),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "checksum_sha256": checksum,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_type": "real" if prov.is_real else "synthetic_fake",
        "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
    }
    meta_path = dest.parent / "metadata.json"
    meta_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    readiness_status = None
    readiness_path = None
    if run_readiness:
        from crypto_trading_bot.data_readiness import (
            validate_candle_dataset,
        )
        rep = validate_candle_dataset(
            csv_text=csv_text, symbol=sym, timeframe=tf_label,
            source=f"fetcher:{prov.name}", checksum=checksum,
        )
        readiness_status = rep.readiness_status.value
        rdir = Path(readiness_report_dir)
        if not any(p == ".." for p in rdir.parts):
            rdir.mkdir(parents=True, exist_ok=True)
            readiness_path = str(
                rdir / f"data_readiness_{sym.lower()}_{tf_label}.json"
            )
            Path(readiness_path).write_text(
                json.dumps(rep.to_dict(), indent=2, sort_keys=True,
                           default=str),
                encoding="utf-8",
            )
        if rep.blocks_backtest:
            warnings.append(
                f"readiness={readiness_status}: dataset NAO apto a "
                "backtest ainda"
            )

    return FetchResult(
        provider=prov.name, provider_is_real=prov.is_real,
        symbol=sym, timeframe=tf_label, start_date=start_date,
        end_date=end_date, rows_downloaded=len(raw),
        rows_saved=len(rows), first_timestamp=first_ts,
        last_timestamp=last_ts, checksum=checksum,
        dataset_path=str(dest), metadata_path=str(meta_path),
        readiness_status=readiness_status,
        readiness_report_path=readiness_path,
        dry_run=False, validate_only=False,
        warnings=tuple(warnings),
    )


def _canonical_path(base_dir: str, symbol: str, tf_label: str) -> Path:
    return Path(base_dir) / symbol / tf_label / f"{symbol}_{tf_label}.csv"


__all__ = [
    "CANONICAL_SCHEMA_VERSION",
    "FetchResult",
    "fetch_historical",
]
