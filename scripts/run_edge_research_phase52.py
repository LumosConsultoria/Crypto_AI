"""
run_edge_research_phase52 (FASE 52) — Funding-MR robustez por REGIME.
=====================================================================
Perpetual-ONLY (sem spot/basis). Carrega 1h Bybit linear + funding/OI;
diagnostica se o edge de funding-MR e robustamente concentrado num regime
PRE-especificado (DEV->VAL nao-sobreposto, sem tuning). NAO monta estrategia.
OOS intocado. Sem rede; sem ordem/demo/live.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _rows(path):
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("rows") \
        or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Diagnostico regime FASE 52")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--output", default="reports/edge_research_phase52.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.research.edge_research_phase52 import (
        run_regime_diagnostic)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    sym = args.symbol.upper()
    csv1h = Path(args.base_dir) / sym / "1h" / f"{sym}_1h.csv"
    candles = load_candles_from_csv(str(csv1h), symbol=sym, timeframe="60")
    # so DEV+VAL (OOS intocado): recorta ate val[1]
    from datetime import datetime, timezone

    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lo, hi = _p(args.dev[0]), _p(args.val[1])
    dv = [c for c in candles
          if lo <= (c.timestamp if c.timestamp.tzinfo else
                    c.timestamp.replace(tzinfo=timezone.utc)) < hi]
    funding = load_funding(_rows(args.funding))
    oi = load_open_interest(_rows(args.oi))
    print(f"1h(DEV+VAL)={len(dv)} funding={len(funding)} oi={len(oi)} "
          f"=> diagnostico regime funding-MR (perp-only; OOS intocado)")

    rep = run_regime_diagnostic(
        dv, symbol=sym, funding_points=funding, oi_points=oi,
        dev=tuple(args.dev), val=tuple(args.val),
        progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    g = rep.gate
    print(f"\nGATE: {g['verdict']} | decisao={g['decision']}")
    if g["verdict"] == "SOBREVIVE":
        print(f"  sobreviventes: {g['survivors']}")
    else:
        print(f"  {g['conclusion']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
