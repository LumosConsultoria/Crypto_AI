"""
run_signal_lab_phase49 (FASE 49) — laboratorio de diagnostico de sinais.
========================================================================
Carrega 1h Bybit linear (canonico) + funding/OI; FATIA em DEV+VAL (OOS
preservado) e mede o poder preditivo das features vs retorno futuro em
multiplos horizontes. NAO monta estrategia. Sem rede; sem ordem/demo/live.

Uso:
  python scripts/run_signal_lab_phase49.py --base-dir data/historical \
      --funding data/perp/funding_BTCUSDT.json --oi data/perp/oi_BTCUSDT_60m.json \
      --dev-start 2025-01-01 --val-end 2026-02-01 \
      --output reports/signal_lab_phase49_btcusdt.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _rows(path):
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("rows") \
        or []


def _slice(candles, start, end):
    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out = []
    for c in candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if s <= ts < e:
            out.append(c)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Signal Diagnostic Lab FASE 49")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--dev-start", default="2025-01-01")
    ap.add_argument("--val-end", default="2026-02-01",
                    help="fim de VAL (exclusivo); OOS (>= esta data) NUNCA "
                         "carregado p/ o lab")
    ap.add_argument("--output", default="reports/signal_lab_phase49.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.research.edge_research_phase49 import run_signal_lab
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    sym = args.symbol.upper()
    csv1h = Path(args.base_dir) / sym / "1h" / f"{sym}_1h.csv"
    candles = load_candles_from_csv(str(csv1h), symbol=sym, timeframe="60")
    dev_val = _slice(candles, args.dev_start, args.val_end)
    funding = load_funding(_rows(args.funding))
    oi = load_open_interest(_rows(args.oi))
    print(f"1h total={len(candles)} | DEV+VAL={len(dev_val)} "
          f"[{args.dev_start}..{args.val_end}) (OOS preservado) | "
          f"funding={len(funding)} oi={len(oi)}")

    rep = run_signal_lab(dev_val, symbol=sym, funding_points=funding,
                         oi_points=oi, progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    d = rep.diagnosis
    print("\n=== DIAGNOSTICO ===")
    print("promising:", d["promising"])
    print("real_relation:", d["real_relation"])
    print("regime_specific:", d["regime_specific"])
    print("dies_after_cost:", d["dies_after_cost"])
    print("noise:", d["noise"])
    print("insufficient_sample:", d["insufficient_sample"])
    print("PROPOSAL has_signal:", rep.proposal.get("has_signal"))
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
