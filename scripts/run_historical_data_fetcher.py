#!/usr/bin/env python
"""
run_historical_data_fetcher.py - Historical Data Fetcher (FASE 37 A/B)
======================================================================
ASCII-only. ZERO ordem / execucao / credencial de trade. Provider real
usa SOMENTE endpoint PUBLICO read-only de mercado (klines).

Busca candles historicos de um provider read-only, normaliza para o CSV
canonico OHLCV/UTC (timestamp,open,high,low,close,volume), grava em
data/historical/<SYMBOL>/<TIMEFRAME>/ + metadata.json e (opcional)
aciona Data Readiness.

Nada hardcoded: provider/symbol/timeframe/range vem do operador.

Inputs OBRIGATORIOS:
    --provider {fake|binance}   fake = offline deterministico (default
                                seguro); binance = publico read-only.
    --symbol    SYMBOL          ex.: BTCUSDT (sem hardcode interno)
    --timeframe TF              ex.: 15m, 1h, 1d
    --start-date YYYY-MM-DD     UTC
    --end-date   YYYY-MM-DD     UTC (deve ser > start-date)

Flags:
    --output P        caminho explicito do CSV (default: canonico)
    --base-dir D      base do caminho canonico (default data/historical)
    --force           sobrescreve dataset existente (controlado)
    --dry-run         busca e valida, NAO grava nada
    --validate-only   so valida os inputs (nao baixa)
    --run-readiness   roda Data Readiness apos gravar
    --allow-network   OBRIGATORIO para provider real (binance). Sem ele,
                      provider real eh recusado (default offline-safe).
    --report-output P grava o relatorio JSON do fetch.

Exit: 0 sucesso/dry-run/validate-only | 1 erro/overwrite-bloqueado.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Historical Data Fetcher (read-only).",
    )
    p.add_argument("--provider", type=str, required=True,
                   help="fake (offline) | binance (publico read-only)")
    p.add_argument("--symbol", type=str, required=True)
    p.add_argument("--timeframe", type=str, required=True)
    p.add_argument("--start-date", dest="start_date", type=str,
                   required=True)
    p.add_argument("--end-date", dest="end_date", type=str,
                   required=True)
    p.add_argument("--output", type=str, default="")
    p.add_argument("--base-dir", type=str, default="data/historical")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--validate-only", dest="validate_only",
                   action="store_true")
    p.add_argument("--run-readiness", dest="run_readiness",
                   action="store_true")
    p.add_argument("--allow-network", dest="allow_network",
                   action="store_true")
    p.add_argument("--report-output", dest="report_output", type=str,
                   default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.historical_data import (
        HistoricalDataError,
        fetch_historical,
        get_provider,
    )

    print()
    print("=" * 72)
    print("  HISTORICAL DATA FETCHER (FASE 37) - READ-ONLY")
    print("  ZERO ordem/execucao. Provider real = klines PUBLICO.")
    print("=" * 72)

    # Resolve provider so para inspecionar is_real (sem rede).
    try:
        prov = get_provider(args.provider)
    except HistoricalDataError as e:
        print(f"  ERROR provider: {e}")
        return 1

    # Guard de rede: provider real exige --allow-network explicito.
    if prov.is_real and not args.allow_network and not args.validate_only:
        print(
            f"  BLOCKED provider real '{prov.name}' exige --allow-network "
            "explicito (chamada de rede read-only). Use --provider fake "
            "para gerar dados offline deterministicos."
        )
        return 1

    try:
        result = fetch_historical(
            provider=args.provider,
            symbol=args.symbol,
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            output_path=(args.output or None),
            base_dir=args.base_dir,
            force=args.force,
            dry_run=args.dry_run,
            validate_only=args.validate_only,
            run_readiness=args.run_readiness,
        )
    except HistoricalDataError as e:
        print(f"  ERROR fetch: {e}")
        return 1

    _print_result(result)

    if args.report_output:
        _write(args.report_output, result.to_dict())

    if result.overwrite_blocked or result.errors:
        return 1
    return 0


def _print_result(r) -> None:
    d = r.to_dict()
    print()
    print(f"  provider:           {d['provider']} "
          f"(real={d['provider_is_real']})")
    print(f"  symbol/timeframe:   {d['symbol']} {d['timeframe']}")
    print(f"  range solicitado:   {d['start_date']} .. {d['end_date']}")
    print(f"  rows_downloaded:    {d['rows_downloaded']}")
    print(f"  rows_saved:         {d['rows_saved']}")
    print(f"  first/last ts:      {d['first_timestamp']} .. "
          f"{d['last_timestamp']}")
    print(f"  checksum_sha256:    {d['checksum']}")
    print(f"  dataset_path:       {d['dataset_path']}")
    print(f"  metadata_path:      {d['metadata_path']}")
    print(f"  readiness_status:   {d['readiness_status']}")
    print(f"  dry_run:            {d['dry_run']}")
    print(f"  validate_only:      {d['validate_only']}")
    print(f"  overwrite_blocked:  {d['overwrite_blocked']}")
    if d["warnings"]:
        print("  warnings:")
        for w in d["warnings"]:
            print(f"    - {w}")
    if d["errors"]:
        print("  errors:")
        for e in d["errors"]:
            print(f"    - {e}")


def _write(path: str, payload: dict) -> None:
    if not path:
        return
    out = Path(path)
    if any(x == ".." for x in out.parts):
        print("  ERROR --report-output contem '..'")
        return
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if any(t in text.lower() for t in _SECRET_TOKENS):
        print("  ERROR token suspeito no report; nao gravado")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    sys.exit(main())
