#!/usr/bin/env python
"""
run_edge_research_phase45.py - Multi-TF Edge Research (FASE 45)
==============================================================
ASCII-only. OFFLINE (le 5m/15m/1h canonicos locais; sem rede/ordem/secret).
1h regime + setups 15m (SL/TP estrutural) + execucao A(15m)/B(5m gatilho).
Janela travada [2025-01-01, 2026-05-31); OOS so apos DEV+VAL. NAO promove
estrategia automaticamente; demo/live bloqueados.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _canonical(base_dir, symbol, tf):
    return Path(base_dir) / symbol.upper() / tf / f"{symbol.upper()}_{tf}.csv"


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Multi-TF Edge Research FASE 45.")
    p.add_argument("--base-dir", default="data/historical")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    p.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    p.add_argument("--oos", nargs=2, default=["2026-02-01", "2026-05-31"])
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument("--wf-folds", type=int, default=5)
    p.add_argument("--hypotheses", default="")
    p.add_argument("--no-oos", action="store_true")
    p.add_argument("--output", default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.research.edge_research_phase45 import (
        run_edge_research45,
    )
    from loguru import logger as _loguru
    _loguru.disable("crypto_trading_bot")   # silencia log por-candle

    print("=" * 72)
    print("  MULTI-TF EDGE RESEARCH (FASE 45) - OFFLINE, sem ordem/rede")
    print("=" * 72)

    paths = {tf: _canonical(args.base_dir, args.symbol, tf)
             for tf in ("5m", "15m", "1h")}
    for tf, pth in paths.items():
        if not pth.is_file():
            print(f"  ERROR dataset ausente: {pth}")
            return 1
    c5 = load_candles_from_csv(str(paths["5m"]), symbol=args.symbol,
                               timeframe="5")
    c15 = load_candles_from_csv(str(paths["15m"]), symbol=args.symbol,
                                timeframe="15")
    c1h = load_candles_from_csv(str(paths["1h"]), symbol=args.symbol,
                                timeframe="60")
    print(f"  5m={len(c5)} | 15m={len(c15)} | 1h={len(c1h)}")

    hyps = ([h.strip() for h in args.hypotheses.split(",") if h.strip()]
            or None)
    t0 = time.monotonic()

    def _prog(m):
        print(f"  [{time.monotonic() - t0:7.1f}s] {m}")

    try:
        rep = run_edge_research45(
            c5, c15, c1h, symbol=args.symbol, dev=tuple(args.dev),
            val=tuple(args.val), oos=tuple(args.oos), capital=args.capital,
            wf_folds=args.wf_folds, hypotheses=hyps,
            run_oos=not args.no_oos, progress=_prog)
    except KeyboardInterrupt:
        print("  INTERROMPIDO; nada promovido.")
        return 1

    d = rep.to_dict()
    print("\n" + "-" * 72)
    print(f"  OVERALL VERDICT: {d['overall_verdict']}")
    for h in d["hypotheses"]:
        print(f"    - {h['hypothesis']}: {h['verdict']} "
              f"[melhor variante: {h['chosen_variant']}]")
        for var, blk in h["variants"].items():
            dev = blk.get("dev", {})
            print(f"        {var}: stop={blk.get('early_stop')} "
                  f"trades={dev.get('total_trades')} "
                  f"pf={dev.get('profit_factor_net')} "
                  f"exp={dev.get('expectancy_net_usd')} "
                  f"setups={dev.get('comparison',{}).get('setups_detected')} "
                  f"%stops<0.5%={dev.get('comparison',{}).get('pct_stops_below_floor')}")
    print(f"  strategy_promoted={d['strategy_promoted']} | "
          f"demo_blocked={d['demo_blocked']} | live_blocked={d['live_blocked']}")
    print(f"  elapsed={time.monotonic() - t0:.1f}s")
    print("-" * 72)

    out = args.output or f"reports/edge_research_phase45_{args.symbol.lower()}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=2, sort_keys=True,
                                    default=str), encoding="utf-8")
    print(f"  Report written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
