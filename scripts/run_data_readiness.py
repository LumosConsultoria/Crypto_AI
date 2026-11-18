#!/usr/bin/env python
"""
run_data_readiness.py - Historical Data Readiness BTCUSDT 15m (FASE 36.x)
=========================================================================
ASCII-only. 100% OFFLINE. ZERO rede / API / credencial / secret.

Valida (e opcionalmente importa) um dataset historico de candles no
formato canonico do projeto (timestamp,open,high,low,close,volume; UTC)
e gera o relatorio de prontidao para backtest / walk-forward.

Acoes:
    (default)     valida o dataset no caminho canonico OU --from-csv.
    --from-csv P  valida o CSV em P.
    --import      valida E copia para data/historical/<symbol>/<tf>m/
                  + escreve metadata.json (recusa se NOT_READY).
    --contract    imprime o contrato do CSV que o operador deve fornecer.
    --output P    grava o relatorio JSON (default
                  reports/data_readiness_btcusdt_15m.json).

NUNCA baixa dados. Se faltar dataset real, informa exatamente o que
fornecer (ver --contract).

Exit: 0 ready/ready_with_warnings | 1 not_ready/insufficient/missing.
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
        description="Historical Data Readiness (offline).",
    )
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframe", type=str, default="15")
    p.add_argument("--from-csv", type=str, default="")
    p.add_argument("--import", dest="do_import", action="store_true")
    p.add_argument("--contract", action="store_true")
    p.add_argument(
        "--base-dir", type=str, default="data/historical",
    )
    p.add_argument(
        "--output", type=str,
        default="reports/data_readiness_btcusdt_15m.json",
    )
    args = p.parse_args(argv)

    from crypto_trading_bot.data_readiness import (
        canonical_dataset_path,
        check_readiness_at_canonical_path,
        describe_source_contract,
        import_candle_dataset,
        validate_candle_dataset,
    )

    print()
    print("=" * 72)
    print("  HISTORICAL DATA READINESS (FASE 36.x) - OFFLINE")
    print("  NAO baixa dados. NAO chama API. Formato canonico OHLCV/UTC.")
    print("=" * 72)

    if args.contract:
        contract = describe_source_contract()
        print(json.dumps(contract, indent=2))
        return 0

    # --- importar ---
    if args.do_import:
        if not args.from_csv.strip():
            print("  ERROR --import exige --from-csv <path>")
            return 1
        try:
            report, dest = import_candle_dataset(
                src_csv=args.from_csv, symbol=args.symbol,
                timeframe=args.timeframe, base_dir=args.base_dir,
            )
        except ValueError as e:
            print(f"  ERROR import: {e}")
            return 1
        _print_report(report)
        if dest:
            print(f"  IMPORTED -> {dest}")
            print(f"  metadata -> {Path(dest).parent / 'metadata.json'}")
        else:
            print(
                "  NOT IMPORTED: dataset reprovado na validacao "
                f"(status={report.readiness_status.value})."
            )
        _write(args.output, report.to_dict())
        return 0 if report.real_dataset_available else 1

    # --- validar (from-csv ou caminho canonico) ---
    if args.from_csv.strip():
        path = Path(args.from_csv)
        if any(x == ".." for x in path.parts):
            print("  ERROR --from-csv contem '..'")
            return 1
        report = validate_candle_dataset(
            csv_path=str(path), symbol=args.symbol,
            timeframe=args.timeframe, source="csv_validate",
        )
    else:
        canon = canonical_dataset_path(
            args.symbol, args.timeframe, args.base_dir,
        )
        print(f"  Caminho canonico: {canon}")
        report = check_readiness_at_canonical_path(
            args.symbol, args.timeframe, args.base_dir,
        )
        if report.readiness_status.value == "missing":
            print(
                "  Nenhum dataset real no caminho canonico. Forneca um "
                "CSV (ver --contract) e rode --import."
            )

    _print_report(report)
    _write(args.output, report.to_dict())
    return 0 if report.real_dataset_available else 1


def _print_report(report) -> None:
    d = report.to_dict()
    print()
    print(f"  symbol/timeframe:   {d['symbol']} {d['timeframe']}")
    print(f"  status:             {d['readiness_status']}")
    print(f"  real_available:     {d['real_dataset_available']}")
    print(f"  rows:               {d['rows']}")
    print(f"  coverage_days:      {d['coverage_days']}")
    print(f"  start/end:          {d['start_timestamp']} .. "
          f"{d['end_timestamp']}")
    print(f"  gaps/missing:       {d['gaps_count']} / "
          f"{d['missing_candles_count']}")
    print(f"  duplicates:         {d['duplicates_count']}")
    print(f"  out_of_order:       {d['out_of_order_count']}")
    print(f"  invalid_ohlc:       {d['invalid_ohlc_count']}")
    print(f"  volume_anomalies:   {d['volume_anomalies_count']}")
    print(f"  blocks_backtest:    {d['blocks_backtest']}")
    print(f"  blocks_walk_forward:{d['blocks_walk_forward']}")
    if d["warnings"]:
        print("  warnings:")
        for w in d["warnings"]:
            print(f"    - {w}")
    if d["blockers"]:
        print("  blockers:")
        for b in d["blockers"]:
            print(f"    - {b}")


def _write(path: str, payload: dict) -> None:
    if not path:
        return
    out = Path(path)
    if any(x == ".." for x in out.parts):
        print("  ERROR --output contem '..'")
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
