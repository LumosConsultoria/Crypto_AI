"""
run_edge_research_phase59 — H1 failed_breakout_fade_5m (BTCUSDT 5m).
====================================================================
DEV primeiro; VAL so se DEV passar os 8 criterios; OOS intocado. dual-profile;
custos reais Bybit + funding. Params pre-fixados. Sem ordem/demo/live.
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edge research FASE 59 (H1 5m)")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--wf-folds", type=int, default=5)
    ap.add_argument("--output", default="reports/edge_research_phase59.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.research.edge_research_phase59 import (
        run_edge_research59)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    sym = args.symbol.upper()
    csv5m = Path(args.base_dir) / sym / "5m" / f"{sym}_5m.csv"
    candles = load_candles_from_csv(str(csv5m), symbol=sym, timeframe="5")

    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lo, hi = _p(args.dev[0]), _p(args.val[1])
    dv = [c for c in candles
          if lo <= (c.timestamp if c.timestamp.tzinfo else
                    c.timestamp.replace(tzinfo=timezone.utc)) < hi]
    funding = load_funding(_rows(args.funding))
    oi = load_open_interest(_rows(args.oi))
    store = (OperatorInputStore(args.operator_inputs)
             if Path(args.operator_inputs).is_file() else None)
    print(f"5m(DEV+VAL)={len(dv)} funding={len(funding)} => H1 "
          f"failed_breakout_fade (dual-profile; OOS intocado)")

    rep = run_edge_research59(
        dv, symbol=sym, funding_points=funding, oi_points=oi,
        dev=tuple(args.dev), val=tuple(args.val), operator_store=store,
        wf_folds=args.wf_folds, progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    d = rep.to_dict()
    h = d["hypothesis"]
    dev = h["dev"]
    sm = dev.get("strategy_metrics") or {}
    g = dev.get("gate") or {}
    att = dev.get("hyro_challenge_attempts") or {}
    print(f"\nDECISAO: {d['decision']}")
    print(f"  DEV: setups={h['n_setups']} trades={sm.get('num_trades')} "
          f"net={sm.get('net_pnl_usd')} PF={sm.get('profit_factor_net')} "
          f"class={dev.get('classification')} gate_passed={g.get('passed')}")
    print(f"  gate checks: {g.get('checks')}")
    print(f"  hyro_attempts: total={att.get('total_attempts')} "
          f"pass_rate={att.get('pass_rate')}")
    if "val" in h:
        vsm = h["val"].get("strategy_metrics") or {}
        vg = h["val"].get("gate") or {}
        print(f"  VAL: trades={vsm.get('num_trades')} net={vsm.get('net_pnl_usd')} "
              f"PF={vsm.get('profit_factor_net')} gate_passed={vg.get('passed')}")
    print(f"  MOTIVO: {d['reason']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
