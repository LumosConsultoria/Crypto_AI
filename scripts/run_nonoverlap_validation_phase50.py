"""
run_nonoverlap_validation_phase50 (FASE 50) — validacao nao-sobreposta.
=======================================================================
Carrega 1h Bybit linear + funding/OI; fatia em DEV+VAL (OOS preservado);
valida os sinais promissores da FASE 49 com janelas DISJUNTAS em varios
offsets (3d/5d/7d). NAO monta estrategia. Sem rede; sem ordem/demo/live.

Uso:
  python scripts/run_nonoverlap_validation_phase50.py --base-dir data/historical \
      --funding data/perp/funding_BTCUSDT.json --oi data/perp/oi_BTCUSDT_60m.json \
      --dev-start 2025-01-01 --val-end 2026-02-01 \
      --output reports/nonoverlap_validation_phase50_btcusdt.json
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
    ap = argparse.ArgumentParser(description="Non-overlap validation FASE 50")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--dev-start", default="2025-01-01")
    ap.add_argument("--val-end", default="2026-02-01")
    ap.add_argument("--output",
                    default="reports/nonoverlap_validation_phase50.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.research.edge_research_phase50 import (
        run_nonoverlap_validation)
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

    rep = run_nonoverlap_validation(dev_val, symbol=sym,
                                    funding_points=funding, oi_points=oi,
                                    progress=lambda m: print(f"  {m}"))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    print("\n=== SIDE-BY-SIDE (overlapping FASE49 vs non-overlap FASE50) ===")
    for s in rep.signals:
        for h, v in s["by_horizon"].items():
            sb = v["side_by_side"]
            print("%-24s %s | overlap net=%s ic=%s || nonoverlap net=%s ic=%s "
                  "| frac_off+=%s msc=%s fired=%s => %s" % (
                      s["signal"], h, sb["overlapping_net"], sb["overlapping_ic"],
                      sb["nonoverlap_mean_net"], sb["nonoverlap_mean_ic"],
                      v["nonoverlap"].get("frac_offsets_net_positive"),
                      v["nonoverlap"].get("monthly_sign_consistency"),
                      v["nonoverlap"].get("total_nonoverlap_fired"),
                      v["survival"]))
    print("\nDIAGNOSTICO:", rep.diagnosis["conclusion"])
    print("survivors:", rep.diagnosis["survivors"])
    print("DECISAO:", rep.decision["verdict"])
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
