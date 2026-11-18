"""
run_bybit_aux_fetch (FASE 47) — fetch publico read-only de funding/OI/instrument
================================================================================
Baixa (PUBLICO, read-only, SEM auth) da Bybit V5 LINEAR: funding history,
open interest e instrument info; salva canonico + provenance + cobertura.
GATED: so faz rede com --allow-network. Passo 0 = AUDITORIA de cobertura
(contagem/first-last); OI pode ter retencao limitada.

Uso (apos autorizacao do operador):
  python scripts/run_bybit_aux_fetch.py --symbol BTCUSDT \
      --start 2025-01-01 --end 2026-05-31 --oi-interval 60 \
      --out-dir data/perp --allow-network
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse(d):
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _cov(rows, kind):
    n = len(rows)
    first = rows[0]["timestamp"] if rows else None
    last = rows[-1]["timestamp"] if rows else None
    return {"kind": kind, "rows": n, "first": first, "last": last}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Bybit aux fetch (FASE 47)")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--oi-interval", type=int, default=60,
                    help="minutos do OI (5/15/30/60/240/1440)")
    ap.add_argument("--out-dir", default="data/perp")
    ap.add_argument("--allow-network", action="store_true",
                    help="OBRIGATORIO p/ tocar a rede (gated)")
    ap.add_argument("--skip-funding", action="store_true")
    ap.add_argument("--skip-oi", action="store_true")
    args = ap.parse_args(argv)

    if not args.allow_network:
        print("BLOQUEADO: rede gated. Use --allow-network (autorizado pelo "
              "operador) para baixar dados publicos read-only.")
        return 3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from crypto_trading_bot.historical_data.aux_providers import (
        BybitFundingProvider, BybitInstrumentProvider,
        BybitOpenInterestProvider)

    start, end = _parse(args.start), _parse(args.end)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sym = args.symbol.upper()
    coverage = {}
    prov_meta = {"market": "bybit_linear_perp", "symbol": sym,
                 "window": [args.start, args.end],
                 "fetched_at": datetime.now(timezone.utc).isoformat()}

    if not args.skip_funding:
        print("baixando funding history (publico read-only)...")
        f = BybitFundingProvider().fetch_funding(symbol=sym, start=start,
                                                 end=end)
        (out / f"funding_{sym}.json").write_text(
            json.dumps({"provenance": prov_meta, "rows": f}, indent=2),
            encoding="utf-8")
        coverage["funding"] = _cov(f, "funding")

    if not args.skip_oi:
        print(f"baixando open interest ({args.oi_interval}m)...")
        oi = BybitOpenInterestProvider().fetch_open_interest(
            symbol=sym, tf_minutes=args.oi_interval, start=start, end=end)
        (out / f"oi_{sym}_{args.oi_interval}m.json").write_text(
            json.dumps({"provenance": prov_meta, "rows": oi}, indent=2),
            encoding="utf-8")
        coverage["open_interest"] = _cov(oi, "open_interest")

    print("baixando instrument info...")
    inst = BybitInstrumentProvider().fetch_instrument(symbol=sym)
    (out / f"instrument_{sym}.json").write_text(
        json.dumps({"provenance": prov_meta, "instrument": inst}, indent=2),
        encoding="utf-8")

    report = {"schema": "bybit_aux_coverage_v1", "provenance": prov_meta,
              "coverage": coverage, "instrument_available":
              inst.get("available")}
    (out / f"coverage_{sym}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
